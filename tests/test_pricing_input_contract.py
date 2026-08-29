"""Regression coverage for pricing inputs crossing function-call transport."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handlers_bulk_pricing as hbp  # noqa: E402
import handlers_pricing as hp  # noqa: E402


def test_save_pricing_decodes_json_object_from_transport():
    params = hp.SavePricingParams(
        app_id="content-strategy-app",
        tool_prices='{"get_internal_linking_status": 2, "enable_internal_linking": 5}',
    )
    assert params.tool_prices == {
        "get_internal_linking_status": 2,
        "enable_internal_linking": 5,
    }


def test_update_pricing_decodes_json_object_from_transport():
    params = hp.UpdatePricingParams(
        app_id="content-strategy-app",
        pricing_model="per_action",
        pricing_config='{"tool_prices": {"create_site_profile": 5}}',
    )
    assert params.pricing_config == {"tool_prices": {"create_site_profile": 5}}


def test_bulk_pricing_decodes_json_array_and_object_from_transport():
    params = hbp.BulkPricingParams(
        app_ids='["content-strategy-app"]',
        tool_prices='{"enable_internal_linking": 5}',
    )
    assert params.app_ids == ["content-strategy-app"]
    assert params.tool_prices == {"enable_internal_linking": 5}


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (hp.SavePricingParams, {"app_id": "app", "tool_prices": "not json"}),
        (hp.UpdatePricingParams, {
            "app_id": "app", "pricing_model": "free", "pricing_config": "[]",
        }),
        (hbp.BulkPricingParams, {"app_ids": "{}"}),
    ],
)
def test_pricing_transport_rejects_invalid_json_container(factory, kwargs):
    with pytest.raises(ValidationError):
        factory(**kwargs)


def test_known_tools_prefers_live_callable_surface(monkeypatch):
    class Loader:
        def load(self, app_id):
            assert app_id == "content-strategy-app"
            return object()

    monkeypatch.setitem(sys.modules, "imperal_kernel.core.loader", type("M", (), {
        "ExtensionLoader": lambda _: Loader(),
    }))
    monkeypatch.setitem(sys.modules, "imperal_sdk.catalog", type("M", (), {
        "callable_functions": lambda ext: [
            {"name": "get_internal_linking_status"},
            {"name": "enable_internal_linking"},
            {"name": "__panel__project"},
        ],
    }))

    assert hp._known_tools("content-strategy-app") == [
        "get_internal_linking_status", "enable_internal_linking"
    ]
