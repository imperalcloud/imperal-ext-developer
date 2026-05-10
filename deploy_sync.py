"""Developer Portal — registry + unified_config sync helpers
(split from handlers_deploy.py).
"""
import sys
import logging

from app import (_gw_post, _gw_put, _registry_post, _registry_put, EXTENSIONS_DIR)

log = logging.getLogger("developer")

_SKELETON_REFRESH_PREFIX = "skeleton_refresh_"
_SKELETON_ALERT_PREFIX = "skeleton_alert_"


async def _record_deploy(uid, app_id, sha, status, error_msg):
    """Record deploy — awaited, not fire-and-forget."""
    try:
        await _gw_post(f"/v1/developer/apps/{app_id}/deploys", {
            "user_id": uid, "commit_sha": sha,
            "status": status, "error_message": error_msg,
        })
    except Exception:
        pass


async def _ensure_app_in_registry(app_id: str, owner_id: str):
    """Ensure app exists in Registry. Creates if missing (409 = already exists = OK)."""
    try:
        await _registry_post("/v1/apps", {
            "app_id": app_id,
            "display_name": app_id,
            "owner_id": owner_id,
        })
        log.info(f"Registry: created app '{app_id}'")
    except Exception as e:
        if "409" in str(e) or "already exists" in str(e).lower():
            pass
        else:
            log.warning(f"Registry: failed to ensure app '{app_id}': {e}")


def _derive_skeleton_sections_from_ext(ext) -> list[dict]:
    """Derive Registry skeleton_sections payload from a loaded Extension.

    Two-source derivation so both styles produce Registry rows:

      (A) Primary — ``@ext.skeleton(section_name, alert=…, ttl=…)`` decorator
          metadata stashed on ``ToolDef._skeleton`` (SDK 1.5.22+).
      (B) Fallback — naming convention: any tool named
          ``skeleton_refresh_<X>`` becomes a section. A sibling
          ``skeleton_alert_<X>`` tool enables ``alert_on_change=True``.

    Pure function — no I/O. Exercised by ``tests/test_skeleton_sync.py``.

    Invariants:
      - I-SKEL-AUTO-DERIVE-1
      - I-PURGE-SKELETON-SCOPE
    """
    if ext is None or not hasattr(ext, "tools"):
        return []
    tools = ext.tools or {}

    sections: list[dict] = []
    seen: set = set()

    # (A) Metadata from @ext.skeleton decorator
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

    # (B) Naming convention fallback
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


async def _sync_tools_to_registry(app_id: str, app_dir: str, owner_id: str = "") -> int:
    """Load extension and sync its tools to Registry so it appears in catalog.

    Auto-creates app in Registry if missing (handles deploy-before-approve).
    """
    try:
        sys.path.insert(0, app_dir)
        from imperal_kernel.core.loader import ExtensionLoader
        loader = ExtensionLoader(EXTENSIONS_DIR)
        ext = loader.load(app_id)

        tools = []
        for activity_name, tool_def in ext.tools.items():
            tools.append({
                "activity": activity_name,
                "name": getattr(tool_def, "display_name", "") or activity_name,
                "description": getattr(tool_def, "description", "") or "",
                "domains": [],
                "required_scopes": getattr(tool_def, "scopes", ["*"]) or ["*"],
            })

        skeleton = _derive_skeleton_sections_from_ext(ext)

        await _ensure_app_in_registry(app_id, owner_id)

        result = await _registry_put(
            f"/v1/apps/{app_id}/tools",
            {"tools": tools, "skeleton_sections": skeleton, "version": ext.version or ""},
        )
        log.info(f"Registry sync: {app_id} — {result.get('tools_registered', 0)} tools registered")
        return result.get("tools_registered", 0)
    except Exception as e:
        log.warning(f"Registry sync failed for {app_id}: {e}")
        return 0


async def _sync_panel_config_to_unified_config(app_id: str, app_dir: str) -> bool:
    """GAP-9: After deploy, write ``config.ui.panels`` into Auth GW
    unified_config so the extension page ``/ext/{app_id}`` renders left/
    right/center panels instead of blank. Reads decorated ``@ext.panel``
    declarations from the loaded extension and PUTs them under
    scope=``app``, scope_id=``app_id``.

    Returns True if panels were found + PUT succeeded. False if extension
    has no panels or PUT failed (logged, non-blocking).
    """
    try:
        sys.path.insert(0, app_dir)
        from imperal_kernel.core.loader import ExtensionLoader
        loader = ExtensionLoader(EXTENSIONS_DIR)
        ext = loader.load(app_id)

        # SDK ALLOWED_PANEL_SLOTS: left, right, center, bottom, overlay,
        # chat-sidebar. Iterate ALL of them — center and bottom and overlay
        # are part of v4.1.7 PANEL_SLOT_RENDERING_STATUS contract.
        from imperal_sdk.types.contributions import ALLOWED_PANEL_SLOTS

        panels_by_slot: dict[str, tuple[str, dict]] = {}
        for name, meta in (ext.panels or {}).items():
            slot = meta.get("slot", "")
            if slot in ALLOWED_PANEL_SLOTS and slot not in panels_by_slot:
                panels_by_slot[slot] = (name, meta)

        if not panels_by_slot:
            return False

        ui_panels: dict[str, dict] = {}
        default_icon = {
            "left":         "Puzzle",
            "right":        "Layout",
            "center":       "LayoutDashboard",
            "bottom":       "PanelBottom",
            "overlay":      "Square",
            "chat-sidebar": "MessageSquare",
        }
        for slot, (name, meta) in panels_by_slot.items():
            entry: dict = {
                "panel_id": name,
                "title": meta.get("title") or name,
                "icon": meta.get("icon") or default_icon.get(slot, "Square"),
            }
            for k in ("default_width", "min_width", "max_width"):
                if k in meta:
                    entry[k] = meta[k]
            # Forward center_overlay flag (federal v4.1.8 — replaces
            # hardcoded TS isCenterOverlay allowlist).
            if meta.get("center_overlay"):
                entry["center_overlay"] = True
            ui_panels[slot] = entry

        payload = {"config": {"ui": {"panels": ui_panels}}}
        path = f"/v1/internal/config/app/{app_id}?tenant_id=default&app_id={app_id}"
        await _gw_put(path, payload)
        log.info(
            "Panel config synced: %s — slots=%s",
            app_id, sorted(ui_panels.keys()),
        )
        return True
    except Exception as e:
        log.warning(f"Panel config sync failed for {app_id}: {e}")
        return False
