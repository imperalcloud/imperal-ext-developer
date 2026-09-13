"""Developer Portal — skeleton tool for AI context refresh."""
from app import ext, _gw_get, _user_id


# SDL-exempt: @ext.skeleton refresh (context-refresh), not a @chat.function
# data tool — no data_model required (V23 applies only to chat read/write
# tools). Uses the modern @ext.skeleton() decorator (not @ext.tool) so the
# kernel auto-wires section metadata (MANIFEST-SKELETON-1).
@ext.skeleton("developer_status")
async def refresh_status(ctx, **kwargs) -> dict:
    """Provide developer tier, app count, earnings, and canonical categories catalog to AI context."""
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

        # Fetch canonical categories catalog so Webbee always knows ALL 121 categories
        categories = []
        try:
            cat_data = await _gw_get("/v1/marketplace/categories/catalog")
            for g in (cat_data.get("groups") or []):
                for c in (g.get("categories") or []):
                    cid = c.get("id") or c.get("category") or c.get("slug")
                    if cid and cid not in categories:
                        categories.append(str(cid))
        except Exception:
            pass

        return {
            "response": {
                "tier": tier,
                "apps_count": profile.get("apps_count", 0),
                "total_earnings": total,
                "available_earnings": available,
                "is_developer": bool(tier and tier != "none"),
                "categories": categories,
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
                "categories": [],
            }
        }
