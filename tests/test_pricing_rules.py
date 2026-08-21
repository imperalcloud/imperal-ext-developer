"""Pricing INPUT must never turn into a quiet lie.

Half one of the pricing suite: the pure rules in pricing_rules.py, plus the
two guarantees that decide whether a price can be expressed at all.

The defect these pin: a per-action price set through chat reported success
and stored nothing, because (a) the tool declared no parameter for prices,
(b) an empty price map still overwrote the stored config, and (c) anything
unparseable became a silent 0 -- i.e. "make it free".

Handler behaviour (write + read-back verification, bulk) lives in
test_pricing_handlers.py; the shared fake gateway in _pricing_fixtures.py.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handlers_pricing as hp         # noqa: E402
import pricing_rules as pr            # noqa: E402

from _pricing_fixtures import (        # noqa: E402,F401
    _Gateway,
    _wire,
    ctx,
)


# ─── 1. the caller can actually express a price ───────────────────────── #

def test_the_tool_declares_a_parameter_for_action_prices():
    """The original defect: prices had NO declared parameter.

    They arrived as undeclared `price_<tool>` extras that only the panel
    form produced, so a chat caller asked to price an action had no field
    to put the price in and could only ever send an empty config.
    """
    schema = hp.SavePricingParams.model_json_schema()
    assert "tool_prices" in schema["properties"], (
        "save_pricing must expose a declared per-action price parameter; "
        f"got {sorted(schema['properties'])}"
    )


def test_the_panel_forms_price_fields_still_work():
    """The form submits price_<tool> extras; that path must not regress."""
    prices = pr.collect_tool_prices(None, {"price_search": "50", "other": "x"})
    assert prices == {"search": 50}


def test_an_explicit_price_beats_a_stale_form_field():
    prices = pr.collect_tool_prices({"search": 70}, {"price_search": "50"})
    assert prices == {"search": 70}


# ─── 2. merge, never clobber ──────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_pricing_one_action_does_not_erase_the_others(ctx, monkeypatch):
    """The nastiest form of the bug: adding a price DELETED existing ones.

    An empty/partial tool_prices was sent as the whole pricing_config, and
    the gateway stores that column wholesale.
    """
    gw = _wire(monkeypatch, _Gateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", tool_prices={"fetch": 25}),
    )

    assert res.status == "success", res.error
    stored = gw.apps["search-tools"]["pricing_config"]["tool_prices"]
    assert stored == {"search": 10, "export": 99, "fetch": 25}, (
        f"unmentioned actions must keep their price, got {stored}"
    )


@pytest.mark.asyncio
async def test_a_zero_price_removes_that_action(ctx, monkeypatch):
    gw = _wire(monkeypatch, _Gateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", tool_prices={"export": 0}),
    )

    assert res.status == "success", res.error
    assert gw.apps["search-tools"]["pricing_config"]["tool_prices"] == {"search": 10}


@pytest.mark.asyncio
async def test_changing_only_the_model_keeps_the_prices(ctx, monkeypatch):
    gw = _wire(monkeypatch, _Gateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", pricing_model="per_action"),
    )

    assert res.status == "success", res.error
    assert gw.apps["search-tools"]["pricing_config"]["tool_prices"] == {
        "search": 10, "export": 99,
    }


# ─── 3. bad input is loud, never a silent zero ────────────────────────── #

@pytest.mark.parametrize("bad", ["abc", "-5", "1e9999", True, 12.5])
def test_unparseable_prices_are_refused(bad):
    with pytest.raises(pr.PricingError):
        pr.coerce_price(bad, field="price of 'search'")


@pytest.mark.asyncio
async def test_a_typo_does_not_quietly_make_an_action_free(ctx, monkeypatch):
    gw = _wire(monkeypatch, _Gateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", tool_prices={"search": "fifty"}),
    )

    assert res.status == "error"
    assert gw.puts == [], "nothing may be written when the input is nonsense"
    assert gw.apps["search-tools"]["pricing_config"]["tool_prices"]["search"] == 10


@pytest.mark.asyncio
async def test_pricing_an_action_the_app_does_not_have_is_refused(ctx, monkeypatch):
    """A price on a non-existent action can never be charged."""
    gw = _wire(monkeypatch, _Gateway())

    res = await hp.save_pricing(
        ctx, hp.SavePricingParams(app_id="search-tools", tool_prices={"serch": 50}),
    )

    assert res.status == "error"
    assert "serch" in res.error
    assert gw.puts == []


def test_an_undeployed_app_is_not_second_guessed():
    """Unverifiable is not the same as wrong: no manifest, no rejection."""
    assert pr.unknown_tools({"anything": 5}, []) == []


