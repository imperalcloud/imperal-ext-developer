"""Shared doubles for the pricing tests.

Split out so the pricing suite can live in two focused files (rules vs
handler behaviour) while sharing ONE fake gateway. Two copies of a fake
that models the gateway's active-app guard is exactly how the two halves
would drift into testing different systems.

Importable as `from _pricing_fixtures import ...` because conftest.py puts
this directory on sys.path (same mechanism as _skeleton_helper).

_LyingGateway is the centrepiece: it accepts every PUT with a cheerful 200
and stores nothing, which is precisely how the original defect looked from
the caller's side. Any pricing path that reports success against it is
lying.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handlers_bulk as hb            # noqa: E402
import handlers_pricing as hp         # noqa: E402


class _Ctx:
    class user:
        imperal_id = "imp_u_DEVELOPER1"
        id = "imp_u_DEVELOPER1"
        role = "developer"


@pytest.fixture
def ctx():
    return _Ctx()


class _Gateway:
    """A developer's apps, behaving like the real gateway's update_app."""

    def __init__(self, apps=None):
        self.apps = apps or {
            "search-tools": {
                "app_id": "search-tools", "display_name": "Search Tools",
                "status": "draft", "pricing_model": "per_action",
                "pricing_config": {"tool_prices": {"search": 10, "export": 99}},
            },
            "meta-social": {
                "app_id": "meta-social", "display_name": "Meta Social",
                "status": "suspended", "pricing_model": "free",
                "pricing_config": {},
            },
            "live-app": {
                "app_id": "live-app", "display_name": "Live App",
                "status": "active", "pricing_model": "free",
                "pricing_config": {},
            },
        }
        self.puts: list[tuple[str, dict]] = []

    async def get(self, path):
        if path.startswith("/v1/developer/apps?"):
            return list(self.apps.values())
        app_id = path.split("/v1/developer/apps/")[1].split("?")[0]
        if app_id not in self.apps:
            raise RuntimeError(f"404 {app_id}")
        return dict(self.apps[app_id])

    async def put(self, path, data):
        app_id = path.split("/v1/developer/apps/")[1]
        self.puts.append((app_id, data))
        app = self.apps[app_id]
        if app["status"] == "active":                 # the real gateway's guard
            raise ValueError("API error 400: Cannot edit pricing on active app")
        self._store(app, data)
        return dict(app)

    def _store(self, app, data):
        for key in ("pricing_model", "pricing_config", "revenue_split_dev"):
            if key in data:
                app[key] = data[key]


class _LyingGateway(_Gateway):
    """Accepts the write, stores nothing -- the original bug, reproduced."""

    def _store(self, app, data):
        return None


class _JsonStringGateway(_Gateway):
    """Returns pricing_config as a raw JSON string, as the DB column can."""

    async def get(self, path):
        out = await super().get(path)
        if isinstance(out, dict) and isinstance(out.get("pricing_config"), dict):
            out["pricing_config"] = json.dumps(out["pricing_config"])
        return out


def _wire(monkeypatch, gw, *, known=("search", "export", "fetch")):
    """Point every pricing seam at one fake gateway."""
    monkeypatch.setattr(hp, "_gw_get", gw.get)
    monkeypatch.setattr(hp, "_gw_put", gw.put)
    monkeypatch.setattr(hp, "_user_id", lambda ctx: "imp_u_DEVELOPER1")
    monkeypatch.setattr(hp, "_known_tools", lambda app_id: list(known))
    # Bulk pricing resolves names through _resolve_apps, which lives in (and
    # reads its gateway from) handlers_bulk -- so that is the module to patch,
    # even though the handler itself now lives in handlers_bulk_pricing.
    monkeypatch.setattr(hb, "_gw_get", gw.get)
    monkeypatch.setattr(hb, "_user_id", lambda ctx: "imp_u_DEVELOPER1")
    return gw
