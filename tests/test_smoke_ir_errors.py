"""imperal-mcp field test 2026-11-13: a failed smoke run reached the agent as the bare word 'data' (a KeyError)."""
import sys
import types

import pytest


@pytest.mark.asyncio
async def test_a_failed_smoke_run_names_the_kind_of_failure(monkeypatch):
    async def boom(ir, fn, args):
        raise KeyError("data")
    mod = types.ModuleType("imperal_kernel.compose.tools")
    mod.smoke_run_impl = boom
    for name in ("imperal_kernel", "imperal_kernel.compose"):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "imperal_kernel.compose.tools", mod)
    import smoke_ir as S

    class _Ctx:
        class user:
            imperal_id = "imp_u_1"
    res = await S.smoke_ir(_Ctx(), S.SmokeIRParams(ir_dict={}, function="f"))
    assert "KeyError" in str(res.error) and "'data'" in str(res.error)
