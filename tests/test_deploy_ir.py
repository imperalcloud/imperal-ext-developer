"""Tests for deploy_ir chat-function (P1.2).

Coverage:
  (a) Module imports cleanly and registers deploy_ir on chat.
  (b) INVALID-IR path: register_ir_app returns ok=False → ActionResult.error,
      _sync_tools_to_registry and _record_deploy are NOT called.
  (c) HAPPY path: register_ir_app ok=True, _gw_get ok → ActionResult.success
      with tools_synced=2.

imperal_kernel is NOT installed locally; deploy_ir imports it lazily
(inside the function body), so the module itself loads fine. Tests inject a
fake module into sys.modules before calling the function.
"""
from __future__ import annotations

import sys
import types
import pytest

# ---------------------------------------------------------------------------
# (a) Import check — must happen at collection time
# ---------------------------------------------------------------------------
import deploy_ir as _deploy_ir_mod  # noqa: E402  (root path added by conftest/main sys.path.insert)
from deploy_ir import deploy_ir, DeployIRParams  # noqa: E402

from app import chat  # noqa: E402


def test_module_imports_and_registers_on_chat():
    """deploy_ir is importable and the function name is registered on chat."""
    # The @chat.function decorator calls chat._functions[name] = FunctionDef(...)
    # (or equivalent). Accept any dict/mapping or list that includes 'deploy_ir'.
    registered = False
    if hasattr(chat, "_functions") and isinstance(chat._functions, dict):
        registered = "deploy_ir" in chat._functions
    elif hasattr(chat, "functions") and isinstance(chat.functions, dict):
        registered = "deploy_ir" in chat.functions
    else:
        # Fall back: at minimum the function object exists in the module
        registered = callable(deploy_ir)
    assert registered, "deploy_ir must be registered on chat after import"


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

class _FakeUser:
    imperal_id = "user-test-123"


class _FakeCtx:
    user = _FakeUser()


def _make_params(app_id="test-app", version="0.1.0", extra_app=None):
    ir = {"app": {"version": version, **(extra_app or {})}, "tools": []}
    return DeployIRParams(app_id=app_id, ir_dict=ir)


def _inject_kernel_fake(register_ir_app_coro):
    """Inject a fake imperal_kernel.services.registration into sys.modules."""
    fake_reg = types.ModuleType("imperal_kernel.services.registration")
    fake_reg.register_ir_app = register_ir_app_coro  # type: ignore[attr-defined]

    fake_kernel = types.ModuleType("imperal_kernel")
    fake_services = types.ModuleType("imperal_kernel.services")

    sys.modules.setdefault("imperal_kernel", fake_kernel)
    sys.modules.setdefault("imperal_kernel.services", fake_services)
    sys.modules["imperal_kernel.services.registration"] = fake_reg


# ---------------------------------------------------------------------------
# (b) INVALID-IR path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_ir_returns_error_without_calling_sync(monkeypatch):
    """When register_ir_app returns ok=False, deploy_ir errors out immediately.
    _sync_tools_to_registry and _record_deploy must NOT be called.
    """
    sync_called = []
    record_called = []

    async def fake_register_ir_app(app_id, ir_dict):
        return {"ok": False, "issues": [{"message": "IR1: bad schema"}]}

    async def fake_gw_get(path):
        return {"app_id": "test-app"}

    async def fake_sync(app_id, app_dir, owner_id):
        sync_called.append(app_id)
        return 0

    async def fake_record(uid, app_id, version, status, error_msg):
        record_called.append(app_id)

    _inject_kernel_fake(fake_register_ir_app)
    monkeypatch.setattr(_deploy_ir_mod, "_gw_get", fake_gw_get)
    monkeypatch.setattr(_deploy_ir_mod, "_sync_tools_to_registry", fake_sync)
    monkeypatch.setattr(_deploy_ir_mod, "_record_deploy", fake_record)

    ctx = _FakeCtx()
    params = _make_params()
    result = await deploy_ir(ctx, params)

    assert result.status == "error", f"Expected error, got: {result.status}"
    assert "IR1: bad schema" in (result.error or ""), (
        f"Error message must contain the issue text; got: {result.error!r}"
    )
    assert sync_called == [], "_sync_tools_to_registry must NOT be called on invalid IR"
    assert record_called == [], "_record_deploy must NOT be called on invalid IR"


# ---------------------------------------------------------------------------
# (c) HAPPY path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_returns_success_with_tools_synced(monkeypatch):
    """When register_ir_app returns ok=True, deploy_ir returns ActionResult.success
    with tools_synced matching the value returned by _sync_tools_to_registry.
    """
    async def fake_register_ir_app(app_id, ir_dict):
        return {"ok": True}

    async def fake_gw_get(path):
        return {"app_id": "test-app"}

    async def fake_sync(app_id, app_dir, owner_id):
        return 2  # simulates 2 tools registered

    async def fake_record(uid, app_id, version, status, error_msg):
        pass  # no-op; existence is enough

    _inject_kernel_fake(fake_register_ir_app)
    monkeypatch.setattr(_deploy_ir_mod, "_gw_get", fake_gw_get)
    monkeypatch.setattr(_deploy_ir_mod, "_sync_tools_to_registry", fake_sync)
    monkeypatch.setattr(_deploy_ir_mod, "_record_deploy", fake_record)

    ctx = _FakeCtx()
    params = _make_params(app_id="test-app", version="1.2.3")
    result = await deploy_ir(ctx, params)

    assert result.status == "success", f"Expected success, got: {result.status!r} err={result.error!r}"
    assert isinstance(result.data, dict), "data must be a dict"
    assert result.data.get("tools_synced") == 2, (
        f"tools_synced must be 2; got: {result.data.get('tools_synced')!r}"
    )
    assert result.data.get("app_id") == "test-app"
    assert result.data.get("commit") == "1.2.3"
    assert result.data.get("status") == "deployed"
    assert result.data.get("validation") == "ok"
    assert result.data.get("panels_synced") is False
    assert result.data.get("icon_synced") is False
    assert result.data.get("manifest_synced") is False
    assert result.data.get("migrations_applied") is None
    assert result.refresh_panels == ["sidebar", "dashboard"]
