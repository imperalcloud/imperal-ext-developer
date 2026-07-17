"""Developer Portal — registry + unified_config sync helpers
(split from handlers_deploy.py).
"""
import json
import os
import sys
import logging

from app import (_gw_post, _gw_put, _registry_post, _registry_put,
                 _registry_patch, EXTENSIONS_DIR)

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


def _manifest_display_name(app_id: str) -> str:
    """The extension's declared display name from its on-disk manifest — the
    single source of truth for the app's name (slice-9, 2026-07-17). Empty on
    any read/parse trouble (caller falls back to app_id)."""
    try:
        mf = os.path.join(EXTENSIONS_DIR, app_id, "imperal.json")
        with open(mf, "r", encoding="utf-8") as f:
            return str(json.load(f).get("name") or "").strip()
    except Exception:
        return ""


async def _ensure_app_in_registry(app_id: str, owner_id: str, display_name: str = ""):
    """Ensure app exists in Registry with its manifest display name.

    Creates with the manifest name (slice-9: was app_id — the slug then leaked
    to the capability list and forced a kernel-side humanizer). On 409 (already
    exists), REFRESH display_name from the manifest so the Registry row tracks
    the manifest SSOT on every redeploy — the row was previously never updated,
    so a name added after first deploy never propagated."""
    _name = display_name or app_id
    try:
        await _registry_post("/v1/apps", {
            "app_id": app_id,
            "display_name": _name,
            "owner_id": owner_id,
        })
        log.info(f"Registry: created app '{app_id}' (display_name='{_name}')")
    except Exception as e:
        if "409" in str(e) or "already exists" in str(e).lower():
            # Existing row — keep its display_name tracking the manifest.
            if display_name and display_name != app_id:
                try:
                    await _registry_patch(f"/v1/apps/{app_id}",
                                          {"display_name": display_name})
                    log.info(f"Registry: refreshed display_name for '{app_id}' -> '{display_name}'")
                except Exception as pe:
                    log.warning(f"Registry: display_name refresh for '{app_id}' failed: {pe}")
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

        await _ensure_app_in_registry(app_id, owner_id,
                                      display_name=_manifest_display_name(app_id))

        result = await _registry_put(
            f"/v1/apps/{app_id}/tools",
            {"tools": tools, "skeleton_sections": skeleton, "version": ext.version or ""},
        )
        log.info(f"Registry sync: {app_id} — {result.get('tools_registered', 0)} tools registered")
        return result.get("tools_registered", 0)
    except Exception as e:
        log.warning(f"Registry sync failed for {app_id}: {e}")
        return 0


async def _sync_ir_manifest(app_id: str, ir_dict: dict) -> bool:
    """Sync IR-derived manifest_json to the developer record via the gateway.

    Populates developer_apps.manifest_json / tools_json so that the owner API
    (GET /v1/developer/apps/{app_id}) returns tool classifications for IR apps,
    enabling the MCP read-only gate (finding F1).  The gateway auto-derives
    tools_json from manifest_json["tools"], so we only POST the manifest dict.

    Non-fatal: a failure here must NOT fail the deploy.  Returns True if the
    gateway confirmed the update.
    """
    try:
        app = (ir_dict.get("app") or {})
        manifest = {
            "name": app.get("title") or app_id,
            "version": app.get("version") or "ir",
            "description": app.get("description", ""),
            "tools": [
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "action_type": fn.get("action_type", "read"),
                    "params_schema": fn.get("params_schema", {}),
                }
                for fn in (app.get("functions") or [])
                if fn.get("name")
            ],
        }
        res = await _gw_post(
            f"/v1/developer/apps/{app_id}/_sync_manifest",
            {"manifest_json": manifest},
        )
        updated = bool(res.get("updated"))
        log.info("IR manifest synced for %s — tools=%d updated=%s", app_id, len(manifest["tools"]), updated)
        return updated
    except Exception as exc:
        log.warning("IR manifest sync failed for %s (non-fatal): %s", app_id, exc)
        return False


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

        # I-PANEL-SLOT-PRUNE (2026-06-18): PUT the COMPLETE current slot map and
        # flag ui.panels for wholesale REPLACE so a renamed/removed @ext.panel
        # does NOT leave an orphan slot in unified_config pointing at a panel the
        # code no longer declares (root cause of the perpetual left-column
        # spinner — "panel doesn't render new changes"). The GW deep-merge never
        # deletes keys absent from the body; replace_paths=["ui.panels"] prunes.
        # We always PUT (even an empty map) so "all panels removed" also clears.
        payload = {
            "config": {"ui": {"panels": ui_panels}},
            "replace_paths": ["ui.panels"],
        }
        path = f"/v1/internal/config/app/{app_id}?tenant_id=default&app_id={app_id}"
        await _gw_put(path, payload)
        log.info(
            "Panel config synced (replace): %s — slots=%s",
            app_id, sorted(ui_panels.keys()),
        )
        return bool(panels_by_slot)
    except Exception as e:
        log.warning(f"Panel config sync failed for {app_id}: {e}")
        return False
