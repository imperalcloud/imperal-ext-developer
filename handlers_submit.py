"""Developer Portal — submit-for-review handler.

Extracted from handlers_deploy.py to keep that module under the workspace's
300-line god-file ceiling (rule 6).
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from imperal_sdk.chat import ActionResult

from app import chat, _gw_post, _user_id


class SubmitParams(BaseModel):
    app_id: str = Field(..., description="App to submit for review")


@chat.function("submit_for_review", action_type="write",
               description="Submit app for admin review")
async def submit_for_review(ctx, params: SubmitParams) -> ActionResult:
    uid = _user_id(ctx)
    try:
        result = await _gw_post(f"/v1/developer/apps/{params.app_id}/submit", {"user_id": uid})
        if result.get("status") == "failed":
            checks = result.get("checks", [])
            failed = [c["check"] for c in checks if not c.get("ok") and not c.get("passed")]
            return ActionResult.error(f"Submission failed — fix: {', '.join(failed)}")
        return ActionResult.success(
            data=result,
            summary=f"App '{params.app_id}' submitted for review.",
            refresh_panels=["sidebar", "dashboard"],
        )
    except Exception as e:
        return ActionResult.error(f"Failed to submit: {e}")
