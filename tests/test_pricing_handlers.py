"""Pricing OUTPUT must be verified against the row, not the HTTP status.

Half two of the pricing suite: what the handlers actually do -- the write +
read-back verification, and the same guarantee applied N times by bulk.

The centrepiece is _LyingGateway (see _pricing_fixtures): it accepts every
PUT with a cheerful 200 and stores nothing, reproducing the original defect
exactly. A pricing path that reports success against it is lying, and these
tests fail.

Input validation and merge semantics live in test_pricing_rules.py.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handlers_bulk_pricing as hbp   # noqa: E402
import handlers_pricing as hp         # noqa: E402

from _pricing_fixtures import (        # noqa: E402,F401
    _CorruptingGateway,
    _Gateway,
    _JsonStringGateway,
    _LyingGateway,
    _wire,
    ctx,
)


# ─── 4. success means the row agrees ──────────────────────────────────── #

@pytest.mark.asyncio
async def test_a_gateway_that_stores_nothing_is_reported_as_failure(ctx, monkeypatch):
    """THE regression test for the reported bug.

    The API answers 200 and writes nothing. Anything that calls that a
    success is repeating the original lie.
    """
    _wire(monkeypatch, _LyingGateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", tool_prices={"fetch": 25}),
    )

    assert res.status == "error", (
        "a write that did not land must never be reported as saved"
    )
    assert "did NOT save" in res.error


@pytest.mark.asyncio
async def test_wrong_price_persisted_is_reported_as_failure(ctx, monkeypatch):
    """A gateway that turns create_site_profile=5 into 15 cannot fake success."""
    _wire(monkeypatch, _CorruptingGateway(), known=("search", "export", "fetch", "create_site_profile"))

    res = await hp.save_pricing(
        ctx,
        hp.SavePricingParams(
            app_id="search-tools", tool_prices={"create_site_profile": 5},
        ),
    )

    assert res.status == "error"
    assert "stored as 15, expected 5" in res.error


@pytest.mark.asyncio
async def test_verification_survives_a_json_string_column(ctx, monkeypatch):
    """pricing_config can come back as raw JSON text; that is not a mismatch."""
    _wire(monkeypatch, _JsonStringGateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", tool_prices={"fetch": 25}),
    )

    assert res.status == "success", res.error


@pytest.mark.asyncio
async def test_an_unverifiable_write_is_not_called_success(ctx, monkeypatch):
    gw = _Gateway()
    _wire(monkeypatch, gw)
    calls = {"n": 0}

    async def _get_then_die(path):
        calls["n"] += 1
        if calls["n"] > 1:                      # first read ok, read-back fails
            raise RuntimeError("gateway timeout")
        return await gw.get(path)

    monkeypatch.setattr(hp, "_gw_get", _get_then_die)

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", tool_prices={"fetch": 25}),
    )

    assert res.status == "error"
    assert "could NOT be verified" in res.error


@pytest.mark.asyncio
async def test_a_live_app_is_refused_before_any_write(ctx, monkeypatch):
    gw = _wire(monkeypatch, _Gateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="live-app", tool_prices={"search": 50}),
    )

    assert res.status == "error"
    assert "pause" in res.error.lower()
    assert gw.puts == [], "a live app must be refused without attempting a write"


@pytest.mark.asyncio
async def test_explicit_update_replaces_config_instead_of_merging(ctx, monkeypatch):
    """update_pricing({}) must clear old prices; save_pricing is the merge API."""
    gw = _wire(monkeypatch, _Gateway())

    res = await hp.update_pricing(
        ctx,
        hp.UpdatePricingParams(
            app_id="search-tools", pricing_model="free", pricing_config={},
        ),
    )

    assert res.status == "success", res.error
    assert gw.apps["search-tools"]["pricing_model"] == "free"
    assert gw.apps["search-tools"]["pricing_config"] == {}


# ─── 5. bulk: the same guarantee, N times ─────────────────────────────── #

@pytest.mark.asyncio
async def test_bulk_prices_every_named_app(ctx, monkeypatch):
    gw = _wire(monkeypatch, _Gateway())

    res = await hbp.fn_bulk_set_pricing(
        ctx,
        hbp.BulkPricingParams(
            app_ids=["search-tools", "meta-social"], tool_prices={"search": 50},
        ),
    )

    assert res.status == "success", res.error
    assert gw.apps["search-tools"]["pricing_config"]["tool_prices"]["search"] == 50
    assert gw.apps["meta-social"]["pricing_config"]["tool_prices"]["search"] == 50


@pytest.mark.asyncio
async def test_bulk_merges_per_app_instead_of_flattening_them(ctx, monkeypatch):
    """Each app keeps its own untouched prices -- bulk is not a bulldozer."""
    gw = _wire(monkeypatch, _Gateway())

    await hbp.fn_bulk_set_pricing(
        ctx,
        hbp.BulkPricingParams(
            app_ids=["search-tools", "meta-social"], tool_prices={"search": 50},
        ),
    )

    assert gw.apps["search-tools"]["pricing_config"]["tool_prices"] == {
        "search": 50, "export": 99,
    }
    assert gw.apps["meta-social"]["pricing_config"]["tool_prices"] == {"search": 50}


@pytest.mark.asyncio
async def test_bulk_reports_the_live_app_and_still_prices_the_rest(ctx, monkeypatch):
    gw = _wire(monkeypatch, _Gateway())

    res = await hbp.fn_bulk_set_pricing(
        ctx,
        hbp.BulkPricingParams(
            app_ids=["search-tools", "live-app"], tool_prices={"search": 50},
        ),
    )

    assert res.status == "success", "partial success is still success"
    assert res.data["succeeded"] == ["search-tools"]
    assert res.data["failure_count"] == 1
    assert gw.apps["search-tools"]["pricing_config"]["tool_prices"]["search"] == 50


@pytest.mark.asyncio
async def test_bulk_never_reports_success_for_writes_that_vanished(ctx, monkeypatch):
    """Bulk must inherit verification, not bypass it."""
    _wire(monkeypatch, _LyingGateway())

    res = await hbp.fn_bulk_set_pricing(
        ctx,
        hbp.BulkPricingParams(
            app_ids=["search-tools", "meta-social"], tool_prices={"search": 50},
        ),
    )

    assert res.status == "error", "no app stored anything; that is not success"


@pytest.mark.asyncio
async def test_bulk_resolves_partial_names_and_dedupes(ctx, monkeypatch):
    gw = _wire(monkeypatch, _Gateway())

    res = await hbp.fn_bulk_set_pricing(
        ctx,
        hbp.BulkPricingParams(
            app_ids=["search", "search-tools"], tool_prices={"search": 50},
        ),
    )

    assert res.status == "success", res.error
    priced = [app_id for app_id, _ in gw.puts]
    assert priced == ["search-tools"], f"one app named twice is priced once, got {priced}"
