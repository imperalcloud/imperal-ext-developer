"""Developer Portal — left sidebar panel."""
import logging
from imperal_sdk import ui
from app import ext, _gw_get, _user_id, set_selected_app
import queries

log = logging.getLogger("developer")

_STATUS_COLORS = {"draft": "gray", "pending_review": "yellow", "active": "green", "suspended": "red"}
_TIER_COLORS = {"explorer": "gray", "indie": "blue", "studio": "purple", "partner": "yellow"}


@ext.panel("sidebar", slot="left", title="Developer Portal", icon="Code",
           default_width=300, min_width=240, max_width=400)
async def developer_sidebar(ctx, selected_app: str = "", section: str = "", **kwargs):
    uid = _user_id(ctx)
    # selected_app is passed through by the panel hook after a center-overlay
    # render so the highlight follows the dashboard's current app.
    if selected_app:
        set_selected_app(uid, selected_app)
    active_app = selected_app or ""
    children = []

    # Fetch profile
    try:
        profile = await _gw_get(f"/v1/developer/profile?user_id={uid}")
        tier = profile.get("tier", "")
    except Exception:
        tier = ""

    # Not a developer yet — registration form. The gateway requires a unique
    # developer handle (nickname); a bare ui.Call could not collect it, which
    # is why the old "Register (Free)" button always 422'd. Collect it here and
    # forward it through the register_developer handler.
    if not tier:
        children.append(ui.Header("Developer Portal", level=2))
        children.append(ui.Text(
            "Register as a developer to publish your own extensions. "
            "Explorer tier is free."))
        children.append(ui.Form(
            action="register_developer",
            submit_label="Register (Free)",
            defaults={"tier": "explorer"},
            children=[
                ui.Text(
                    "Choose a public developer handle — 3-30 chars: "
                    "lowercase a-z, 0-9, _ or - (e.g. your company slug).",
                    variant="caption"),
                ui.Input(placeholder="e.g. bluebeeweb", param_name="nickname"),
            ],
        ))
        return ui.Stack(children=children, gap=2)

    # Header + tier badge
    children.append(ui.Stack(direction="h", gap=1, children=[
        ui.Header("Developer Portal", level=3),
        ui.Badge(tier.title(), color=_TIER_COLORS.get(tier, "gray")),
    ]))

    # App list — clicks go directly to the center dashboard so the workshop
    # renders, while the hook's center→left passthrough keeps the highlight
    # in sync (selected_app wired into this handler).
    try:
        apps = await _gw_get(f"/v1/developer/apps?user_id={uid}")
    except Exception:
        apps = []

    if apps:
        items = []
        for app in apps:
            aid = app["app_id"]
            status = app.get("status", "draft")
            items.append(ui.ListItem(
                id=aid,
                title=app.get("display_name", aid),
                subtitle=aid,
                badge=ui.Badge(status.replace("_", " ").title(), color=_STATUS_COLORS.get(status, "gray")),
                selected=(aid == active_app),
                on_click=ui.Call("__panel__dashboard", app_id=aid, tab="overview",
                                 period="30d", view="", page="0"),
            ))
        children.append(ui.Section(title=f"My Apps ({len(apps)})", children=[ui.List(items=items)]))
    else:
        children.append(ui.Alert(title="No Apps Yet", message="Create your first extension.", type="info"))

    children.append(ui.Button(
        label="New App", icon="Plus", variant="primary",
        on_click=ui.Call("__panel__dashboard", app_id="", tab="", period="", view="create", page=""),
    ))

    # Earnings summary
    try:
        earnings = await queries.get_earnings_total(uid)
        children.append(ui.Section(title="Earnings", children=[ui.KeyValue(items=[
            {"key": "Total earned", "value": f"{earnings['total']:,}"},
            {"key": "Paid out", "value": f"{earnings['paid']:,}"},
            {"key": "Available", "value": f"{earnings['available']:,}"},
        ], columns=1)]))
    except Exception as e:
        # Don't crash the sidebar, but don't swallow silently either — a broken
        # earnings query (e.g. a bad column) must be visible in the logs.
        log.warning("sidebar earnings summary failed for %s: %s", uid[:7], e)

    # Auto-trigger center overlay (App Details dashboard) on first sidebar mount.
    # federal v4.1.8 declarative center_overlay → chat shifts to 380px right rail.
    root = ui.Stack(children=children, gap=2)
    root.props["auto_action"] = ui.Call("__panel__dashboard")
    return root
