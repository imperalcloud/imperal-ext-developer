"""Developer Portal — pricing handlers: set prices and PROVE they landed.

Split out of handlers.py (which was already at its size ceiling) so the two
callers that price an app -- the panel form and chat, single and bulk --
share one write path. See pricing_rules.py for the four defects this
replaces; the short version is that "I set the price" was a claim about an
HTTP status code, not about the row.

THE CONTRACT HERE: a pricing call succeeds only if a FRESH READ of the app
shows the prices. Every write is followed by a read-back and a field-by-field
comparison. If the row disagrees with what we asked for, this returns an
ERROR describing the difference -- never a success summary.

That read costs one extra round trip per pricing change. Pricing changes are
rare and a wrong one is invisible until a developer's revenue is wrong, so
the trade is not close.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import chat, _gw_get, _gw_put, _user_id, EXTENSIONS_DIR
from models_sdl import AppRecord
from pricing_catalog import known_tools as _known_tools
from pricing_input import JsonObject, PricingConfig
from pricing_rules import (
    PricingError,
    build_pricing_config,
    collect_tool_prices,
    config_mismatches,
    describe_prices,
    normalise_model,
    unknown_tools,
)

log = logging.getLogger("developer.pricing")


# ─── Params ───────────────────────────────────────────────────────────── #

class SavePricingParams(BaseModel):
    """Set an app's pricing model and what each of its actions costs."""

    model_config = {"extra": "allow"}       # panel form sends price_<tool> fields

    app_id: str = Field(..., description="App whose pricing to set")
    pricing_model: str = Field(
        default="",
        description=(
            "free, per_action, or subscription. Leave unset to keep the app's "
            "current model while changing prices."
        ),
    )
    # THE field whose absence was the original bug: without it there was no
    # way for a caller to express a price at all.
    tool_prices: Optional[JsonObject] = Field(
        default=None,
        description=(
            "Per-action prices in tokens, keyed by the action/function name — "
            "e.g. {'search_web': 50, 'fetch_page': 20}. Actions you do not "
            "mention keep their current price; pass 0 to make one free again."
        ),
    )
    monthly_price: Optional[str] = Field(
        default=None,
        description="Monthly token price for the subscription model (0 removes it)",
    )
    revenue_split_dev: Optional[int] = Field(
        default=None,
        description="Developer share % (unset = keep current)",
    )


# ─── Shared write+verify path ─────────────────────────────────────────── #

async def apply_pricing(
    ctx,
    app_id: str,
    *,
    pricing_model: str = "",
    tool_prices: Optional[dict] = None,
    extras: Optional[dict] = None,
    monthly_price=None,
    revenue_split_dev: Optional[int] = None,
) -> ActionResult:
    """Set pricing on ONE app, then prove it by reading the app back.

    Used by the single-app handlers AND by bulk, so a bulk price change is
    the same operation N times -- including the verification. A bulk path
    that skipped the read-back would reintroduce the original bug wholesale.
    """
    uid = _user_id(ctx)

    # 1. Current state: needed to merge (not clobber) and to fail early with a
    #    better message than the gateway's on an active app.
    try:
        app = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as exc:                                   # noqa: BLE001
        return ActionResult.error(f"Couldn't load '{app_id}': {exc}")

    status = (app.get("status") or "draft").lower()
    if status == "active":
        return ActionResult.error(
            f"'{app_id}' is live, and pricing can't change under users mid-flight. "
            f"Pause it first (suspend_app), set the price, then submit it again."
        )

    current_config = app.get("pricing_config") or {}
    if isinstance(current_config, str):                        # defensive: raw JSON
        import json
        try:
            current_config = json.loads(current_config)
        except Exception:                                      # noqa: BLE001
            current_config = {}

    # 2. Build the desired state from validated input.
    try:
        model = normalise_model(pricing_model, app.get("pricing_model"))
        incoming = collect_tool_prices(tool_prices, extras)
        desired = build_pricing_config(current_config, incoming, monthly_price)
    except PricingError as exc:
        return ActionResult.error(str(exc))

    stray = unknown_tools(incoming, _known_tools(app_id))
    if stray:
        return ActionResult.error(
            f"'{app_id}' has no action named {', '.join(repr(s) for s in stray)}. "
            f"A price on an action that doesn't exist could never be charged. "
            f"Check the name, or deploy the app first if it's new."
        )

    if model == "per_action" and not desired.get("tool_prices"):
        return ActionResult.error(
            f"'{app_id}' would be per-action with no action priced — every call "
            f"would be free. Give at least one action a price, or use the free model."
        )

    payload = {
        "user_id": uid,
        "pricing_model": model,
        "pricing_config": desired,
    }
    if revenue_split_dev is not None:
        payload["revenue_split_dev"] = revenue_split_dev

    # 3. Write.
    try:
        await _gw_put(f"/v1/developer/apps/{app_id}", payload)
    except Exception as exc:                                   # noqa: BLE001
        return ActionResult.error(f"Failed to save pricing for '{app_id}': {exc}")

    # 4. Read back. THE point of this module: a 200 is about the request, the
    #    row is about the truth.
    try:
        fresh = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as exc:                                   # noqa: BLE001
        return ActionResult.error(
            f"Pricing for '{app_id}' was submitted but could NOT be verified "
            f"({exc}). Re-run to confirm before trusting it."
        )

    stored = fresh.get("pricing_config") or {}
    if isinstance(stored, str):
        import json
        try:
            stored = json.loads(stored)
        except Exception:                                      # noqa: BLE001
            stored = {}

    problems = config_mismatches(desired, stored)
    stored_model = (fresh.get("pricing_model") or "").lower()
    if stored_model != model:
        # Kept out of the f-string on purpose: nesting the SAME quote inside an
        # f-string only parses on Python 3.12+ (PEP 701), and the platform
        # workers run 3.11 -- a local 3.14 venv compiles it happily and the
        # deploy then fails on syntax. Plain and version-neutral beats clever.
        shown = stored_model or "?"
        problems.insert(0, f"model stored as '{shown}', expected '{model}'")

    if problems:
        return ActionResult.error(
            f"Pricing for '{app_id}' did NOT save correctly: "
            + "; ".join(problems)
            + ". Nothing was reported as failed by the API, so this is a real "
              "mismatch worth investigating rather than a retry."
        )

    final_prices = stored.get("tool_prices") or {}
    bits = [f"model: {model}"]
    if final_prices:
        bits.append(describe_prices({k: int(v) for k, v in final_prices.items()}))
    if stored.get("monthly_price"):
        bits.append(f"monthly {stored['monthly_price']} tok")
    if revenue_split_dev is not None:
        bits.append(f"dev split {revenue_split_dev}%")

    return ActionResult.success(
        data=fresh,
        summary=f"Pricing verified for '{app_id}' — {', '.join(bits)}.",
        refresh_panels=["sidebar", "dashboard"],
    )


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function(
    "save_pricing",
    action_type="write",
    event="developer.save_pricing",
    effects=["update:app_pricing"],
    data_model=AppRecord,
    description=(
        "Set what an app's actions cost (per-action token prices), its pricing "
        "model, or its monthly price — then verify the change actually stored. "
        "Actions not mentioned keep their price; 0 makes one free. Requires a "
        "paused/draft app. For SEVERAL apps use bulk_set_pricing."
    ),
)
async def save_pricing(ctx, params: SavePricingParams) -> ActionResult:
    """Set pricing on one app and confirm it against a fresh read."""
    return await apply_pricing(
        ctx,
        params.app_id,
        pricing_model=params.pricing_model,
        tool_prices=params.tool_prices,
        extras=params.model_extra or {},
        monthly_price=params.monthly_price,
        revenue_split_dev=params.revenue_split_dev,
    )


class UpdatePricingParams(BaseModel):
    """Lower-level pricing update (explicit pricing_config)."""

    app_id: str = Field(..., description="App to update pricing")
    pricing_model: str = Field(..., description="free, per_action, or subscription")
    pricing_config: PricingConfig = Field(default_factory=dict, description="Price config")
    revenue_split_dev: Optional[int] = Field(
        default=None, description="Developer share % (unset = keep current)"
    )


@chat.function(
    "update_pricing",
    action_type="write",
    event="developer.update_pricing",
    effects=["update:app_pricing"],
    data_model=AppRecord,
    description="Update an app's pricing model with an explicit pricing_config (requires paused app)",
)
async def update_pricing(ctx, params: UpdatePricingParams) -> ActionResult:
    """Explicit-config variant, verified on the same path as save_pricing."""
    config = params.pricing_config or {}
    return await apply_pricing(
        ctx,
        params.app_id,
        pricing_model=params.pricing_model,
        tool_prices=config.get("tool_prices") or {},
        monthly_price=config.get("monthly_price"),
        revenue_split_dev=params.revenue_split_dev,
    )
