"""Webhooks tab for the Developer Portal App Details dashboard.

Lists every @ext.webhook handler declared in the app's manifest with the
canonical public URL the developer must register in OAuth provider
consoles (Spotify Dashboard → Redirect URIs, GitHub App → Webhook URL,
Google OAuth → Authorized redirect URIs).

URLs are built from the kernel-authoritative app_id (folder/manifest
name) — *not* whatever the developer typed into ``Extension("X", ...)``
in app.py. So if the Python value drifts from the manifest, the URL
shown here is still correct, and the developer can spot the drift by
comparing what's shown to their app.py declaration.

Surface:
- ui.Card per webhook with method badge + canonical URL in a Code block
- Empty state when manifest has zero @ext.webhook declarations
- Link to docs.imperal.io decorator-webhook-reference for help
"""
from __future__ import annotations

import json
import os
from typing import Any

from imperal_sdk import ui

from app import _gw_get


DOC_URL = "https://docs.imperal.io/en/sdk/decorator-webhook-reference/"

_PUBLIC_HOST = os.getenv("IMPERAL_PUBLIC_HOST", "panel.imperal.io")


def _build_webhook_url(app_id: str, path: str) -> str:
    """Canonical public URL — mirrors ctx.webhook_url() shape in SDK."""
    clean = (path or "").lstrip("/")
    return f"https://{_PUBLIC_HOST}/v1/ext/{app_id}/webhook/{clean}"


async def build_webhooks(uid: str, app_id: str, **_kwargs: Any) -> Any:
    """Render the Webhooks tab content for a single app."""
    if not app_id:
        return ui.Alert(
            title="Select an app",
            message="Pick an app from the sidebar to view its webhook URLs.",
            type="info",
        )

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
            arr = mf.get("webhooks") if isinstance(mf, dict) else None
            if isinstance(arr, list):
                declared = [
                    w for w in arr
                    if isinstance(w, dict) and w.get("path")
                ]
        except Exception:
            declared = []
    elif isinstance(manifest_raw, dict):
        arr = manifest_raw.get("webhooks")
        if isinstance(arr, list):
            declared = [
                w for w in arr if isinstance(w, dict) and w.get("path")
            ]

    # Empty state — guide the developer
    if not declared:
        return ui.Stack(children=[
            ui.Alert(
                title="No webhooks declared in this app's manifest",
                message=(
                    "This extension does not declare any @ext.webhook(...) "
                    "handlers. Add a declaration to your app.py and redeploy "
                    "to see your callback URLs here. Useful for OAuth flows "
                    "(Spotify, GitHub, Google) and server-to-server events "
                    "(Stripe, SendGrid)."
                ),
                type="info",
            ),
            ui.Card(
                title="How to declare a webhook",
                content=ui.Stack(children=[
                    ui.Code(content=(
                        '@ext.webhook("/callback", method="GET")\n'
                        'async def oauth_callback(ctx, headers, body, query_params):\n'
                        '    code = query_params.get("code")\n'
                        '    # ...exchange code for refresh_token...\n'
                        '    await ctx.secrets.set("refresh_token", token)\n'
                        '    return {"status": "ok"}'
                    ), language="python"),
                    ui.Text(content=(
                        "Methods: GET (OAuth redirect callbacks) or POST "
                        "(server-to-server hooks). The path you pass to "
                        "@ext.webhook becomes part of the public URL: "
                        f"https://{_PUBLIC_HOST}/v1/ext/{app_id}/webhook/<path>."
                    )),
                    ui.Link(
                        label="@ext.webhook reference →",
                        on_click=ui.Open(url=DOC_URL),
                    ),
                ]),
            ),
        ], gap=2)

    # Render one card per declared webhook
    rows: list[Any] = [
        ui.Alert(
            title=f"{len(declared)} webhook URL(s) for `{app_id}`",
            message=(
                "Register these URLs exactly in the OAuth provider's "
                "developer console (Spotify Dashboard → Redirect URIs, etc.) "
                "before users connect. The URL uses your manifest app_id "
                f"(`{app_id}`) — not whatever you typed into Extension(...)."
            ),
            type="info",
        ),
    ]

    for spec in declared:
        path = spec.get("path", "")
        method = (spec.get("method") or "POST").upper()
        secret_header = spec.get("secret_header") or ""

        url = _build_webhook_url(app_id, path)

        body_children: list[Any] = [
            ui.Stack(direction="h", gap=1, children=[
                ui.Badge(method, color="blue" if method == "POST" else "green"),
                ui.Badge(f"path: {path}", color="gray"),
            ]),
            ui.Code(content=url, language="text"),
        ]

        if method == "GET":
            body_children.append(ui.Text(
                content=(
                    "OAuth redirect callback. Provider 302-redirects the "
                    "user-agent here with `?code=...&state=...` in the "
                    "query string. Your handler exchanges the code for a "
                    "token and stores it via `ctx.secrets.set(...)` "
                    "(write_mode='extension')."
                ),
                variant="caption",
            ))
        else:
            if secret_header:
                body_children.append(ui.Text(
                    content=(
                        f"Server-to-server hook. Provider sends HMAC "
                        f"signature in header `{secret_header}` — verify "
                        f"with `hmac.compare_digest()` in your handler."
                    ),
                    variant="caption",
                ))
            else:
                body_children.append(ui.Text(
                    content=(
                        "Server-to-server hook. No HMAC header declared — "
                        "consider adding `secret_header=` to "
                        "@ext.webhook(...) and verifying signatures in "
                        "your handler."
                    ),
                    variant="caption",
                ))

        rows.append(ui.Card(
            title=path,
            subtitle=f"{method} · {app_id}",
            content=ui.Stack(children=body_children, gap=1),
        ))

    rows.append(ui.Link(
        label="📖 @ext.webhook reference (docs.imperal.io) →",
        on_click=ui.Open(url=DOC_URL),
    ))

    return ui.Stack(children=rows, gap=2)
