"""Developer Portal — Analytics tab builder."""
from imperal_sdk import ui
from app import _user_id
from queries import get_app_stats, get_revenue_chart, get_top_functions

_PERIODS = [("7d", 7), ("30d", 30), ("90d", 90)]


async def build_analytics(uid: str, app_id: str, period: str = "30d", **kwargs):
    # Period selector
    period_buttons = [
        ui.Button(
            label=key,
            variant="primary" if period == key else "ghost",
            on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="analytics",
                             period=key, view="", page=""),
        )
        for key, _ in _PERIODS
    ]
    period_nav = ui.Stack(children=period_buttons, direction="h", gap=1)

    days = dict(_PERIODS).get(period, 30)

    # Fetch data
    try:
        stats = await get_app_stats(uid, app_id, days)
        chart_data = await get_revenue_chart(uid, app_id, days)
        top_fns = await get_top_functions(uid, app_id, days)
    except Exception as exc:
        return ui.Stack(children=[
            period_nav,
            ui.Alert(type="error", message=f"Failed to load analytics: {exc}"),
        ], gap=2)

    # Empty state
    if stats["total_calls"] == 0:
        return ui.Stack(children=[
            period_nav,
            ui.Alert(type="info", message=f"No activity in the last {days} days."),
        ], gap=2)

    # Stats cards
    stat_cards = ui.Stats(columns=3, children=[
        ui.Stat(label="Total Calls",  value=f"{stats['total_calls']:,}"),
        ui.Stat(label="Revenue",      value=f"{stats['total_revenue']:,} tok"),
        ui.Stat(label="Unique Users", value=f"{stats['unique_users']:,}"),
    ])

    # Revenue chart
    if chart_data:
        chart = ui.Chart(
            type="line",
            data=[{"x": r["day"], "y": r["revenue"]} for r in chart_data],
            x_key="x",
            height=250,
        )
    else:
        chart = ui.Text("Not enough data for chart.", variant="caption")

    # Top functions table
    fn_table = ui.DataTable(
        columns=[
            ui.DataColumn(key="function",  label="Function"),
            ui.DataColumn(key="calls",     label="Calls"),
            ui.DataColumn(key="revenue",   label="Revenue (tok)"),
        ],
        rows=[{"function": r["function"], "calls": str(r["calls"]),
               "revenue": str(r["revenue"])} for r in top_fns],
    ) if top_fns else ui.Text("No function data.", variant="caption")

    return ui.Stack(children=[
        period_nav,
        stat_cards,
        ui.Section(title="Daily Revenue", children=[chart]),
        ui.Section(title="Top Functions", children=[fn_table]),
    ], gap=3)
