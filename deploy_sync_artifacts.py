"""Developer Portal — post-deploy artifact sync helpers.

Pushes icon.svg and the full imperal.json blob back to the auth gateway after
a successful deploy. Both calls are non-fatal: the deploy is already on disk
and active by the time these run, so a network blip here only delays the
marketplace UI / ctx.secrets readiness on the next refresh.

Extracted from handlers_deploy.py to keep that module under the workspace's
300-line god-file ceiling (rule 6).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("developer")

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
    icon_synced = False
    icon_path = os.path.join(app_dir, "icon.svg")
    if os.path.isfile(icon_path):
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
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_blob = f.read()
            if 0 < len(manifest_blob) <= _MANIFEST_MAX_BYTES:
                res = await gw_post(
                    f"/v1/developer/apps/{app_id}/_sync_manifest",
                    {"manifest_json": manifest_blob},
                )
                manifest_synced = bool(res.get("updated"))
        except Exception as exc:
            log.warning(
                "EXT-SECRETS-V1 manifest_json sync failed for %s (non-fatal): %s",
                app_id, exc,
            )

    return {"icon_synced": icon_synced, "manifest_synced": manifest_synced}
