"""Developer Portal — skeleton timer handler (split from handlers.py to keep it
under the 300-line god-file ceiling, rule 6). Writes a per-app ttl_override; the
cadence is a global, developer-owned value (ttl_override over the manifest ttl
default; effective = COALESCE(ttl_override, ttl), served by the Registry)."""
from pydantic import BaseModel, Field, ConfigDict
from imperal_sdk.chat import ActionResult
from app import chat, _gw_get, _registry_put, _user_id
from skeleton_ttl import build_override_sections
from models_app import SkeletonConfigReceipt


class SaveSkeletonTtlParams(BaseModel):
    model_config = ConfigDict(extra="allow")  # per-section fields: ttl_<section_name>
    app_id: str = Field(..., description="App whose skeleton timers to update")


@chat.function("save_skeleton_ttl", action_type="write",
               description="Save per-section skeleton refresh intervals from the Skeleton form",
               data_model=SkeletonConfigReceipt)
async def save_skeleton_ttl(ctx, params: SaveSkeletonTtlParams) -> ActionResult:
    uid = _user_id(ctx)
    sections = build_override_sections(params.model_extra or {})
    if not sections:
        return ActionResult.error("No skeleton sections to update")
    # Owner gate: the developer endpoint only returns the app if uid owns it.
    try:
        await _gw_get(f"/v1/developer/apps/{params.app_id}?user_id={uid}")
    except Exception:
        return ActionResult.error("App not found or not yours")
    try:
        await _registry_put(f"/v1/apps/{params.app_id}/settings",
                            {"skeleton": {"sections": sections}})
    except Exception as e:
        return ActionResult.error(f"Failed to save skeleton timers: {e}")
    n = len(sections)
    return ActionResult.success(
        data={"app_id": params.app_id, "updated": True, "sections": sections},
        summary=f"Updated {n} skeleton timer{'s' if n != 1 else ''} for '{params.app_id}'",
        refresh_panels=["dashboard"],
    )
