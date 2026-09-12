"""Tests for get_pricing tool (read-back verification)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from handlers_pricing_read import GetPricingParams, get_pricing


@pytest.mark.asyncio
async def test_get_pricing_success():
    ctx = AsyncMock()
    params = GetPricingParams(app_id="test-app")

    fake_res = {
        "app_id": "test-app",
        "pricing_model": "per_action",
        "pricing_config": {"tool_prices": {"action1": 10}},
        "revenue_split_dev": 70,
        "status": "draft",
        "monthly_price": None,
        "tool_prices": {"action1": 10},
    }

    with patch("handlers_pricing_read._user_id", return_value="user1"), \
         patch("handlers_pricing_read._gw_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = fake_res
        res = await get_pricing(ctx, params)

        assert res.status == "success"
        assert res.data["app_id"] == "test-app"
        assert res.data["pricing_model"] == "per_action"
        assert "1 tool(s) priced" in res.summary


@pytest.mark.asyncio
async def test_get_pricing_error():
    ctx = AsyncMock()
    params = GetPricingParams(app_id="missing-app")

    with patch("handlers_pricing_read._user_id", return_value="user1"), \
         patch("handlers_pricing_read._gw_get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = RuntimeError("404 Not Found")
        res = await get_pricing(ctx, params)

        assert res.status == "error"
        assert "Couldn't load pricing" in res.error
