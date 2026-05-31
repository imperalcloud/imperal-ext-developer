"""Developer Portal — SDL typed return models (additive, non-breaking).

These entities declare the shape of ``ActionResult.data`` for the read tools
so the platform can read them as typed SDL entities (Federal Typed Return
Contract V23 — ``data_model`` is required for ``action_type="read"``).

The ``data_model`` kwarg is schema-declaration only: the SDK records it on
``FunctionDef._return_model`` for manifest ``return_schema`` emission and
catalog ingestion. It does NOT validate or coerce the runtime
``ActionResult.data`` dict, so adding these models is non-breaking to the
existing handlers — every existing field name is preserved verbatim.

Token amounts are platform tokens, not a fiat currency, so they carry custom
``developer.*`` roles via ``sdl.field`` rather than the reserved ``money.*``
facet fields (whose names would not match the handler-visible field names).
"""
from __future__ import annotations

from imperal_sdk import sdl
from pydantic import model_validator


class EarningsSummary(sdl.Entity):
    """Aggregate earnings across all of a developer's apps.

    Shape mirrors ``GET /v1/developer/earnings`` as read by the
    ``get_earnings`` handler (``total_earned`` + ``available`` token totals).
    """

    # --- existing handler-visible fields kept verbatim ---
    total_earned: int | None = sdl.field(
        role="developer.total_earned",
        description="Total tokens earned across all apps (lifetime).",
    )
    available: int | None = sdl.field(
        role="developer.available_earnings",
        description="Tokens available for payout right now.",
    )

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "earnings")
            data.setdefault("title", "Earnings")
        return data


class AppEarnings(sdl.Entity):
    """Earnings scoped to a single app.

    Shape mirrors ``GET /v1/developer/earnings/{app_id}`` as read by the
    ``get_earnings_by_app`` handler (``total_earned`` token total for one app).
    The app id is a path parameter, so it is injected into the canonical
    ``id``/``title`` only when the API echoes it back as ``app_id``.
    """

    # --- existing handler-visible fields kept verbatim ---
    app_id: str | None = None
    total_earned: int | None = sdl.field(
        role="developer.total_earned",
        description="Total tokens earned by this app (lifetime).",
    )

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("app_id") or "app")
            data.setdefault("title", data.get("app_id") or "App earnings")
        return data
