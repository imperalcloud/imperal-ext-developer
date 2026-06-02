"""Developer Portal — SDL typed return models (100% SDL).

Canonical re-export hub. Every read/write/destructive @chat.function in this
extension declares its ``ActionResult.data`` shape as a real ``sdl.Entity`` (or
``sdl.EntityList[T]`` for list returns), so the platform reads typed SDL
entities directly from the manifest ``return_schema`` (Federal Typed Return
Contract V23 — ``data_model`` required for ``action_type="read"``; extended
here to every data tool per the SDL doctrine: ТОЛЬКО SDL, zero legacy
``{key:[dict]}`` wrappers).

The concrete records live in domain modules (each under the 300-line god-file
ceiling, rule 6) and are re-exported here so existing
``from models_sdl import X`` imports keep working unchanged:

  - models_earnings.py — earnings reads + payout list/receipt
  - models_app.py      — developer registration, app lifecycle, deploy
  - models_secrets.py  — app-secret save/delete receipts

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
runtime dict keys the handler returns (handlers return ``data=result`` where
``result`` is the raw auth-gateway JSON, verified against
api-contracts/imperal/auth-gateway.json). The ``data_model`` kwarg is
schema-declaration only (recorded on ``FunctionDef._return_model`` for manifest
``return_schema`` emission); it does NOT validate/coerce the runtime data dict,
so these models are non-breaking — unknown keys pass through untouched.
"""
from __future__ import annotations

from models_earnings import (
    EarningsSummary,
    AppEarnings,
    PayoutRecord,
    PayoutHistory,
    PayoutRequestReceipt,
)
from models_app import (
    DeveloperRegistration,
    AppRecord,
    SuspendReceipt,
    DeleteAppReceipt,
    SubmitReceipt,
    DeployReceipt,
)
from models_secrets import (
    SecretSaveReceipt,
    SecretDeleteReceipt,
)

__all__ = [
    "EarningsSummary",
    "AppEarnings",
    "PayoutRecord",
    "PayoutHistory",
    "PayoutRequestReceipt",
    "DeveloperRegistration",
    "AppRecord",
    "SuspendReceipt",
    "DeleteAppReceipt",
    "SubmitReceipt",
    "DeployReceipt",
    "SecretSaveReceipt",
    "SecretDeleteReceipt",
]
