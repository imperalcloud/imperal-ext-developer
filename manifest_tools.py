"""Developer Portal — helper functions to read tools from imperal.json."""
import json
import os


def get_extension_tools(app_dir: str) -> list[dict]:
    """Read user-facing tools from imperal.json (skip panels + skeleton)."""
    manifest = os.path.join(app_dir, "imperal.json")
    if not os.path.isfile(manifest):
        return []
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    tools = []
    for t in data.get("tools", []):
        name = t.get("name", "")
        if name.startswith("__panel__") or name.startswith("skeleton_"):
            continue
        tools.append({"name": name, "description": t.get("description", "")[:80]})
    return tools


def get_extension_tools_full(app_dir: str) -> list[dict]:
    """Same tools as get_extension_tools, but with the FULL description text."""
    manifest = os.path.join(app_dir, "imperal.json")
    if not os.path.isfile(manifest):
        return []
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
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
