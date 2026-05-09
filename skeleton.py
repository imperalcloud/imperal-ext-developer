"""Developer Portal — skeleton tool for AI context refresh."""
from app import ext, _gw_get, _user_id


@ext.tool("skeleton_refresh_developer_status", scopes=["extensions:read"])
async def refresh_status(ctx, **kwargs) -> dict:
    """Provide developer tier, app count, and earnings to the AI context."""
    uid = _user_id(ctx)
    try:
        profile = await _gw_get(f"/v1/developer/profile?user_id={uid}")
        return {
            "response": {
                "tier": profile.get("tier", "none"),
                "apps_count": profile.get("apps_count", 0),
                "total_earnings": profile.get("total_earnings", 0),
                "available_earnings": profile.get("available_earnings", 0),
                "is_developer": profile.get("is_developer", False),
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
