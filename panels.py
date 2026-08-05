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
    # Same false-emptiness hazard as the app list: if this call FAILS we must
    # not conclude "not a developer". tier="" renders the registration form,
    # so a transient gateway error would tell a long-registered developer to
    # sign up again -- and a stray submit would 422 on a taken handle. Track
    # the failure separately and keep the real UI.
    tier, profile_error = "", ""
    try:
        profile = await _gw_get(f"/v1/developer/profile?user_id={uid}")
        tier = profile.get("tier", "")
    except Exception as e:
        profile_error = type(e).__name__
        log.warning("sidebar profile fetch failed for %s: %s: %s", uid[:7], profile_error, e)

    # Not a developer yet — registration form. The gateway requires a unique
    # developer handle (nickname); a bare ui.Call could not collect it, which
    # is why the old "Register (Free)" button always 422'd. Collect it here and
    # forward it through the register_developer handler.
    # Guarded by `not profile_error` so this only ever shows on a SUCCESSFUL
    # read that genuinely returned no tier.
    if not tier and not profile_error:
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
    # A FAILED fetch and an EMPTY account are NOT the same thing. This used to
    # be `except Exception: apps = []`, so when the gateway call failed the
    # sidebar rendered the cheerful "No Apps Yet" -- telling a developer with
    # 10 published apps that they had none. That is exactly how the 2026-08-06
    # incident presented: the /apps list had grown to ~1.3 MB (manifest_json
    # for every app), the 15s httpx timeout fired, and the exception was
    # swallowed into a wrong, confident answer. Silence is the bug here; the
    # oversized payload was only the trigger.
    apps, apps_error = [], ""
    try:
        apps = await _gw_get(f"/v1/developer/apps?user_id={uid}")
    except Exception as e:
        apps_error = type(e).__name__
        log.warning("sidebar app list failed for %s: %s: %s", uid[:7], apps_error, e)

    if apps_error:
        # Say what actually happened and keep the app list ABSENT rather than
        # claiming it is empty -- a wrong answer is worse than a missing one.
        children.append(ui.Alert(
            title="Could not load your apps",
            message=("The Developer Portal could not reach the apps service "
                     f"({apps_error}). Your apps are not affected — this is a "
                     "loading problem. Try again in a moment."),
            type="error"))
    elif apps:
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
