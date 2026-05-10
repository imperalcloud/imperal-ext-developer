"""Developer Portal — right panel router / tab bar."""
from imperal_sdk import ui
from app import ext, _user_id, set_selected_app
from panels_overview import build_overview
from panels_pricing import build_pricing
from panels_analytics import build_analytics
from panels_transactions import build_transactions
from panels_earnings import build_earnings
from panels_deploy import build_deploy

_TABS = [
    ("overview",     "Overview",      "Info"),
    ("analytics",    "Analytics",     "BarChart3"),
    ("transactions", "Transactions",  "List"),
    ("pricing",      "Pricing",       "DollarSign"),
    ("earnings",     "Earnings",      "Wallet"),
    ("deploy",       "Deploy",        "Rocket"),
]

_BUILDERS = {
    "overview": build_overview,
    "pricing": build_pricing,
    "analytics": build_analytics,
    "transactions": build_transactions,
    "earnings": build_earnings,
    "deploy": build_deploy,
}

_PRICING_OPTIONS = [
    {"label": "Free — no charges to users", "value": "free"},
    {"label": "Per Action — charge per function call", "value": "per_action"},
    {"label": "Subscription — flat monthly fee", "value": "subscription"},
]


def _field(label_text: str, placeholder: str, param_name: str, value: str = ""):
    return ui.Stack(children=[
        ui.Text(label_text, variant="caption"),
        ui.Input(placeholder=placeholder, param_name=param_name, value=value),
    ], gap=1)


@ext.panel("dashboard", slot="center", title="App Details", icon="LayoutDashboard",
           center_overlay=True)  # federal v4.1.8 — chat shifts to 380px right rail
async def developer_dashboard(ctx, app_id: str = "", tab: str = "overview",
                               period: str = "30d", view: str = "",
                               page: str = "0", section: str = "", **kwargs):
    uid = _user_id(ctx)
    # section from sidebar cross-panel sync — ALWAYS wins over stale app_id
    if section:
        app_id = section
    if app_id:
        set_selected_app(uid, app_id)

    # Create new app form — full setup with pricing
    if view == "create":
        return ui.Stack(children=[
            ui.Header("Create New App", level=2),
            ui.Form(
                action="create_app",
                submit_label="Create App",
                defaults={"pricing_model": "free", "monthly_price": "0"},
                children=[
                    ui.Section(title="Basic Info", children=[
                        _field("App ID (slug)", "my-cool-extension", "app_id"),
                        _field("Display Name", "My Cool Extension", "display_name"),
                        _field("Description", "What does your extension do?", "description"),
                        _field("Category", "tools", "category", "general"),
                        _field("Git URL (HTTPS)", "https://github.com/you/repo.git", "git_url"),
                    ]),
                    ui.Section(title="Pricing", children=[
                        ui.Text("How do you want to monetize?", variant="caption"),
                        ui.Select(
                            param_name="pricing_model",
                            value="free",
                            options=_PRICING_OPTIONS,
                        ),
                        ui.Text("Monthly price in tokens (for subscription model)", variant="caption"),
                        ui.Input(
                            param_name="monthly_price",
                            value="0",
                            placeholder="5000",
                        ),
                        ui.Alert(
                            type="info",
                            message="Per-tool prices can be configured after deploying your extension (Pricing tab).",
                        ),
                    ]),
                ],
            ),
            ui.Button(
                label="Cancel", variant="ghost",
                on_click=ui.Call("__panel__dashboard", app_id="", tab="", period="", view="", page=""),
            ),
        ], gap=2)

    # Welcome screen
    if not app_id:
        return ui.Stack(children=[
            ui.Header("Developer Portal", level=2),
            ui.Text("Select an app from the sidebar, or create a new one."),
            ui.Button(
                label="Create New App", icon="Plus", variant="primary",
                on_click=ui.Call("__panel__dashboard", app_id="", tab="", period="", view="create", page=""),
            ),
            ui.Alert(
                title="Getting Started",
                message="1. Create an app with a Git URL\n2. Deploy to pull code\n3. Submit for review\n4. Start earning!",
                type="info",
            ),
        ], gap=2)

    # Tab navigation bar
    tab_buttons = [
        ui.Button(
            label=label, icon=icon, size="sm",
            variant="primary" if tab == key else "ghost",
            on_click=ui.Call("__panel__dashboard", app_id=app_id, tab=key,
                             period=period, view="", page="0"),
        )
        for key, label, icon in _TABS
    ]

    try:
        builder = _BUILDERS.get(tab, build_overview)
        content = await builder(uid, app_id, period=period, page=page, view=view, **kwargs)
    except Exception as exc:
        content = ui.Alert(title=f"Error loading {tab}", message=str(exc), type="error")

    return ui.Stack(children=[
        ui.Stack(direction="h", gap=1, children=tab_buttons),
        ui.Divider(),
        content,
    ], gap=1)
