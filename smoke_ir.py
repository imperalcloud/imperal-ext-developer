"""Developer Portal — smoke-run one function of a composed IR app in an ISOLATED
store (never real tenant data). Sibling of deploy_ir: reached via the existing
POST /v1/extensions/developer/call (function="smoke_ir"). Reuses the kernel's
smoke_run_impl (MockContext) — no new gateway route, no second runtime."""
import logging

from pydantic import BaseModel, Field
from imperal_sdk.chat import ActionResult

from app import chat, _user_id
from models_app import SmokeReceipt

log = logging.getLogger("developer")


class SmokeIRParams(BaseModel):
    ir_dict: dict = Field(..., description="The app.ir.json content to smoke-run")
    function: str = Field(..., description="Which function to run")
    args: dict = Field(default_factory=dict, description="Arguments for the function")


@chat.function("smoke_ir", action_type="read",
               description="Smoke-run one function of a composed IR app in an isolated store and report the result",
               data_model=SmokeReceipt)
async def smoke_ir(ctx, params: SmokeIRParams) -> ActionResult:
    """Smoke-run one function of a composed IR app in an isolated store and report the result"""
    _ = _user_id(ctx)  # auth/identity already enforced by the gateway
    from imperal_kernel.compose.tools import smoke_run_impl
    try:
        out = await smoke_run_impl(params.ir_dict, params.function, params.args or {})
    except Exception as e:  # never leak a raw stack to the agent
        return ActionResult.error(f"Smoke run failed: {e}")
    return ActionResult.success(
        data={"ok": out.get("ok", False), "result": out.get("result", {}), "trace": out.get("trace", {})},
        summary=("Smoke run OK" if out.get("ok") else "Smoke run reported a problem"),
    )
