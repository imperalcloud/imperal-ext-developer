"""Developer Portal — left sidebar panel."""
from imperal_sdk import ui
from app import ext, _gw_get, _user_id, set_selected_app
import queries

_STATUS_COLORS = {"draft": "gray", "pending_review": "yellow", "active": "green", "suspended": "red"}
_TIER_COLORS = {"explorer": "gray", "indie": "blue", "studio": "purple", "partner": "yellow"}


@ext.panel("sidebar", slot="left", title="Developer Portal", icon="Code",
           default_width=300, min_width=240, max_width=400)
async def developer_sidebar(ctx, selected_app: str = "", section: str = "", **kwargs):
    uid = _user_id(ctx)
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

    # Not a developer yet
    if not tier:
        children.append(ui.Header("Developer Portal", level=2))
        children.append(ui.Alert(type="info", message="Register as a developer to create extensions."))
        children.append(ui.Button(
            label="Register (Free)", icon="UserPlus", variant="primary",
            on_click=ui.Call("register_developer", tier="explorer"),
        ))
        return ui.Stack(children=children, gap=2)

    # Header + tier badge
    children.append(ui.Stack(direction="h", gap=1, children=[
        ui.Header("Developer Portal", level=3),
        ui.Badge(tier.title(), color=_TIER_COLORS.get(tier, "gray")),
    ]))

    # App list
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
                on_click=ui.Call("__panel__sidebar", selected_app=aid, section=aid),
            ))
        children.append(ui.Section(title=f"My Apps ({len(apps)})", children=[ui.List(items=items)]))
    else:
        children.append(ui.Alert(title="No Apps Yet", message="Create your first extension.", type="info"))

    children.append(ui.Button(
        label="+ New App", icon="Plus", variant="primary",
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
    except Exception:
        pass

    # Auto-trigger center overlay (App Details dashboard) on first sidebar mount.
    # federal v4.1.8 declarative center_overlay → chat shifts to 380px right rail.
    root = ui.Stack(children=children, gap=2)
    root.props["auto_action"] = ui.Call("__panel__dashboard")
    return root
