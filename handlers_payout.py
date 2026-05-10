"""Developer Portal — chat function handlers (earnings & payouts)."""
from typing import Optional
from pydantic import BaseModel
from imperal_sdk.chat import ActionResult
from app import chat, _gw_get, _gw_post, _user_id


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------
class EmptyParams(BaseModel):
    pass


class AppIdParams(BaseModel):
    app_id: str


class PayoutRequestParams(BaseModel):
    amount: int                       # tokens to payout
    payout_method: Optional[str] = "stripe"
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
@chat.function("request_payout", action_type="write", description="Request a payout of your available earnings")
async def request_payout(ctx, params: PayoutRequestParams) -> ActionResult:
    uid = _user_id(ctx)
    payload: dict = {
        "user_id": uid,
        "amount": params.amount,
        "payout_method": params.payout_method,
    }
    if params.notes:
        payload["notes"] = params.notes
    result = await _gw_post("/v1/developer/payouts/request", payload)
    return ActionResult.success(
        data=result,
        summary=f"Payout of {params.amount:,} tokens requested via {params.payout_method}.",
    refresh_panels=["sidebar", "dashboard"],
    )


@chat.function("get_earnings", action_type="read", description="View total earnings across all your apps")
async def get_earnings(ctx, params: EmptyParams) -> ActionResult:
    uid = _user_id(ctx)
    result = await _gw_get(f"/v1/developer/earnings?user_id={uid}")
    total = result.get("total_earned", 0)
    available = result.get("available", 0)
    return ActionResult.success(
        data=result,
        summary=f"Total earned: {total:,} tokens. Available for payout: {available:,} tokens.",
    )


@chat.function("get_earnings_by_app", action_type="read", description="View earnings for a specific app")
async def get_earnings_by_app(ctx, params: AppIdParams) -> ActionResult:
    uid = _user_id(ctx)
    result = await _gw_get(f"/v1/developer/earnings/{params.app_id}?user_id={uid}")
    total = result.get("total_earned", 0)
    return ActionResult.success(
        data=result,
        summary=f"App '{params.app_id}' earned {total:,} tokens total.",
    )


@chat.function("get_payout_history", action_type="read", description="View your payout request history")
async def get_payout_history(ctx, params: EmptyParams) -> ActionResult:
    uid = _user_id(ctx)
    result = await _gw_get(f"/v1/developer/payouts?user_id={uid}")
    payouts = result if isinstance(result, list) else result.get("payouts", [])
    return ActionResult.success(
        data=result,
        summary=f"Found {len(payouts)} payout request(s).",
    )
