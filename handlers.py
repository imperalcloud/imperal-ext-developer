"""Developer Portal — app lifecycle handlers (CRUD, pricing, delete)."""
from typing import Optional
from pydantic import BaseModel, Field
from imperal_sdk.chat import ActionResult
from app import chat, _gw_get, _gw_post, _gw_put, _gw_delete, _user_id
from models_sdl import (
    DeveloperRegistration,
    AppRecord,
    SuspendReceipt,
    DeleteAppReceipt,
)
import logging

log = logging.getLogger("developer")


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------
class RegisterParams(BaseModel):
    tier: str = Field(default="explorer", description="explorer, indie, studio, or partner")
    # Optional at the action layer so an empty submit reaches the handler's
    # friendly guard instead of a raw kernel param-validation error. The gateway
    # remains the source of truth — it rejects a missing/invalid handle.
    nickname: str = Field(default="", description="Unique username/handle (3-30 chars, lowercase, a-z 0-9 _ -)")


class CreateAppParams(BaseModel):
    app_id: str = Field(..., description="Unique slug (lowercase, hyphens)")
    display_name: str = Field(..., description="Human-readable name")
    description: str = Field(default="", description="Short description")
    category: str = Field(default="general", description="App category")
    git_url: str = Field(..., description="HTTPS Git repo URL")
    pricing_model: str = Field(default="free", description="free, per_action, or subscription")
    monthly_price: Optional[str] = Field(default="0", description="Monthly price for subscription")


class SuspendParams(BaseModel):
    app_id: str = Field(..., description="App to pause/suspend")


class DeleteAppParams(BaseModel):
    app_id: str = Field(..., description="App ID to permanently delete")
    confirm_name: str = Field(..., description="Type the app_id to confirm deletion")


class UpdateAppInfoParams(BaseModel):
    app_id: str = Field(..., description="App to update")
    display_name: Optional[str] = Field(default=None, description="New display name")
    description: Optional[str] = Field(default=None, description="New description")
    category: Optional[str] = Field(default=None, description="New category")
    git_url: Optional[str] = Field(default=None, description="New Git URL (HTTPS)")


class UpdatePricingParams(BaseModel):
    app_id: str = Field(..., description="App to update pricing")
    pricing_model: str = Field(..., description="free, per_action, or subscription")
    pricing_config: dict = Field(default_factory=dict, description="Price config")
    revenue_split_dev: int = Field(default=80, description="Developer share %")


class SavePricingParams(BaseModel):
    app_id: str = Field(..., description="App to update pricing")
    pricing_model: str = Field(default="free", description="free, per_action, or subscription")
    monthly_price: Optional[str] = Field(default="0", description="Monthly price for subscription")

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
@chat.function("register_developer", action_type="write",
               description="Register as a developer (Explorer tier is free)",
               data_model=DeveloperRegistration)
async def register_developer(ctx, params: RegisterParams) -> ActionResult:
    uid = _user_id(ctx)
    # Friendly guard: nickname is required by the gateway (DeveloperRegisterRequest
    # rejects a missing/empty handle with 422/400). Surface a clear ask instead of
    # a raw validation dump when the form is submitted without one.
    nickname = (params.nickname or "").strip()
    if not nickname:
        return ActionResult.error(
            "Please choose a developer handle (3-30 chars: lowercase a-z, 0-9, _ or -)."
        )
    try:
        result = await _gw_post("/v1/developer/register", {
            "user_id": uid, "tier": params.tier, "nickname": nickname,
        })
        # Gateway returns {tier, nickname, registered_at} with no SDL id/title,
        # but DeveloperRegistration marks them required — project from nickname.
        if isinstance(result, dict):
            result.setdefault("id", nickname)
            result.setdefault("title", f"@{nickname}")
        return ActionResult.success(
            data=result,
            summary=f"Registered as {params.tier} developer (@{nickname})!",
        refresh_panels=["sidebar", "dashboard"],
        )
    except Exception as e:
        return ActionResult.error(f"Registration failed: {e}")


@chat.function("create_app", action_type="write",
               description="Create a new extension app (requires Git URL)",
               data_model=AppRecord)
async def create_app(ctx, params: CreateAppParams) -> ActionResult:
    uid = _user_id(ctx)
    try:
        pricing_config = {}
        monthly = 0
        if params.monthly_price:
            try:
                monthly = int(params.monthly_price)
            except (ValueError, TypeError):
                pass
        if monthly > 0:
            pricing_config["monthly_price"] = monthly
        result = await _gw_post("/v1/developer/apps", {
            "user_id": uid,
            "app_id": params.app_id,
            "display_name": params.display_name,
            "description": params.description,
            "category": params.category,
            "git_url": params.git_url,
            "pricing_model": params.pricing_model,
            "pricing_config": pricing_config or None,
        })
        return ActionResult.success(
            data=result,
            summary=f"App '{params.app_id}' created ({params.pricing_model}).",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to create app: {e}")


@chat.function("suspend_app", action_type="write",
               description="Pause/suspend your app (allows editing pricing)",
               data_model=SuspendReceipt)
async def suspend_app(ctx, params: SuspendParams) -> ActionResult:
    uid = _user_id(ctx)
    try:
        result = await _gw_post(f"/v1/developer/apps/{params.app_id}/suspend", {"user_id": uid})
        return ActionResult.success(
            data=result,
            summary=f"App '{params.app_id}' paused. You can now edit pricing and resubmit.",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to pause app: {e}")


@chat.function("delete_app", action_type="destructive",
               description="Permanently delete an app. Must be suspended first. Requires typing the exact app_id to confirm. THIS CANNOT BE UNDONE.",
               data_model=DeleteAppReceipt)
async def delete_app(ctx, params: DeleteAppParams) -> ActionResult:
    uid = _user_id(ctx)
    try:
        result = await _gw_delete(
            f"/v1/developer/apps/{params.app_id}",
            {"confirm_name": params.confirm_name, "user_id": uid},
        )
    except Exception as e:
        return ActionResult.error(f"Delete failed: {e}")

    # task #75: rm -rf /opt/extensions/{app_id} so a subsequent New-App
    # with the same app_id starts clean (was: dir persisted with dirty
    # state from prior deploy, breaking re-create).
    import os as _os, shutil as _shutil, re as _re
    app_id = params.app_id or ""
    # Defensive: app_id is regex-validated at registration, but double-
    # check before filesystem action.
    if _re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]", app_id):
        ext_dir = f"/opt/extensions/{app_id}"
        if _os.path.isdir(ext_dir):
            try:
                _shutil.rmtree(ext_dir, ignore_errors=False)
            except Exception as rm_err:
                # Auth GW delete already succeeded — surface partial success.
                return ActionResult.success(
                    data=result,
                    summary=(
                        f"App '{app_id}' deleted in DB but extension "
                        f"directory cleanup failed: {rm_err}. Manual "
                        f"cleanup required: rm -rf {ext_dir}"
                    ),
                refresh_panels=["sidebar", "dashboard"],
                )
    return ActionResult.success(
        data=result,
        summary=f"App '{app_id}' has been permanently deleted (DB + /opt/extensions/ dir).",
    )


@chat.function("update_app_info", action_type="write",
               description="Update app info (name, description, git URL) — works on active apps",
               data_model=AppRecord)
async def update_app_info(ctx, params: UpdateAppInfoParams) -> ActionResult:
    uid = _user_id(ctx)
    data = {}
    if params.display_name is not None:
        data["display_name"] = params.display_name
    if params.description is not None:
        data["description"] = params.description
    if params.category is not None:
        data["category"] = params.category
    if params.git_url is not None:
        data["git_url"] = params.git_url
    if not data:
        return ActionResult.error("No fields to update")
    data["user_id"] = uid
    try:
        result = await _gw_put(f"/v1/developer/apps/{params.app_id}", data)
        changed = ", ".join(k for k in data if k != "user_id")
        return ActionResult.success(
            data=result,
            summary=f"Updated {changed} for '{params.app_id}'.",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to update: {e}")


@chat.function("update_pricing", action_type="write",
               description="Update app pricing model (requires paused app)",
               data_model=AppRecord)
async def update_pricing(ctx, params: UpdatePricingParams) -> ActionResult:
    uid = _user_id(ctx)
    try:
        result = await _gw_put(f"/v1/developer/apps/{params.app_id}", {
            "user_id": uid,
            "pricing_model": params.pricing_model,
            "pricing_config": params.pricing_config,
            "revenue_split_dev": params.revenue_split_dev,
        })
        return ActionResult.success(data=result, summary=f"Pricing updated for '{params.app_id}'.")
    except Exception as e:
        return ActionResult.error(f"Failed to update pricing: {e}")


@chat.function("save_pricing", action_type="write",
               description="Save pricing model and per-tool prices from the pricing form",
               data_model=AppRecord)
async def save_pricing(ctx, params: SavePricingParams) -> ActionResult:
    uid = _user_id(ctx)

    # Extract per-tool prices from extra fields (price_toolname=value)
    tool_prices = {}
    extra = params.model_extra or {}
    for key, val in extra.items():
        if key.startswith("price_"):
            tool_name = key[6:]
            try:
                price = int(val) if val and str(val).isdigit() else 0
            except (ValueError, TypeError):
                price = 0
            if price > 0:
                tool_prices[tool_name] = price

    # Build pricing_config
    pricing_config = {}
    if tool_prices:
        pricing_config["tool_prices"] = tool_prices
    monthly = 0
    if params.monthly_price:
        try:
            monthly = int(params.monthly_price)
        except (ValueError, TypeError):
            pass
    if monthly > 0:
        pricing_config["monthly_price"] = monthly

    try:
        result = await _gw_put(f"/v1/developer/apps/{params.app_id}", {
            "user_id": uid,
            "pricing_model": params.pricing_model,
            "pricing_config": pricing_config,
        })
        summary_parts = [f"Model: {params.pricing_model}"]
        if tool_prices:
            summary_parts.append(f"{len(tool_prices)} tool prices set")
        if monthly > 0:
            summary_parts.append(f"monthly: {monthly} tok")
        return ActionResult.success(
            data=result,
            summary=f"Pricing saved for '{params.app_id}': {', '.join(summary_parts)}",
        refresh_panels=["sidebar", "dashboard"],
        )
    except Exception as e:
        return ActionResult.error(f"Failed to save pricing: {e}")
