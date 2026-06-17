"""Developer Portal — skeleton tool for AI context refresh."""
from app import ext, _gw_get, _user_id


# SDL-exempt: @ext.tool skeleton (context-refresh), not a @chat.function data
# tool — no data_model required (V23 applies only to chat read/write tools).
@ext.tool("skeleton_refresh_developer_status", scopes=["extensions:read"])
async def refresh_status(ctx, **kwargs) -> dict:
    """Provide developer tier, app count, and earnings to the AI context."""
    uid = _user_id(ctx)
    try:
        profile = await _gw_get(f"/v1/developer/profile?user_id={uid}")
        tier = profile.get("tier") or "none"
        total = profile.get("total_earnings", 0)
        # profile does NOT carry available_earnings/is_developer — derive them.
        # available = pending_payout from the earnings endpoint; is_developer from tier.
        available = 0
        try:
            earn = await _gw_get(f"/v1/developer/earnings?user_id={uid}")
            total = earn.get("total_earnings", total)
            available = earn.get("pending_payout", 0)
        except Exception:
            pass
        return {
            "response": {
                "tier": tier,
                "apps_count": profile.get("apps_count", 0),
                "total_earnings": total,
                "available_earnings": available,
                "is_developer": bool(tier and tier != "none"),
            }
        }
    except Exception:
        return {
            "response": {
                "tier": "none",
                "apps_count": 0,
                "total_earnings": 0,
                "available_earnings": 0,
                "is_developer": False,
            }
        }
