"""Developer Portal — Transactions tab builder."""
from imperal_sdk import ui
from queries import get_transactions

_PAGE_SIZE = 30


async def build_transactions(uid: str, app_id: str, page: str = "0", **kwargs):
    page_num = int(page) if str(page).isdigit() else 0
    offset = page_num * _PAGE_SIZE

    try:
        rows = await get_transactions(uid, app_id, limit=_PAGE_SIZE + 1, offset=offset)
    except Exception as exc:
        return ui.Alert(type="error", message=f"Failed to load transactions: {exc}")

    has_next = len(rows) > _PAGE_SIZE
    rows = rows[:_PAGE_SIZE]

    if not rows and page_num == 0:
        return ui.Stack(children=[
            ui.Alert(
                type="info",
                message="No transactions yet. Actions will appear here as users interact with your app.",
            ),
        ], gap=2)

    table = ui.DataTable(
        columns=[
            ui.DataColumn(key="event_id", label="Event ID", width="15%"),
            ui.DataColumn(key="user",     label="User",     width="18%"),
            ui.DataColumn(key="function", label="Function", width="22%"),
            ui.DataColumn(key="cost",     label="Cost",     width="12%"),
            ui.DataColumn(key="share",    label="Your Share", width="13%"),
            ui.DataColumn(key="date",     label="Date",     width="20%"),
        ],
        rows=[{
            "event_id": r["event_id"],
            "user": r["user"],
            "function": r["function"],
            "cost": str(r["cost"]),
            "share": str(r["share"]),
            "date": r["date"][:19],
        } for r in rows],
    )

    nav_buttons = []
    if page_num > 0:
        nav_buttons.append(ui.Button(
            label="Previous", icon="ChevronLeft", size="sm", variant="ghost",
            on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="transactions",
                             period="", view="", page=str(page_num - 1)),
        ))
    nav_buttons.append(ui.Text(f"Page {page_num + 1}", variant="caption"))
    if has_next:
        nav_buttons.append(ui.Button(
            label="Next", icon="ChevronRight", size="sm", variant="ghost",
            on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="transactions",
                             period="", view="", page=str(page_num + 1)),
        ))

    children = [table]
    if nav_buttons:
        children.append(ui.Stack(direction="h", gap=1, children=nav_buttons))

    return ui.Stack(children=children, gap=2)
