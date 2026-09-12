"""Developer Portal — skeleton derivation from loaded Extension."""
from __future__ import annotations

_SKELETON_REFRESH_PREFIX = "skeleton_refresh_"
_SKELETON_ALERT_PREFIX = "skeleton_alert_"


def _derive_skeleton_sections_from_ext(ext) -> list[dict]:
    """Derive Registry skeleton_sections payload from a loaded Extension."""
    if ext is None or not hasattr(ext, "tools"):
        return []
    tools = ext.tools or {}

    sections: list[dict] = []
    seen: set = set()

    for activity_name, tool_def in tools.items():
        meta = getattr(tool_def, "_skeleton", None)
        if not meta or not isinstance(meta, dict):
            continue
        section_name = meta.get("section_name") or ""
        if not section_name:
            continue
        alert_activity = f"{_SKELETON_ALERT_PREFIX}{section_name}"
        has_alert = alert_activity in tools
        sections.append({
            "name": section_name,
            "refresh_activity": activity_name,
            "alert_activity": alert_activity if has_alert else meta.get("alert_activity"),
            "ttl": int(meta.get("ttl", 300) or 300),
            "alert_on_change": bool(meta.get("alert_on_change") or has_alert),
        })
        seen.add(section_name)

    for activity_name in tools.keys():
        if not isinstance(activity_name, str):
            continue
        if not activity_name.startswith(_SKELETON_REFRESH_PREFIX):
            continue
        section_name = activity_name[len(_SKELETON_REFRESH_PREFIX):]
        if not section_name or section_name in seen:
            continue
        alert_activity = f"{_SKELETON_ALERT_PREFIX}{section_name}"
        has_alert = alert_activity in tools
        sections.append({
            "name": section_name,
            "refresh_activity": activity_name,
            "alert_activity": alert_activity if has_alert else None,
            "ttl": 300,
            "alert_on_change": has_alert,
        })
        seen.add(section_name)

    return sections
