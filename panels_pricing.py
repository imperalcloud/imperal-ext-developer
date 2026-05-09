"""Developer Portal — Pricing tab builder with edit forms."""
import os
from imperal_sdk import ui
from app import _gw_get, EXTENSIONS_DIR
from validation import get_extension_tools

_MODEL_OPTIONS = [
    {"label": "Free — no charges, great for showcasing", "value": "free"},
    {"label": "Per Action — charge per function call", "value": "per_action"},
    {"label": "Subscription — flat monthly fee", "value": "subscription"},
]

_MODEL_DESCRIPTIONS = {
    "per_action": "Users pay tokens per function call. You earn your revenue split on each.",
    "subscription": "Users pay a flat monthly token fee. Revenue split based on usage.",
    "free": "No charges. Users can use all functions for free. Great for building audience.",
}


async def build_pricing(uid: str, app_id: str, view: str = "", **kwargs):
    app = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    status = app.get("status", "draft")
    model = app.get("pricing_model", "free")
    split = app.get("revenue_split_dev", 80)
    config = app.get("pricing_config") or {}
    tool_prices = config.get("tool_prices", {})

    # Read tools from disk
    app_dir = os.path.join(EXTENSIONS_DIR, app_id)
    tools = get_extension_tools(app_dir)

    can_edit = status in ("draft", "suspended")
    children = []

    # Edit form
    if view == "edit" and can_edit:
        return _build_edit_form(app_id, model, split, config, tools, tool_prices)

    # Current pricing display
    children.append(ui.Section(title="Pricing Model", children=[
        ui.KeyValue(items=[
            {"key": "Model", "value": model.replace("_", " ").title()},
            {"key": "Your Revenue Split", "value": f"{split}%"},
            {"key": "Platform Fee", "value": f"{100 - split}%"},
        ], columns=3),
        ui.Text(_MODEL_DESCRIPTIONS.get(model, ""), variant="caption"),
    ]))

    # Per-tool prices
    if model == "per_action":
        if tools:
            rows = []
            for t in tools:
                price = tool_prices.get(t["name"], 0)
                your_share = int(price * split / 100) if price else 0
                rows.append({
                    "function": t["name"],
                    "description": t["description"][:40],
                    "price": str(price) if price else "not set",
                    "your_share": str(your_share),
                })
            children.append(ui.Section(title="Function Prices", children=[
                ui.DataTable(
                    columns=[
                        ui.DataColumn(key="function", label="Function", width="30%"),
                        ui.DataColumn(key="description", label="Description", width="30%"),
                        ui.DataColumn(key="price", label="Price (tok)", width="20%"),
                        ui.DataColumn(key="your_share", label="Your Share", width="20%"),
                    ],
                    rows=rows,
                ),
            ]))
        else:
            children.append(ui.Alert(type="info",
                                     message="Deploy your extension first to see available functions."))

    elif model == "subscription":
        monthly = config.get("monthly_price", 0)
        if monthly:
            children.append(ui.Stats(columns=2, children=[
                ui.Stat(label="Monthly Price", value=f"{monthly:,} tok"),
                ui.Stat(label="Your Monthly Share", value=f"{int(monthly * split / 100):,} tok"),
            ]))
        else:
            children.append(ui.Alert(type="info", message="Monthly price not configured yet."))

    # Edit button or lock message
    if can_edit:
        children.append(ui.Button(
            label="Edit Pricing", icon="Pencil", variant="primary",
            on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="pricing",
                             period="", view="edit", page=""),
        ))
    elif status == "active":
        children.append(ui.Alert(
            type="warning",
            message="Pause your app to edit pricing. Active apps cannot change prices.",
        ))
    elif status == "pending_review":
        children.append(ui.Alert(type="info", message="Pricing locked during review."))

    return ui.Stack(children=children, gap=3)


def _build_edit_form(app_id, model, split, config, tools, tool_prices):
    """Build the pricing edit form."""
    children = [ui.Header("Edit Pricing", level=2)]

    # Model selector
    form_children = [
        ui.Text("Pricing Model", variant="caption"),
        ui.Select(
            param_name="pricing_model",
            value=model,
            options=_MODEL_OPTIONS,
        ),
    ]

    # Per-tool price inputs (shown regardless — relevant for per_action)
    if tools:
        form_children.append(ui.Text("Function Prices (tokens per call)", variant="caption"))
        for t in tools:
            current_price = str(tool_prices.get(t["name"], "0"))
            form_children.append(ui.Stack(direction="h", gap=1, children=[
                ui.Text(t["name"], variant="caption"),
                ui.Input(
                    param_name=f"price_{t['name']}",
                    value=current_price,
                    placeholder="0",
                ),
            ]))
    else:
        form_children.append(ui.Alert(type="info",
                                      message="Deploy first to configure per-function prices."))

    # Monthly price (for subscription)
    monthly = str(config.get("monthly_price", "0"))
    form_children.append(ui.Text("Monthly Price (for subscription model)", variant="caption"))
    form_children.append(ui.Input(
        param_name="monthly_price",
        value=monthly,
        placeholder="5000",
    ))

    # Build defaults with current values
    defaults = {
        "app_id": app_id,
        "pricing_model": model,
        "monthly_price": monthly,
    }
    for t in tools:
        defaults[f"price_{t['name']}"] = str(tool_prices.get(t["name"], "0"))

    children.append(ui.Form(
        action="save_pricing",
        submit_label="Save Pricing",
        defaults=defaults,
        children=form_children,
    ))

    children.append(ui.Button(
        label="Cancel", variant="ghost",
        on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="pricing",
                         period="", view="", page=""),
    ))

    return ui.Stack(children=children, gap=2)
