"""Developer Portal — deploy a composed IR app (app.ir.json) without git.

Sibling of deploy_app (handlers_deploy.py): reached via the existing
POST /v1/extensions/developer/call (function="deploy_ir"). Reuses the kernel's
register_ir_app (validate + write + hot-index + fleet-wide imperal:catalog
signal) and the shared deploy-sync pipeline. No git, no new gateway route,
no second validator. PII gate is P2's scope (DeployReceipt carries no PII).
"""
import logging
import os
import re

from pydantic import BaseModel, Field
from imperal_sdk.chat import ActionResult

from app import chat, _gw_get, _user_id, EXTENSIONS_DIR
from models_app import DeployReceipt
from deploy_sync import _record_deploy, _sync_ir_manifest, _sync_tools_to_registry

log = logging.getLogger("developer")


class DeployIRParams(BaseModel):
    app_id: str = Field(..., description="App to deploy the IR to")
    ir_dict: dict = Field(..., description="The app.ir.json content (declarative IR envelope)")


@chat.function("deploy_ir", action_type="write",
               description="Deploy a composed declarative IR app (app.ir.json) — validate, register, and sync to the registry",
               data_model=DeployReceipt)
async def deploy_ir(ctx, params: DeployIRParams) -> ActionResult:
    uid = _user_id(ctx)
    app_id = params.app_id

    # Strict app_id allowlist BEFORE any use — prevents path traversal in
    # os.path.join(EXTENSIONS_DIR, app_id) (and register_ir_app's own write)
    # and path/query injection into the ownership-check URL below.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", app_id or ""):
        return ActionResult.error(
            "Invalid app_id (allowed: letters, digits, '_' and '-'; max 64 chars)."
        )

    # Ownership (mirror deploy_app): the app must exist and belong to the caller.
    try:
        await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as e:
        return ActionResult.error(f"App not found: {e}")

    # Validate + write + hot-index + fleet-wide catalog signal (kernel, in-process).
    from imperal_kernel.services.registration import register_ir_app
    result = await register_ir_app(app_id, params.ir_dict)
    if not result.get("ok"):
        issues = result.get("issues", [])
        msgs = "; ".join(
            i.get("message", str(i)) if isinstance(i, dict) else str(i) for i in issues
        )
        return ActionResult.error(f"Invalid IR — not deployed. {msgs}")

    # Registry sync (IR-ready) + deploy record. app.ir.json is now on disk.
    app_dir = os.path.join(EXTENSIONS_DIR, app_id)
    try:
        tools_synced = await _sync_tools_to_registry(app_id, app_dir, owner_id=uid)
    except Exception as e:
        log.warning("deploy_ir registry sync failed for %s: %s", app_id, e)
        tools_synced = 0

    manifest_synced = False
    try:
        manifest_synced = await _sync_ir_manifest(app_id, params.ir_dict)
    except Exception as e:
        log.warning("deploy_ir manifest sync failed for %s: %s", app_id, e)

    version = (params.ir_dict.get("app", {}) or {}).get("version", "") or "ir"
    try:
        await _record_deploy(uid, app_id, version, "success", "")
    except Exception as e:
        log.warning("deploy_ir record_deploy failed for %s: %s", app_id, e)

    summary = f"Deployed IR app {app_id} v{version} — {tools_synced} tools registered in catalog."
    if manifest_synced:
        summary += " Manifest synced to DB (tools classifiable)."
    return ActionResult.success(
        data={
            "app_id": app_id,
            "commit": version,
            "status": "deployed",
            "validation": "ok",
            "tools_synced": tools_synced,
            "panels_synced": False,
            "icon_synced": False,
            "manifest_synced": manifest_synced,
            "migrations_applied": None,
        },
        summary=summary,
        refresh_panels=["sidebar", "dashboard"],
    )
