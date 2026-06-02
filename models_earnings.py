"""Developer Portal — SDL records for the earnings & payouts domain.

Split from ``models_sdl.py`` to keep each module under the workspace's
300-line god-file ceiling (rule 6). Re-exported from ``models_sdl`` so existing
imports keep working.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
runtime dict keys the handler returns (the handlers return ``data=result``
where ``result`` is the raw auth-gateway JSON, verified against
api-contracts/imperal/auth-gateway.json), NOT a synthetic projection.

Token amounts are platform tokens, not a fiat currency, so they carry custom
``developer.*`` roles via ``sdl.field`` rather than the reserved ``money.*``
facet fields (whose names would not match the handler-visible field names).
"""
from __future__ import annotations

from typing import Any, Optional

from imperal_sdk import sdl
from pydantic import model_validator


# ---------------------------------------------------------------------------
# Earnings (reads)
# ---------------------------------------------------------------------------
class EarningsSummary(sdl.Entity):
    """Aggregate earnings across all of a developer's apps (kind='earnings').

    Shape mirrors ``GET /v1/developer/earnings`` (EarningsResponse) as returned
    verbatim by ``get_earnings`` (``data=result``): total_earnings,
    total_platform_share, pending_payout, paid_out.
    """

    total_earnings: Optional[int] = sdl.field(
        default=None,
        role="developer.total_earned",
        description="Total tokens earned across all apps (lifetime).",
    )
    total_platform_share: Optional[int] = sdl.field(
        default=None,
        role="developer.platform_share",
        description="Total tokens taken as platform share (lifetime).",
    )
    pending_payout: Optional[int] = sdl.field(
        default=None,
        role="developer.available_earnings",
        description="Tokens available for payout right now.",
    )
    paid_out: Optional[int] = sdl.field(
        default=None,
        role="developer.paid_out",
        description="Tokens already paid out (lifetime).",
    )

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "earnings")
            data.setdefault("title", "Earnings")
            data.setdefault("kind", "earnings")
        return data


class AppEarnings(sdl.Entity):
    """Earnings scoped to a single app (kind='appearnings').

    Shape mirrors ``GET /v1/developer/earnings/{app_id}`` (EarningsByAppResponse)
    as returned verbatim by ``get_earnings_by_app`` (``data=result``): app_id,
    total_earnings, action_count, by_period.
    """

    app_id: Optional[str] = None
    total_earnings: Optional[int] = sdl.field(
        default=None,
        role="developer.total_earned",
        description="Total tokens earned by this app (lifetime).",
    )
    action_count: Optional[int] = sdl.field(
        default=None,
        role="developer.action_count",
        description="Total billable actions for this app (lifetime).",
    )
    by_period: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "app"
            data.setdefault("title", data.get("app_id") or "App earnings")
            data.setdefault("kind", "appearnings")
        return data


# ---------------------------------------------------------------------------
# Payouts (read list + write receipt)
# ---------------------------------------------------------------------------
class PayoutRecord(sdl.Entity):
    """One payout request (kind='payout').

    Mirrors PayoutResponse (``GET /v1/developer/payouts`` items): id,
    developer_id, amount_tokens, amount_usd, status, method, admin_note,
    requested_at, processed_at.
    """

    developer_id: Optional[str] = None
    amount_tokens: Optional[int] = sdl.field(
        default=None,
        role="developer.payout_amount",
        description="Payout amount in platform tokens.",
    )
    amount_usd: Optional[str] = None
    method: Optional[str] = None
    admin_note: Optional[str] = None
    requested_at: Optional[str] = None
    processed_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            pid = data.get("id")
            data["id"] = str(pid) if pid not in (None, "") else "payout"
            data.setdefault(
                "title", "Payout " + (str(pid) if pid not in (None, "") else ""))
            data.setdefault("kind", "payout")
            data.setdefault("status", data.get("status"))
        return data


class PayoutHistory(sdl.EntityList[PayoutRecord]):
    """Typed list of payout requests (``get_payout_history``)."""
    pass


class PayoutRequestReceipt(sdl.Entity):
    """Receipt for request_payout (kind='payout').

    Mirrors the raw auth-gateway POST /v1/developer/payouts/request response
    (loosely typed — known keys carried as Optional pass-through; the request
    amount/method come from params, the gateway echoes id/status when present).
    """

    amount_tokens: Optional[int] = sdl.field(
        default=None,
        role="developer.payout_amount",
        description="Requested payout amount in platform tokens.",
    )
    method: Optional[str] = None
    payout_method: Optional[str] = None
    amount: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            pid = data.get("id") or data.get("payout_id")
            data["id"] = str(pid) if pid not in (None, "") else "payout"
            data.setdefault(
                "title", "Payout " + (str(pid) if pid not in (None, "") else "requested"))
            data.setdefault("kind", "payout")
        return data
