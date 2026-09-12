"""Developer Portal — direct pricing inspection tool (read-back verification).

Split out of handlers_pricing.py to respect the 300-line ceiling (rule 6).
Provides a dedicated read-back tool for app pricing verification.
"""
from __future__ import annotations

import logging
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult
from app import chat, _gw_get, _user_id
from models_sdl import AppPricingRecord

log = logging.getLogger("developer.pricing_read")


class GetPricingParams(BaseModel):
    """Parameters for get_pricing tool."""

    app_id: str = Field(..., description="App id to inspect pricing for")


@chat.function(
    "get_pricing",
    action_type="read",
    event="developer.get_pricing",
    data_model=AppPricingRecord,
    description="Inspect an app's current verified pricing model, per-action prices, and revenue split.",
)
async def get_pricing(ctx, params: GetPricingParams) -> ActionResult:
    """Direct read-back tool for developer app pricing."""
    uid = _user_id(ctx)
    app_id = params.app_id.strip()
    try:
        res = await _gw_get(f"/v1/developer/apps/{app_id}/pricing?user_id={uid}")
    except Exception as exc:  # noqa: BLE001
        return ActionResult.error(f"Couldn't load pricing for '{app_id}': {exc}")

    prices = res.get("tool_prices") or {}
    summary_bits = [f"model: {res.get('pricing_model', 'free')}"]
    if prices:
        summary_bits.append(f"{len(prices)} tool(s) priced")
    if res.get("monthly_price"):
        summary_bits.append(f"monthly: {res['monthly_price']}")
    summary_bits.append(f"status: {res.get('status', 'unknown')}")

    return ActionResult.success(
        data=res,
        summary=f"Pricing for '{app_id}': {', '.join(summary_bits)}",
    )
