"""Shared helper for skeleton-sync tests.

Lazily mocks `app` + `validation` modules so `deploy_sync` (where the helper
function now lives, post-split from handlers_deploy.py) can be imported
under pytest without the extension runtime present.
"""
from __future__ import annotations

import os
import sys
import types

# Make deploy_sync.py importable (it lives alongside tests/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _noop(*a, **k):  # pragma: no cover — never actually invoked
    return {}


async def _noop_validate(*a, **k):  # pragma: no cover
    return {"ok": True, "checks": [], "passed": 0, "total": 0}


def _install_mocks_once():
    if "app" not in sys.modules:
        mock_app = types.ModuleType("app")
        mock_app.chat = type("C", (), {"function": lambda *a, **k: lambda f: f})()
        mock_app._gw_get = _noop
        mock_app._gw_post = _noop
        mock_app._gw_put = _noop
        mock_app._registry_post = _noop
        mock_app._registry_put = _noop
        mock_app._user_id = _noop
        mock_app.EXTENSIONS_DIR = "/opt/extensions"
        sys.modules["app"] = mock_app

    if "validation" not in sys.modules:
        mock_val = types.ModuleType("validation")
        mock_val.validate_extension_full = _noop_validate
        sys.modules["validation"] = mock_val


def get_derive():
    """Return the _derive_skeleton_sections_from_ext function."""
    _install_mocks_once()
    import deploy_sync  # type: ignore
    return deploy_sync._derive_skeleton_sections_from_ext


derive = get_derive()
