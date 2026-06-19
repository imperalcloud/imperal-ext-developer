"""Secrets tab for the Developer Portal App Details dashboard.

Renders one inline form per declared secret in the app's manifest. The
developer (= the app's owner) pastes the value directly here; submit
PUTs to auth-gw /v1/secrets/{app_id}/{secret_name} via service-token +
X-Acting-User. Plaintext never touches our DB column except briefly in
Vault transit between encrypt/decrypt — federal I-SECRETS-NEVER-LOGGED
contract intact.

If the app declares no secrets, shows an empty state with the canonical
@ext.secret(...) code example so the developer knows how to declare one.

Uses only SDK ui.* primitives:
- ui.Card(title=, subtitle=, content=UINode)  — single content node, not list
- ui.Text(content=, variant="body"/"caption"/"heading"/"code")
- ui.Input(param_name=, placeholder=, value=, type=)  — type∈{text,password,email,number,url} (v4.2.6+); prefer ui.Password for credentials
- ui.Form(children=, action=, submit_label=, defaults=)  — defaults carries
  hidden values (app_id, name) since there's no ui.Hidden primitive
- ui.Link(label=, on_click=ui.Open(url=...))  — Open action opens new tab
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from imperal_sdk import ui

from app import _gw_get


DOC_URL = "https://docs.imperal.io/en/sdk/decorator-secret-reference/"

_AUTH_GW = os.getenv("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
_SVC = os.getenv("IMPERAL_SERVICE_TOKEN", "")


async def _gw_get_as_user(path: str, uid: str) -> Any:
    """GET against auth-gw with X-Service-Token + X-Acting-User for the
    given user. The shared httpx client in app.py only carries the service
    token — secrets list endpoint needs both headers for proper scoping
    (I-SECRETS-USER-SCOPED), otherwise the list comes back empty for the
    fallback empty-string user."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{_AUTH_GW.rstrip('/')}{path}",
            headers={"X-Service-Token": _SVC, "X-Acting-User": uid},
        )
    r.raise_for_status()
    return r.json()


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
                    "Add a declaration to your app.py and redeploy to manage "
                    "credentials here."
                ),
                type="info",
            ),
            ui.Card(
                title="How to declare a secret",
                content=ui.Stack(children=[
                    ui.Code(content=(
                        'ext.secret(\n'
                        '    name="openai_api_key",\n'
                        '    description="Your OpenAI API key (sk-proj-...).",\n'
                        '    required=True,\n'
                        '    write_mode="user",       # user pastes via Panel\n'
                        '    max_bytes=200,\n'
                        ')(lambda: None)'
                    ), language="python"),
                    ui.Text(content=(
                        "After git push + Deploy, the field appears in this Secrets "
                        "tab ready for value entry. Plaintext is encrypted in Vault "
                        "transit; never logged, never visible to admins."
                    )),
                    ui.Link(
                        label="@ext.secret reference →",
                        on_click=ui.Open(url=DOC_URL),
                    ),
                ]),
            ),
        ], gap=2)

    # Fetch current is_set state for each declared secret in one shot.
    # MUST use _gw_get_as_user(..., uid) — auth-gw scopes the list by user_id
    # taken from X-Acting-User header; the default _gw_get only sends the
    # service token and would land at empty-user scope returning no rows.
    statuses: dict[str, dict] = {}
    try:
        live = await _gw_get_as_user(f"/v1/secrets/{app_id}", uid)
        if isinstance(live, list):
            for item in live:
                if isinstance(item, dict) and item.get("name"):
                    statuses[item["name"]] = item
    except Exception:
        statuses = {}

    rows: list[Any] = [
        ui.Alert(
            title=f"{len(declared)} secret(s) declared",
            message=(
                "Paste each value below — stored encrypted via Vault transit. "
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

        # Build the per-secret card body as a single Stack content node.
        body_children: list[Any] = []

        # Status line — name + badges
        head_badges = [
            ui.Badge("Set" if is_set else "Not set",
                     color="green" if is_set else "gray"),
        ]
        if required:
            head_badges.append(ui.Badge("required", color="orange"))
        if write_mode == "extension":
            head_badges.append(ui.Badge("ext-write only", color="blue"))
        body_children.append(ui.Stack(direction="h", gap=1, children=head_badges))

        if desc:
            body_children.append(ui.Text(content=desc))
        if rotation_hint:
            body_children.append(ui.Text(
                content=f"Recommended rotation: every {rotation_hint} day(s).",
                variant="caption",
            ))
        if last_read:
            body_children.append(ui.Text(
                content=f"Last read: {last_read}", variant="caption",
            ))

        if write_mode == "extension":
            # Extension writes this itself; show info + Clear button if set.
            body_children.append(ui.Alert(
                title="Extension writes this value",
                message=(
                    "This secret has write_mode='extension' — the extension itself "
                    "writes the value (e.g. OAuth refresh tokens written after the "
                    "user authorizes via the provider). You can't paste a value here."
                ),
                type="info",
            ))
            if is_set:
                body_children.append(ui.Button(
                    label="Clear (revoke)",
                    variant="danger",
                    size="sm",
                    on_click=ui.Call(
                        "delete_app_secret",
                        app_id=app_id, name=name,
                        confirm="Delete this secret value? This cannot be undone.",
                    ),
                ))
        else:
            # User-writable: render Form with inline value input. The Form
            # `defaults` dict carries app_id + name as hidden values that
            # ride into save_app_secret action alongside the user-entered
            # value (no ui.Hidden primitive exists in SDK 4.2.x).
            body_children.append(ui.Form(
                action="save_app_secret",
                submit_label="Save" if not is_set else "Rotate",
                defaults={"app_id": app_id, "name": name},
                children=[
                    ui.Password(
                        param_name="value",
                        placeholder="paste value…",
                    ),
                ],
            ))
            if is_set:
                body_children.append(ui.Button(
                    label="Delete value",
                    variant="danger",
                    size="sm",
                    on_click=ui.Call(
                        "delete_app_secret",
                        app_id=app_id, name=name,
                        confirm="Delete this secret value? This cannot be undone.",
                    ),
                ))

        rows.append(ui.Card(
            title=name,
            subtitle=desc if not desc or len(desc) < 80 else desc[:77] + "…",
            content=ui.Stack(children=body_children, gap=1),
        ))

    rows.append(ui.Link(
        label="📖 @ext.secret reference (docs.imperal.io) →",
        on_click=ui.Open(url=DOC_URL),
    ))

    return ui.Stack(children=rows, gap=2)
