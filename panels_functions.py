"""Developer Portal — Functions tab.

What the author's users actually read. Every @chat.function an extension
exposes carries a `description` in imperal.json, and that text is what the
Marketplace shows on the app page and what Webbee reads when deciding whether
a function fits the user's request. It was collected on every deploy and
stored (36 of 37 apps have it) but shown to the author NOWHERE -- so a weak or
missing description was invisible to the one person who could fix it.

This tab is that mirror: the live list, the exact text, and a straight answer
about which functions are still undescribed.

Source of truth is imperal.json on disk (what is deployed). If the code has
not been pulled yet, we fall back to the manifest stored in the DB so a
freshly created app still shows something real instead of an empty tab.
"""
import json
import os

from imperal_sdk import ui
from app import _gw_get, EXTENSIONS_DIR
from validation import get_extension_tools_full


def _tools_from_db_manifest(app: dict) -> list[dict]:
    """Fallback: read the tools out of the manifest_json column."""
    raw = app.get("manifest_json")
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    tools = []
    for t in data.get("tools", []):
        if not isinstance(t, dict):
            continue
        name = t.get("name", "")
        if not name or name.startswith(("__panel__", "__widget__", "__webhook__", "skeleton_")):
            continue
        if name.startswith("tool_") and name.endswith("_chat"):
            continue
        tools.append({
            "name": name,
            "description": (t.get("description") or "").strip(),
            "action_type": t.get("action_type", ""),
        })
    return tools


async def build_functions(uid: str, app_id: str, view: str = "", **kwargs):
    try:
        app = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as exc:
        return ui.Alert(title="Couldn't load this app",
                        message=f"{type(exc).__name__}: {exc}", type="error")

    app_dir = os.path.join(EXTENSIONS_DIR, app_id)
    tools = get_extension_tools_full(app_dir)
    source = "deployed code"
    if not tools:
        tools = _tools_from_db_manifest(app)
        source = "last synced manifest"

    children = [
        ui.Header("Functions", level=2),
        ui.Text(
            "These descriptions are what users read on your Marketplace page — "
            "and what Webbee reads when deciding which function answers a request. "
            "They come from your imperal.json; edit them there and redeploy.",
            variant="caption",
        ),
    ]

    if not tools:
        children.append(ui.Empty(
            message=(
                "No functions found yet — deploy your extension to pull its code, "
                "and the functions declared in imperal.json will show up here "
                "with their descriptions."
            ),
            icon="Wrench",
        ))
        return ui.Stack(children=children, gap=2)

    described = [t for t in tools if t.get("description")]
    missing = [t for t in tools if not t.get("description")]

    children.append(ui.Stats(children=[
        ui.Stat(label="Functions", value=len(tools), icon="Wrench", color="blue"),
        ui.Stat(label="Described", value=len(described), icon="Check", color="green"),
        ui.Stat(label="Missing description", value=len(missing), icon="AlertTriangle",
                color="red" if missing else "gray"),
    ]))

    if missing:
        children.append(ui.Alert(
            title=f"{len(missing)} function(s) have no description",
            message=(
                "Users see a blank line for these, and Webbee has nothing to go on "
                "when matching them to a request. Add a `description` to each one "
                "in imperal.json, then redeploy.\n\n"
                + ", ".join(t["name"] for t in missing[:20])
                + ("..." if len(missing) > 20 else "")
            ),
            type="warning",
        ))

    children.append(ui.DataTable(
        columns=[
            ui.DataColumn(key="name", label="Function"),
            ui.DataColumn(key="action_type", label="Type"),
            ui.DataColumn(key="description", label="Description users see"),
        ],
        rows=[
            {
                "name": t["name"],
                "action_type": t.get("action_type") or "—",
                "description": t.get("description") or "— no description —",
            }
            for t in tools
        ],
    ))

    children.append(ui.Text(f"Read from: {source}.", variant="caption"))
    return ui.Stack(children=children, gap=2)
