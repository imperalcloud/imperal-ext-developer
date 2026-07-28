"""Form-submit action handlers for the Secrets tab in App Details dashboard.

`save_app_secret` — proxies PUT /v1/secrets/{app_id}/{name} via service token.
`delete_app_secret` — proxies DELETE /v1/secrets/{app_id}/{name}.

Both run as the authenticated developer (ctx.user.imperal_id is the X-Acting-User
header; the developer can only manage secrets they OWN under their own user
account — they're not bypassing federal user-scope at the auth-gw layer).
"""
from __future__ import annotations

import os
import httpx
from pydantic import BaseModel, Field
from imperal_sdk import ActionResult

from app import chat, _user_id
from models_sdl import SecretSaveReceipt, SecretDeleteReceipt


GW = os.getenv("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
SVC = os.getenv("IMPERAL_SERVICE_TOKEN", "")


def _headers(acting_user: str, *, json_body: bool = False) -> dict:
    h = {
        "X-Service-Token": SVC,
        "X-Acting-User": acting_user,
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


class SaveSecretParams(BaseModel):
    app_id: str = Field(..., description="The extension to save the secret for.")
    name: str = Field(..., description="The declared secret name.")
    value: str = Field(..., description="The plaintext value to encrypt.")


class DeleteSecretParams(BaseModel):
    app_id: str = Field(..., description="The extension whose secret to delete.")
    name: str = Field(..., description="The declared secret name.")


@chat.function(
    "save_app_secret",
    action_type="write",
    event="developer.save_app_secret",
    effects=["create:secret"],
    description=(
        "Save the value of a declared secret for one of your extensions. "
        "PUTs to auth-gw /v1/secrets/{app_id}/{name}; plaintext is encrypted "
        "by Vault transit before storage."
    ),
    data_model=SecretSaveReceipt,
)
async def save_app_secret(ctx, params: SaveSecretParams) -> ActionResult:
    """Save the value of a declared secret for one of your extensions. PUTs to auth-gw /v1/secrets/{app_id}/{name}; plaintext is encrypted by Vault transit before storage."""
    uid = _user_id(ctx)
    if not (params.app_id and params.name and params.value):
        return ActionResult.error("app_id, name, and value are all required.")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.put(
                f"{GW}/v1/secrets/{params.app_id}/{params.name}",
                headers=_headers(uid, json_body=True),
                json={"value": params.value},
            )
    except Exception as e:
        return ActionResult.error(f"auth-gw unreachable: {type(e).__name__}")
    if r.status_code == 200:
        return ActionResult.success(
            data={"ok": True, "app_id": params.app_id, "name": params.name},
            summary=f"Saved '{params.name}' for '{params.app_id}'.",
            refresh_panels=["dashboard"],
        )
    if r.status_code == 503:
        return ActionResult.error("Vault transit endpoint unavailable. Try again shortly.")
    try:
        detail = r.json().get("detail", {})
        code = detail.get("error_code", f"HTTP {r.status_code}") if isinstance(detail, dict) else str(detail)
    except Exception:
        code = f"HTTP {r.status_code}"
    return ActionResult.error(f"Save failed: {code}")


@chat.function(
    "delete_app_secret",
    action_type="destructive",
    event="developer.delete_app_secret",
    effects=["delete:secret"],
    description="Delete the value of a declared secret for one of your extensions.",
    data_model=SecretDeleteReceipt,
)
async def delete_app_secret(ctx, params: DeleteSecretParams) -> ActionResult:
    """Delete the value of a declared secret for one of your extensions."""
    uid = _user_id(ctx)
    if not (params.app_id and params.name):
        return ActionResult.error("app_id and name are required.")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.delete(
                f"{GW}/v1/secrets/{params.app_id}/{params.name}",
                headers=_headers(uid),
            )
    except Exception as e:
        return ActionResult.error(f"auth-gw unreachable: {type(e).__name__}")
    if r.status_code == 200:
        body = {}
        try:
            body = r.json()
        except Exception:
            pass
        return ActionResult.success(
            data={"ok": True, "was_set": bool(body.get("was_set"))},
            summary=f"Deleted '{params.name}' for '{params.app_id}'.",
            refresh_panels=["dashboard"],
        )
    try:
        detail = r.json().get("detail", {})
        code = detail.get("error_code", f"HTTP {r.status_code}") if isinstance(detail, dict) else str(detail)
    except Exception:
        code = f"HTTP {r.status_code}"
    return ActionResult.error(f"Delete failed: {code}")
