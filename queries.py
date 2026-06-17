"""Developer Portal — direct MySQL analytics queries."""
import os
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL env var is required for developer extension "
        "(no plaintext credential fallback -- federal/CJIS)"
    )

_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5)
_AsyncSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _session() -> AsyncSession:
    return _AsyncSession()


def _mask_user(uid: str) -> str:
    if not uid or len(uid) < 10:
        return uid or "—"
    return f"{uid[:7]}...{uid[-4:]}"


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
async def get_app_stats(developer_id: str, app_id: Optional[str], days: int = 30) -> dict:
    app_filter = "AND app_id = :app_id" if app_id else ""
    sql = f"""
        SELECT
            COUNT(*) AS total_calls,
            COALESCE(SUM(developer_share), 0) AS total_revenue,
            COUNT(DISTINCT user_id) AS unique_users
        FROM developer_earnings
        WHERE developer_id = :dev_id
          {app_filter}
          AND created_at >= NOW() - INTERVAL :days DAY
    """
    async with _AsyncSession() as session:
        params = {"dev_id": developer_id, "days": days}
        if app_id:
            params["app_id"] = app_id
        row = (await session.execute(text(sql), params)).fetchone()
    return {
        "total_calls": int(row.total_calls) if row else 0,
        "total_revenue": int(row.total_revenue) if row else 0,
        "unique_users": int(row.unique_users) if row else 0,
    }


async def get_revenue_chart(developer_id: str, app_id: Optional[str], days: int = 30) -> list:
    app_filter = "AND app_id = :app_id" if app_id else ""
    sql = f"""
        SELECT
            DATE(created_at) AS day,
            COALESCE(SUM(developer_share), 0) AS revenue
        FROM developer_earnings
        WHERE developer_id = :dev_id
          {app_filter}
          AND created_at >= NOW() - INTERVAL :days DAY
        GROUP BY DATE(created_at)
        ORDER BY day ASC
    """
    async with _AsyncSession() as session:
        params = {"dev_id": developer_id, "days": days}
        if app_id:
            params["app_id"] = app_id
        rows = (await session.execute(text(sql), params)).fetchall()
    return [{"day": str(r.day), "revenue": int(r.revenue)} for r in rows]


async def get_top_functions(developer_id: str, app_id: Optional[str], days: int = 30) -> list:
    app_filter = "AND app_id = :app_id" if app_id else ""
    sql = f"""
        SELECT
            tool_name,
            COUNT(*) AS calls,
            COALESCE(SUM(developer_share), 0) AS revenue
        FROM developer_earnings
        WHERE developer_id = :dev_id
          {app_filter}
          AND created_at >= NOW() - INTERVAL :days DAY
        GROUP BY tool_name
        ORDER BY calls DESC
        LIMIT 20
    """
    async with _AsyncSession() as session:
        params = {"dev_id": developer_id, "days": days}
        if app_id:
            params["app_id"] = app_id
        rows = (await session.execute(text(sql), params)).fetchall()
    return [{"function": r.tool_name, "calls": int(r.calls), "revenue": int(r.revenue)} for r in rows]


async def get_transactions(developer_id: str, app_id: Optional[str],
                           limit: int = 50, offset: int = 0) -> list:
    app_filter = "AND app_id = :app_id" if app_id else ""
    sql = f"""
        SELECT event_id, user_id, app_id, tool_name,
               action_cost, developer_share, platform_share, created_at
        FROM developer_earnings
        WHERE developer_id = :dev_id {app_filter}
        ORDER BY created_at DESC
        LIMIT :lim OFFSET :off
    """
    async with _AsyncSession() as session:
        params = {"dev_id": developer_id, "lim": limit, "off": offset}
        if app_id:
            params["app_id"] = app_id
        rows = (await session.execute(text(sql), params)).fetchall()
    return [
        {
            "event_id": (r.event_id or "")[:12],
            "user": _mask_user(r.user_id),
            "function": r.tool_name or "",
            "cost": int(r.action_cost) if r.action_cost else 0,
            "share": int(r.developer_share) if r.developer_share else 0,
            "date": str(r.created_at),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Deploys
# ---------------------------------------------------------------------------
async def get_deploy_history(app_id: str, limit: int = 20) -> list:
    sql = """
        SELECT commit_sha, status, error_message, deployed_at
        FROM app_deploys
        WHERE app_id = :app_id
        ORDER BY deployed_at DESC
        LIMIT :lim
    """
    async with _AsyncSession() as session:
        rows = (await session.execute(text(sql), {"app_id": app_id, "lim": limit})).fetchall()
    return [
        {
            "sha": (r.commit_sha or "")[:8],
            "status": r.status or "",
            "error": r.error_message or "",
            "date": str(r.deployed_at) if r.deployed_at else "",
        }
        for r in rows
    ]


async def get_latest_deploy(app_id: str) -> dict | None:
    """Latest successful or warning deploy for 'Current Version' display."""
    sql = """
        SELECT commit_sha, status, deployed_at
        FROM app_deploys
        WHERE app_id = :app_id AND status IN ('success', 'warning')
        ORDER BY deployed_at DESC
        LIMIT 1
    """
    async with _AsyncSession() as session:
        row = (await session.execute(text(sql), {"app_id": app_id})).fetchone()
    if not row:
        return None
    return {
        "commit": (row.commit_sha or "")[:8],
        "status": row.status or "",
        "deployed_at": str(row.deployed_at) if row.deployed_at else "",
    }


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------
async def get_earnings_total(developer_id: str) -> dict:
    # developer_earnings has NO `paid` column; paid-out is tracked in
    # developer_payouts. Mirror the gateway (service.get_earnings): total =
    # SUM(developer_share); paid = SUM(amount_tokens) of approved/paid payouts;
    # available = total - paid.
    total_sql = (
        "SELECT COALESCE(SUM(developer_share), 0) AS total "
        "FROM developer_earnings WHERE developer_id = :dev_id"
    )
    paid_sql = (
        "SELECT COALESCE(SUM(amount_tokens), 0) AS paid "
        "FROM developer_payouts WHERE developer_id = :dev_id "
        "AND status IN ('approved', 'paid')"
    )
    async with _AsyncSession() as session:
        total = int((await session.execute(text(total_sql), {"dev_id": developer_id})).scalar() or 0)
        paid = int((await session.execute(text(paid_sql), {"dev_id": developer_id})).scalar() or 0)
    return {"total": total, "paid": paid, "available": max(0, total - paid)}
