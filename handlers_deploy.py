"""Developer Portal — deploy & submit handlers (split from handlers.py)."""
import asyncio
import json
import os
import shutil
import sys
from pydantic import BaseModel, Field
from imperal_sdk.chat import ActionResult
from app import (chat, _gw_get, _gw_post, _gw_put, _registry_post, _registry_put,
                 _user_id, EXTENSIONS_DIR)
from validation import validate_extension_full
import logging

log = logging.getLogger("developer")
PIPE = asyncio.subprocess.PIPE

# Make scripts importable for R11 check
sys.path.insert(0, "/home/imperal-platform-worker/scripts")

# I-FIRSTPARTY-ADMIN-ONLY-CLAIM (2026-05-09): system-tier first-party
# extensions Admin can re-deploy through the canonical Dev Portal flow.
# Sharelock is intentionally NOT here — it's an enterprise/agency-tier
# product with its own deploy lifecycle. When the deployed dir at
# /opt/extensions/<app_id>/ exists without `.git/` (legacy hand-deploy),
# admin re-deploy backs up the dir and clones from git_url, replacing
# the legacy copy with the canonical git-managed copy.
FIRSTPARTY_APP_IDS = {"admin", "automations", "billing", "developer", "hello-world"}
FIRSTPARTY_BACKUP_DIR = "/opt/backups/extensions"


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------
class DeployParams(BaseModel):
    app_id: str = Field(..., description="App to deploy")


class SubmitParams(BaseModel):
    app_id: str = Field(..., description="App to submit for review")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
async def _git_remote_url(app_dir: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", app_dir, "remote", "get-url", "origin",
        stdout=PIPE, stderr=PIPE,
    )
    out, _ = await proc.communicate()
    return out.decode().strip() if proc.returncode == 0 else None


async def _git_pull_or_clone(
    app_dir: str,
    git_url: str,
    *,
    caller_role: str = "developer",
    app_id: str = "",
) -> tuple[str, str]:
    """Clone or pull with smart directory handling.

    `caller_role` + `app_id` thread `I-FIRSTPARTY-ADMIN-ONLY-CLAIM`
    through the squat-refuse branch: when an admin re-deploys a system
    first-party extension whose dir exists without a `.git/` (legacy
    hand-deploy shape), back up + clone instead of refusing.
    """
    # Pin git's safe.directory for this extension dir so files written
    # by rsync/restore from a different uid (e.g. backup-and-restore
    # paths, hand-edited copies) don't trip the dubious-ownership
    # check at fetch/pull time. Idempotent — git silently dedups.
    try:
        _safe_proc = await asyncio.create_subprocess_exec(
            "git", "config", "--global", "--add", "safe.directory", app_dir,
            stdout=PIPE, stderr=PIPE,
        )
        await _safe_proc.communicate()
    except Exception as exc:
        log.warning("safe.directory pin failed for %s: %s", app_dir, exc)

    git_dir = os.path.join(app_dir, ".git")

    if os.path.isdir(git_dir):
        # Squatting defence: if the existing repo's origin does not match the
        # caller's declared git_url, refuse. Previously we silently rewrote the
        # remote, which allowed a rogue dev who registered a clashing app_id
        # (e.g. `mail`) to take over the first-party extension directory on
        # first deploy. Remote-URL equality is our ownership proof for the
        # .git-exists branch.
        current_remote = await _git_remote_url(app_dir)
        if current_remote and current_remote.rstrip("/") != git_url.rstrip("/"):
            return ("squatting_refused",
                    f"/opt/extensions path already owned by a different git remote "
                    f"({current_remote}); refusing to overwrite with {git_url}")

        # task #75: fetch+reset replaces `git pull --ff-only`.
        # Federal rigor: upstream is source of truth. Deploy MUST succeed
        # regardless of local worktree state (dirty files from prior deploys,
        # upstream force-pushes, etc.). `git fetch + reset --hard origin/BRANCH`
        # is idempotent and never fails on dirty tree.
        #
        # We detect the default branch via `symbolic-ref refs/remotes/origin/HEAD`
        # so the fix works for repos with `main`, `master`, or custom defaults.

        # fetch upstream refs
        proc_fetch = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "fetch", "origin",
            stdout=PIPE, stderr=PIPE,
        )
        _, fetch_err = await proc_fetch.communicate()
        if proc_fetch.returncode != 0:
            return ("pull_failed", fetch_err.decode()[:300])

        # resolve default branch — prefer symbolic-ref; fallback to main then master
        proc_def = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD",
            stdout=PIPE, stderr=PIPE,
        )
        def_out, _ = await proc_def.communicate()
        default_ref = def_out.decode().strip() or "origin/main"
        if not default_ref.startswith("origin/"):
            default_ref = "origin/" + default_ref.split("/")[-1]

        # hard-reset to upstream
        proc_reset = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "reset", "--hard", default_ref,
            stdout=PIPE, stderr=PIPE,
        )
        _, reset_err = await proc_reset.communicate()
        if proc_reset.returncode != 0:
            # Fallback: try `origin/main` then `origin/master` explicitly.
            for fallback in ("origin/main", "origin/master"):
                if fallback == default_ref:
                    continue
                proc_fb = await asyncio.create_subprocess_exec(
                    "git", "-C", app_dir, "reset", "--hard", fallback,
                    stdout=PIPE, stderr=PIPE,
                )
                _, fb_err = await proc_fb.communicate()
                if proc_fb.returncode == 0:
                    return ("pulled", "")
            return ("pull_failed", reset_err.decode()[:300])

        # Optional tidy: drop untracked files/dirs left over from a previous
        # clone (e.g. editor swap files). Safe because we just reset to
        # upstream HEAD — nothing local is expected.
        proc_clean = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "clean", "-fd",
            stdout=PIPE, stderr=PIPE,
        )
        await proc_clean.communicate()
        return ("pulled", "")

    if os.path.isdir(app_dir):
        # Squatting defence: path exists but has no `.git` subdir.
        # I-FIRSTPARTY-ADMIN-ONLY-CLAIM: when an admin re-deploys a
        # system first-party extension, back up the legacy hand-deployed
        # copy and continue to clone. For any other caller — refuse, so
        # a third-party who registered a clashing app_id can never
        # silently swap a first-party directory.
        if caller_role == "admin" and app_id in FIRSTPARTY_APP_IDS:
            import time as _time
            import tarfile as _tarfile
            os.makedirs(FIRSTPARTY_BACKUP_DIR, exist_ok=True)
            ts = int(_time.time())
            backup_path = os.path.join(FIRSTPARTY_BACKUP_DIR, f"{app_id}.{ts}.tar.gz")
            try:
                with _tarfile.open(backup_path, "w:gz") as tf:
                    tf.add(app_dir, arcname=os.path.basename(app_dir))
                shutil.rmtree(app_dir)
                log.info(
                    "I-FIRSTPARTY-ADMIN-ONLY-CLAIM: backed up %s to %s before clone",
                    app_dir, backup_path,
                )
            except (OSError, _tarfile.TarError) as exc:
                return ("backup_failed",
                        f"Failed to back up legacy {app_dir} -> {backup_path}: {exc}")
        else:
            return ("squatting_refused",
                    f"/opt/extensions/{os.path.basename(app_dir)} is already occupied by "
                    f"a non-developer-portal extension (no .git dir); refusing to deploy. "
                    f"Contact platform admin if you believe this is your app.")

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", git_url, app_dir,
        stdout=PIPE, stderr=PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        return ("clone_failed", stderr.decode()[:300])
    return ("cloned", "")


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
            pass  # Already exists — OK
        else:
            log.warning(f"Registry: failed to ensure app '{app_id}': {e}")


# ---------------------------------------------------------------------------
# Skeleton-section derivation (pure, testable, reused by backfill script)
# ---------------------------------------------------------------------------

_SKELETON_REFRESH_PREFIX = "skeleton_refresh_"
_SKELETON_ALERT_PREFIX = "skeleton_alert_"


def _derive_skeleton_sections_from_ext(ext) -> list[dict]:
    """Derive Registry skeleton_sections payload from a loaded Extension.

    Two-source derivation so both styles produce Registry rows:

      (A) Primary — ``@ext.skeleton(section_name, alert=…, ttl=…)`` decorator
          metadata stashed on ``ToolDef._skeleton`` (SDK 1.5.22+).
      (B) Fallback — naming convention: any tool named
          ``skeleton_refresh_<X>`` becomes a section. A sibling
          ``skeleton_alert_<X>`` tool enables ``alert_on_change=True``.

    The output shape matches what Registry ``POST /v1/apps/{app_id}/tools``
    expects — see ``/home/imperal-registry/v1/tools.py::replace_tools``
    which reads ``body.skeleton_sections[i]["name"]`` into the
    ``app_skeleton_config.section_name`` column. Intentionally uses the
    key ``name`` (not ``section_name``).

    Pure function — no I/O, no Registry calls. Exercised by
    ``tests/test_skeleton_sync.py`` and
    ``/home/imperal-platform-worker/scripts/backfill_portal_skeleton_sections.py``.

    Invariants touched:
      - I-SKEL-AUTO-DERIVE-1 (kernel-side mirror of convention (B))
      - I-PURGE-SKELETON-SCOPE (section_name format constraints)
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

    Auto-creates app in Registry if it doesn't exist yet (handles deploy-before-approve).
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

        # Skeleton sections via shared helper (see _derive_skeleton_sections_from_ext).
        # Kernel auto-derive is still a safety net but Registry is now
        # source-of-truth for portal-deployed extensions.
        skeleton = _derive_skeleton_sections_from_ext(ext)

        # Ensure app exists in Registry (idempotent — 409 on duplicate is OK)
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
    """GAP-9: After deploy, write ``config.ui.panels`` into Auth GW unified_config
    so the extension page ``/ext/{app_id}`` renders left/right panels instead of
    blank. Reads decorated ``@ext.panel`` declarations from the loaded extension
    (slot, title, icon) and PUTs them under scope=``app``, scope_id=``app_id``.

    Returns True if panels were found + PUT succeeded. False if extension has
    no panels (nothing to sync) or PUT failed (logged, non-blocking).
    """
    try:
        sys.path.insert(0, app_dir)
        from imperal_kernel.core.loader import ExtensionLoader
        loader = ExtensionLoader(EXTENSIONS_DIR)
        ext = loader.load(app_id)

        # SDK ALLOWED_PANEL_SLOTS: left, right, center, bottom, overlay, chat-sidebar.
        # Previously this loop hardcoded ('left', 'right') and silently dropped
        # any extension's center/bottom/overlay panels — they'd never show up
        # in the Imperal Panel UI even though the extension registered them.
        from imperal_sdk.types.contributions import ALLOWED_PANEL_SLOTS

        panels_by_slot: dict[str, tuple[str, dict]] = {}
        for name, meta in (ext.panels or {}).items():
            slot = meta.get("slot", "")
            if slot in ALLOWED_PANEL_SLOTS and slot not in panels_by_slot:
                panels_by_slot[slot] = (name, meta)

        if not panels_by_slot:
            return False  # no panels declared — nothing to sync

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
            # Forward width hints + center_overlay flag (federal v4.1.8 —
            # replaces hardcoded TS isCenterOverlay allowlist).
            for k in ("default_width", "min_width", "max_width"):
                if k in meta:
                    entry[k] = meta[k]
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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
@chat.function("deploy_app", action_type="write",
               description="Clone or pull extension from Git, validate, and report results")
async def deploy_app(ctx, params: DeployParams) -> ActionResult:
    uid = _user_id(ctx)
    app_id = params.app_id

    try:
        app_info = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as e:
        return ActionResult.error(f"App not found: {e}")

    git_url = app_info.get("git_url", "")
    if not git_url.startswith("https://"):
        return ActionResult.error("git_url must start with https://")

    app_dir = os.path.join(EXTENSIONS_DIR, app_id)

    # I-FIRSTPARTY-ADMIN-ONLY-CLAIM: thread caller role + app_id so the
    # squat-refuse path can admin-bypass for first-party app_ids.
    caller_role = getattr(ctx.user, "role", "developer")

    # Clone or pull
    action, error = await _git_pull_or_clone(
        app_dir, git_url, caller_role=caller_role, app_id=app_id,
    )

    if action == "backup_failed":
        return ActionResult.error(error)
    if action == "squatting_refused":
        # App-ID squatting defence. Do NOT record a deploy row — the attacker
        # never reached git, and we don't want to pollute the audit log.
        log.warning("squatting_refused uid=%s app_id=%s reason=%s", uid, app_id, error)
        return ActionResult.error(error, retryable=False)
    if action in ("clone_failed", "pull_failed"):
        await _record_deploy(uid, app_id, "000000", "failed", error)
        return ActionResult.error(f"Git {action.replace('_', ' ')}: {error}")

    # Commit SHA
    sha_proc = await asyncio.create_subprocess_exec(
        "git", "-C", app_dir, "rev-parse", "HEAD", stdout=PIPE,
    )
    sha_out, _ = await sha_proc.communicate()
    commit_sha = sha_out.decode().strip()[:40]

    # Clear __pycache__
    for root, dirs, _ in os.walk(app_dir):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)

    # Replay kernel-side migrations against the freshly-checked-out working
    # tree. Closes the inner-git drift gap documented in
    # ``feedback_devportal_migration_drift_open_gap.md``: previously,
    # kernel-side reformats (imperal.json normalization, E8 scope rename,
    # auto-identity) wrote directly to /opt/extensions/<app> but never
    # round-tripped back to the portal's git origin, so `git reset --hard
    # origin/main` would roll them back.
    #
    # Invariant I-PORTAL-REPLAY-1. Failure policy: log + continue — a
    # regression in one migration MUST NOT block the deploy pipeline.
    migrations_applied: list[str] = []
    try:
        from pathlib import Path as _Path
        from imperal_kernel.migrations.extensions import replay as _replay_ext_migrations
        migrations_applied = await _replay_ext_migrations(_Path(app_dir), app_id)
        if migrations_applied:
            log.info(
                "Portal deploy: replayed %d kernel migrations for %s: %s",
                len(migrations_applied), app_id, migrations_applied,
            )
    except Exception as mig_exc:
        log.error(
            "Portal deploy: migration replay failed for %s: %s",
            app_id, mig_exc,
        )

    # Fix app_id in imperal.json if mismatched (before validation).
    # Capture the mismatch for a non-blocking warning in the validation
    # report — a future release will convert this to a hard reject (repo
    # must be the source of truth for app_id).
    manifest_path = os.path.join(app_dir, "imperal.json")
    manifest_app_id_mismatch = None
    try:
        with open(manifest_path) as mf:
            m = json.load(mf)
        if m.get("app_id") != app_id:
            manifest_app_id_mismatch = m.get("app_id", "<missing>")
            m["app_id"] = app_id
            with open(manifest_path, "w") as mf:
                json.dump(m, mf, indent=2)
    except Exception:
        pass

    # Deep validation: static (6 checks) + runtime (R1-R10 incl. identity)
    report = await validate_extension_full(app_dir)
    checks = report["checks"]
    passed = report["passed"]
    total = report["total"]
    deploy_status = report["status"]

    # On critical failure, revert code
    if deploy_status == "failed":
        critical = [c for c in checks if not c.get("passed") and c.get("name") == "syntax"]
        if critical:
            await asyncio.create_subprocess_exec(
                "git", "-C", app_dir, "checkout", ".", stdout=PIPE, stderr=PIPE)

    # Map status names for DB
    db_status = {"passed": "success", "warning": "warning", "failed": "failed"}

    # Record deploy with full validation JSON
    validation_json = json.dumps({
        "checks": checks, "passed": passed, "total": total,
    })
    await _record_deploy(uid, app_id, commit_sha, db_status.get(deploy_status, deploy_status), validation_json)

    # Auto-sync tools to Registry (on success or warning — NOT on failure)
    tools_synced = 0
    panels_synced = False
    if deploy_status in ("passed", "warning"):
        tools_synced = await _sync_tools_to_registry(app_id, app_dir, owner_id=uid)
        # GAP-9: populate config.ui.panels so /ext/{app_id} doesn't render blank.
        panels_synced = await _sync_panel_config_to_unified_config(app_id, app_dir)

    # Emit manifest_app_id_mismatch warning if detected above. Non-blocking:
    # platform auto-fixed for this deploy. Future releases will reject.
    if manifest_app_id_mismatch is not None:
        checks.append({
            "name": "manifest_app_id_mismatch",
            "passed": False,
            "severity": "warning",
            "message": (
                f"imperal.json in your repo has app_id='{manifest_app_id_mismatch}', "
                f"but your app is registered as '{app_id}'. Platform auto-fixed "
                f"this deploy. Please set app_id='{app_id}' in imperal.json, "
                f"commit, and push. Future releases will reject mismatches."
            ),
        })
        total += 1
        if deploy_status == "passed":
            deploy_status = "warning"

    # R11: Registry sync verification
    from validate_checks_deploy import check_registry_sync
    registry_check = check_registry_sync(app_id, tools_synced)
    checks.append(registry_check)
    total += 1
    if registry_check["passed"]:
        passed += 1
    elif registry_check.get("severity") == "critical" and deploy_status == "passed":
        deploy_status = "warning"

    # Chat summary: short line + LLM report for debugging
    status_word = {"passed": "deployed", "warning": "deployed with warnings", "failed": "failed"}
    llm_report = report.get("llm_report", "")
    summary = (
        f"{app_id} {action} at {commit_sha[:8]} — "
        f"{status_word.get(deploy_status, deploy_status)} "
        f"({passed}/{total} checks)."
    )
    if tools_synced:
        summary += f" {tools_synced} tools registered in catalog."
    if panels_synced:
        summary += " Panel config synced to unified_config."
    if migrations_applied:
        summary += f" Migrations replayed: {len(migrations_applied)}."
    if deploy_status == "failed" and llm_report:
        summary += "\n\n" + llm_report
    elif deploy_status == "warning" and llm_report:
        summary += " See Deploy tab for details."

    return ActionResult.success(
        data={"app_id": app_id, "commit": commit_sha[:8], "status": deploy_status,
              "validation": f"{passed}/{total}", "tools_synced": tools_synced,
              "panels_synced": panels_synced,
              "migrations_applied": migrations_applied},
        summary=summary,
    )


@chat.function("submit_for_review", action_type="write",
               description="Submit app for admin review")
async def submit_for_review(ctx, params: SubmitParams) -> ActionResult:
    uid = _user_id(ctx)
    try:
        result = await _gw_post(f"/v1/developer/apps/{params.app_id}/submit", {"user_id": uid})
        if result.get("status") == "failed":
            checks = result.get("checks", [])
            failed = [c["check"] for c in checks if not c.get("ok") and not c.get("passed")]
            return ActionResult.error(f"Submission failed — fix: {', '.join(failed)}")
        return ActionResult.success(data=result, summary=f"App '{params.app_id}' submitted for review.")
    except Exception as e:
        return ActionResult.error(f"Failed to submit: {e}")
