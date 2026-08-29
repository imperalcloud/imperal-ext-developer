"""Developer · bulk PRICING: price many apps in one call, each one verified.

Split from handlers_bulk.py to keep both files under the 300-line ceiling the
Portal's own validator enforces (a rule this extension should obey before it
enforces it on other developers).

Kept apart from the lifecycle bulk ops for a second reason: pricing is the
one bulk action that changes what USERS are charged, so it carries the
read-back verification from handlers_pricing.apply_pricing. Deploy/suspend
/submit only move an app's own state.

The work itself is delegated -- this module resolves names and reports, it
does NOT build a pricing_config. That belongs to pricing_rules, via
apply_pricing, so the single-app and bulk paths cannot drift apart.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import chat
from pricing_input import AppIds, JsonObject
from handlers_bulk import (
    _MAX_APPS,
    BulkAppReceipt,
    _receipt,
    _resolve_apps,
    _run_each,
)

log = logging.getLogger("developer.handlers_bulk_pricing")


class BulkPricingParams(BaseModel):
    """Price SEVERAL of your own apps in one call."""

    app_ids: AppIds = Field(
        description=(
            "The apps to price — exact app_ids, display names, or partials of "
            "either; each is resolved against YOUR apps. Pass EVERY app the "
            "user named in ONE call; do not loop."
        ),
        min_length=1,
        max_length=_MAX_APPS,
    )
    pricing_model: str = Field(
        default="",
        description=(
            "free, per_action, or subscription. Unset keeps each app's current "
            "model, so prices can be changed without touching the model."
        ),
    )
    tool_prices: Optional[JsonObject] = Field(
        default=None,
        description=(
            "Per-action prices in tokens, {action_name: price}, applied to "
            "EVERY named app. An action not listed keeps its current price; 0 "
            "makes it free. An app lacking a named action is reported as a "
            "failure for that app only — the others still change. Example: "
            "{'search': 50, 'export': 200}."
        ),
    )
    monthly_price: Optional[str] = Field(
        default=None, description="Monthly token price (subscription model)")
    revenue_split_dev: Optional[int] = Field(
        default=None, description="Developer share % (unset = keep each app's current)")


@chat.function(
    "bulk_set_pricing",
    action_type="write",
    event="developer.bulk_set_pricing",
    effects=["update:app_pricing"],
    data_model=BulkAppReceipt,
    description=(
        "Set per-action prices (or the pricing model / monthly price) on "
        "SEVERAL of your apps at once, verifying each write. Use for 'charge "
        "50 tokens for search in all my apps', 'make both apps free', 'price "
        "these three the same'. Apps must be paused/draft."
    ),
)
async def fn_bulk_set_pricing(ctx, params: BulkPricingParams) -> ActionResult:
    """Price many apps, each verified against a fresh read.

    Runs the REAL single-app pricing path once per app. That path merges
    rather than clobbers, rejects prices for actions an app does not have,
    and re-reads the app to confirm the value stored -- so a bulk price
    change is that same guarantee N times, not a faster way to be wrong in
    bulk. An app that fails (still live, unknown action, mismatch) is
    reported as that app's failure; the rest still change.
    """
    targets, failures = await _resolve_apps(ctx, params.app_ids)

    # Reuse the verified write path; a second implementation here is exactly
    # how bulk would drift back into "reported success, wrote nothing".
    from handlers_pricing import apply_pricing

    async def _price_one(c, app_id: str):
        return await apply_pricing(
            c,
            app_id,
            pricing_model=params.pricing_model,
            tool_prices=params.tool_prices,
            monthly_price=params.monthly_price,
            revenue_split_dev=params.revenue_split_dev,
        )

    ok, more = await _run_each(ctx, targets, _price_one, lambda a: a)
    return _receipt("Priced", ok, failures + more)
