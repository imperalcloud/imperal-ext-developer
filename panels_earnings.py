"""Developer Portal — Earnings tab builder."""
from imperal_sdk import ui
from app import _gw_get

_MIN_PAYOUT = 10_000  # tokens


async def build_earnings(uid: str, app_id: str, **kwargs):
    # App-level earnings
    try:
        app_earnings = await _gw_get(f"/v1/developer/earnings/{app_id}?user_id={uid}")
    except Exception as exc:
        return ui.Alert(type="error", message=f"Failed to load earnings: {exc}")

    # Global payout summary
    try:
        summary = await _gw_get(f"/v1/developer/earnings?user_id={uid}")
    except Exception:
        summary = {}

    # Payout history
    try:
        payout_resp = await _gw_get(f"/v1/developer/payouts?user_id={uid}")
        payouts = payout_resp if isinstance(payout_resp, list) else payout_resp.get("payouts", [])
    except Exception:
        payouts = []

    # Auth GW returns: total_earnings, action_count, by_period (for app)
    total = app_earnings.get("total_earnings", 0)
    action_count = app_earnings.get("action_count", 0)
    by_period = app_earnings.get("by_period", [])

    # Global: total_earnings, pending_payout, paid_out
    available = summary.get("pending_payout", 0)
    paid_out = summary.get("paid_out", 0)
    global_total = summary.get("total_earnings", 0)

    # Stats for this app
    app_stats = ui.Stats(columns=3, children=[
        ui.Stat(label="App Earned", value=f"{total:,} tok"),
        ui.Stat(label="Actions", value=f"{action_count:,}"),
        ui.Stat(label="Available (All)", value=f"{available:,} tok"),
    ])

    global_stats = ui.Stats(columns=3, children=[
        ui.Stat(label="Total Earned (All Apps)", value=f"{global_total:,} tok"),
        ui.Stat(label="Available for Payout", value=f"{available:,} tok"),
        ui.Stat(label="Paid Out", value=f"{paid_out:,} tok"),
    ])

    # Daily earnings chart
    if by_period:
        chart = ui.Chart(
            type="line",
            data=[{"x": d.get("day", ""), "y": d.get("total", 0)} for d in by_period],
            x_key="x",
            height=250,
        )
    else:
        chart = ui.Text("No daily earnings data yet.", variant="caption")

    # Payout button
    can_payout = available >= _MIN_PAYOUT
    payout_btn = ui.Button(
        label=f"Request Payout ({available:,} tok available)",
        icon="ArrowUpCircle",
        variant="primary" if can_payout else "ghost",
        disabled=not can_payout,
        on_click=ui.Call("tool_developer_chat",
                         message=f"request payout of {available} tokens"),
    )
    payout_note = None
    if not can_payout and available < _MIN_PAYOUT:
        payout_note = ui.Text(
            f"Minimum payout: {_MIN_PAYOUT:,} tok. Need {_MIN_PAYOUT - available:,} more.",
            variant="caption",
        )

    # Payout history table
    history_rows = [
        {
            "date": (p.get("requested_at") or p.get("created_at", ""))[:10],
            "amount": str(p.get("amount_tokens", p.get("amount", 0))),
            "status": p.get("status", ""),
            "method": p.get("method", p.get("payout_method", "")),
        }
        for p in payouts
    ]
    history_table = ui.DataTable(
        columns=[
            ui.DataColumn(key="date",   label="Date"),
            ui.DataColumn(key="amount", label="Amount (tok)"),
            ui.DataColumn(key="status", label="Status"),
            ui.DataColumn(key="method", label="Method"),
        ],
        rows=history_rows,
    ) if history_rows else ui.Text("No payout history.", variant="caption")

    payout_actions = [payout_btn]
    if payout_note:
        payout_actions.append(payout_note)

    return ui.Stack(children=[
        ui.Section(title=f"App: {app_id}", children=[app_stats]),
        ui.Section(title="All Apps Summary", children=[global_stats]),
        ui.Section(title="Daily Earnings", children=[chart]),
        ui.Section(title="Payout", children=payout_actions),
        ui.Section(title="Payout History", children=[history_table]),
    ], gap=3)
