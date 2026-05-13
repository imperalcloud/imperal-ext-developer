"""Secrets tab for the Developer Portal App Details dashboard.

Renders one inline form per declared secret in the app's manifest. The
developer (= the app's owner) pastes the value directly here; submit
PUTs to auth-gw /v1/secrets/{app_id}/{secret_name} via service-token +
X-Acting-User. Plaintext never touches our DB column except briefly in
Vault transit between encrypt/decrypt — federal I-SECRETS-NEVER-LOGGED
contract intact.

If the app declares no secrets, shows an empty state with the canonical
@ext.secret(...) code example so the developer knows how to declare one.
"""
from __future__ import annotations

import json
from typing import Any

from imperal_sdk import ui

from app import _gw_get


async def build_secrets(uid: str, app_id: str, **_kwargs: Any) -> Any:
    """Render the Secrets tab content for a single app."""
    if not app_id:
        return ui.Alert(
            title="Select an app",
            message="Pick an app from the sidebar to manage its secrets.",
            type="info",
        )

    # Fetch app row (which now has manifest_json since dev-ext v1.2.3 syncs it).
    try:
        app = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as exc:
        return ui.Alert(
            title="Cannot load app",
            message=f"{type(exc).__name__}: {exc}",
            type="error",
        )

    manifest_raw = app.get("manifest_json") if isinstance(app, dict) else None
    declared: list[dict] = []
    if isinstance(manifest_raw, str) and manifest_raw.strip():
        try:
            mf = json.loads(manifest_raw)
            arr = mf.get("secrets") if isinstance(mf, dict) else None
            if isinstance(arr, list):
                declared = [s for s in arr if isinstance(s, dict) and s.get("name")]
        except Exception:
            declared = []
    elif isinstance(manifest_raw, dict):
        arr = manifest_raw.get("secrets")
        if isinstance(arr, list):
            declared = [s for s in arr if isinstance(s, dict) and s.get("name")]

    # Empty state — guide the developer
    if not declared:
        return ui.Stack(children=[
            ui.Alert(
                title="No secrets declared in this app's manifest",
                message=(
                    "This extension does not declare any @ext.secret(...) entries. "
                    "Add a declaration to your app.py and redeploy to manage credentials here."
                ),
                type="info",
            ),
            ui.Section(title="How to declare a secret", children=[
                ui.Markdown(content=(
                    "```python\n"
                    "ext.secret(\n"
                    "    name=\"openai_api_key\",\n"
                    "    description=\"Your OpenAI API key (sk-proj-...).\",\n"
                    "    required=True,\n"
                    "    write_mode=\"user\",       # user pastes via Panel\n"
                    "    max_bytes=200,\n"
                    ")(lambda: None)\n"
                    "```\n"
                    "After git push + Deploy, the field appears in this Secrets tab "
                    "ready for value entry. Plaintext is encrypted in Vault transit; "
                    "never logged, never visible to admins."
                )),
                ui.Link(
                    text="@ext.secret reference →",
                    href="https://docs.imperal.io/en/sdk/decorator-secret-reference/",
                ),
            ]),
        ], gap=2)

    # Fetch current is_set state for each declared secret in one shot.
    statuses: dict[str, dict] = {}
    try:
        live = await _gw_get(f"/v1/secrets/{app_id}")
        if isinstance(live, list):
            for item in live:
                if isinstance(item, dict) and item.get("name"):
                    statuses[item["name"]] = item
    except Exception:
        statuses = {}

    rows = [
        ui.Alert(
            title=f"{len(declared)} secret(s) declared",
            message=(
                "Paste each value below. Stored encrypted via Vault transit. "
                "Never visible to admins or in logs (federal I-SECRETS-NEVER-LOGGED)."
            ),
            type="info",
        ),
    ]

    for spec in declared:
        name = spec.get("name", "")
        desc = spec.get("description", "")
        required = bool(spec.get("required", False))
        write_mode = spec.get("write_mode", "user")
        rotation_hint = spec.get("rotation_hint_days")

        st = statuses.get(name, {})
        is_set = bool(st.get("is_set"))
        last_read = st.get("last_accessed_at")

        # Header row with status badge
        head_children = [
            ui.Heading(text=name, level=3),
            ui.Badge("Set" if is_set else "Not set",
                     color="green" if is_set else "gray"),
        ]
        if required:
            head_children.append(ui.Badge("required", color="orange"))
        if write_mode == "extension":
            head_children.append(ui.Badge("ext-write only", color="blue"))

        # Description + meta
        meta_lines = []
        if desc:
            meta_lines.append(ui.Text(desc))
        if rotation_hint:
            meta_lines.append(ui.Text(
                f"Recommended rotation: every {rotation_hint} day(s).",
                color="muted",
            ))
        if last_read:
            meta_lines.append(ui.Text(
                f"Last read: {last_read}", color="muted",
            ))

        # Form: ALWAYS show input for user/both modes (auto-expanded — no
        # extra click needed). For extension-write-only, show informational
        # block instead since dev can't enter from here.
        card_children = [
            ui.Stack(direction="h", gap=1, children=head_children),
            *meta_lines,
        ]

        if write_mode == "extension":
            card_children.append(ui.Alert(
                title="Extension writes this value",
                message=(
                    "This secret has write_mode='extension' — the extension itself "
                    "writes the value (e.g. OAuth refresh tokens written after the "
                    "user authorizes via the provider). You cannot paste a value here."
                ),
                type="info",
            ))
            if is_set:
                card_children.append(ui.Button(
                    label="Clear (revoke)",
                    variant="danger",
                    size="sm",
                    on_click=ui.Call(
                        "delete_app_secret",
                        app_id=app_id, name=name,
                    ),
                ))
        else:
            # User-writable: render Form with inline password input
            card_children.append(ui.Form(
                action="save_app_secret",
                submit_label="Save" if not is_set else "Rotate",
                children=[
                    ui.Hidden(name="app_id", value=app_id),
                    ui.Hidden(name="name", value=name),
                    ui.Input(
                        name="value",
                        type="password",
                        placeholder="paste value…",
                        autocomplete="new-password",
                    ),
                ],
            ))
            if is_set:
                card_children.append(ui.Button(
                    label="Delete value",
                    variant="danger",
                    size="sm",
                    on_click=ui.Call(
                        "delete_app_secret",
                        app_id=app_id, name=name,
                    ),
                ))

        rows.append(ui.Card(
            title="",  # title already in head row
            children=card_children,
        ))

    return ui.Stack(children=rows, gap=2)
