"""Developer Portal — post-deploy artifact sync helpers.

Pushes icon.svg and the full imperal.json blob back to the auth gateway after
a successful deploy. Both calls are non-fatal: the deploy is already on disk
and active by the time these run, so a network blip here only delays the
marketplace UI / ctx.secrets readiness on the next refresh.

Extracted from handlers_deploy.py to keep that module under the workspace's
300-line god-file ceiling (rule 6).
"""
from __future__ import annotations

import glob
import logging
import os

log = logging.getLogger("developer")


def _resolve_icon_path(app_dir: str, manifest: dict) -> str | None:
    """Resolve the icon file inside app_dir. Order: manifest-declared `icon`
    filename (basename only — path-traversal guard; must end .svg), then
    icon.svg, then the sole *.svg in the package root. None if no icon ships
    (the icon endpoint serves a placeholder)."""
    candidates = []
    declared = (manifest or {}).get("icon")
    if declared and str(declared).lower().endswith(".svg"):
        candidates.append(os.path.join(app_dir, os.path.basename(str(declared))))
    candidates.append(os.path.join(app_dir, "icon.svg"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    svgs = glob.glob(os.path.join(app_dir, "*.svg"))
    return svgs[0] if len(svgs) == 1 else None

_ICON_MAX_BYTES = 65_536       # federal manifest cap per Extension icon
_MANIFEST_MAX_BYTES = 1_048_576  # 1 MB ceiling enforced auth-gw side


async def sync_icon_and_manifest_to_gw(app_id: str, app_dir: str, gw_post) -> dict[str, bool]:
    """Sync icon.svg and imperal.json to the auth gateway. Returns sync flags.

    B-icon-db (2026-05-11): the icon is persisted into developer_apps.icon_svg
    so the marketplace + sidebar can render it via
    GET /v1/marketplace/apps/{app_id}/icon (proxied through the panel's
    Next.js /api/extensions/{appId}/icon.svg route). The DB is the single
    source of truth — there is no filesystem sync between hosts.

    EXT-SECRETS-V1 (2026-05-13): the manifest blob is persisted into
    developer_apps.manifest_json so the /v1/secrets/* router can read
    secrets[] for I-SECRETS-CONTRACT-DECLARED enforcement. Without this,
    ctx.secrets.get() against a newly-deployed extension would 404 with
    SECRET_NOT_DECLARED even when the manifest declared the name.

    Both syncs are non-fatal — the deploy itself has already succeeded.
    """
    # Parse manifest once — used for icon-filename resolution and the blob sync.
    _manifest_dict: dict = {}
    _manifest_path = os.path.join(app_dir, "imperal.json")
    if os.path.isfile(_manifest_path):
        try:
            import json as _json
            with open(_manifest_path, "r", encoding="utf-8") as _mf:
                _manifest_dict = _json.load(_mf) or {}
        except Exception:
            _manifest_dict = {}

    icon_synced = False
    icon_path = _resolve_icon_path(app_dir, _manifest_dict)
    if icon_path and os.path.isfile(icon_path):
        try:
            with open(icon_path, "r", encoding="utf-8") as f:
                icon_bytes = f.read()
            if 0 < len(icon_bytes) <= _ICON_MAX_BYTES:
                res = await gw_post(
                    f"/v1/developer/apps/{app_id}/_sync_manifest",
                    {"icon_svg": icon_bytes},
                )
                icon_synced = bool(res.get("updated"))
        except Exception as exc:
            log.warning("B-icon-db sync failed for %s (non-fatal): %s", app_id, exc)

    manifest_synced = False
    manifest_path = os.path.join(app_dir, "imperal.json")
    if os.path.isfile(manifest_path):
        try:
            # B-manifest-indent (2026-08-21): send the PARSED manifest, never the
            # file's raw text.
            #
            # ``imperal.json`` is written pretty-printed (indent=2). WordPress
            # Hub's is 1212 KB on disk -- over the gateway's 1 MB cap -- so the
            # size guard skipped the POST entirely and the deploy reported
            # ``manifest_synced=false`` with no error anywhere: no exception was
            # raised, so the except branch never logged. The SAME manifest
            # serialized compactly is 609 KB, comfortably inside the cap; the
            # 603 KB difference was pure indentation whitespace.
            #
            # The gateway compacts a dict payload itself (json.dumps with
            # separators=(',',':')), so posting the dict both fixes the false
            # rejection and makes this size check measure what the server will
            # actually store.
            import json as _json
            manifest_payload: object
            if _manifest_dict:
                manifest_payload = _manifest_dict
                measured = len(_json.dumps(_manifest_dict, separators=(",", ":"),
                                           ensure_ascii=False).encode("utf-8"))
            else:
                # Unparseable manifest: fall back to the raw text so a
                # hand-edited file still syncs.
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_payload = f.read()
                measured = len(str(manifest_payload).encode("utf-8"))

            if measured > _MANIFEST_MAX_BYTES:
                # Say it out loud. The silent skip is what made this bug take
                # months to attribute.
                log.warning(
                    "manifest_json sync SKIPPED for %s: %d bytes (compact) exceeds "
                    "the %d byte gateway cap -- ctx.secrets and marketplace "
                    "metadata stay stale until the manifest shrinks",
                    app_id, measured, _MANIFEST_MAX_BYTES,
                )
            elif measured > 0:
                sync_payload: dict = {"manifest_json": manifest_payload}
                # I-SYSTEM-FLAG-MANIFEST-SYNC (2026-07-16): the manifest's own
                # top-level `system` bool declares first-party-app INTENT, but
                # nothing ever mirrored it onto developer_apps.system — the
                # SEPARATE gateway column that actually drives Marketplace
                # exclusion + auto-install (_MANIFEST_SYNC_ALLOWED has always
                # included "system"; this call just never sent it). Missing
                # this meant a redeployed app with manifest system=true could
                # still show up in marketplace search (e.g. notifications-control).
                # Include it here so every deploy self-heals the gateway bit
                # from the manifest, same as icon_svg/manifest_json already do.
                if "system" in _manifest_dict:
                    sync_payload["system"] = bool(_manifest_dict.get("system"))
                res = await gw_post(
                    f"/v1/developer/apps/{app_id}/_sync_manifest",
                    sync_payload,
                )
                manifest_synced = bool(res.get("updated"))
        except Exception as exc:
            log.warning(
                "EXT-SECRETS-V1 manifest_json sync failed for %s (non-fatal): %s",
                app_id, exc,
            )

    return {"icon_synced": icon_synced, "manifest_synced": manifest_synced}
