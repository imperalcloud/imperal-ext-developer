"""Developer Portal — deploy & submit handlers (split from handlers.py).

Slim handler module: only @chat.function entries. Implementation details:

  - deploy_git.py    — git clone/pull + first-party squat-defence
  - deploy_sync.py   — Registry + unified_config sync, skeleton derivation
  - validation.py    — phase-1 static checks
  - validation_runtime.py — phase-2 runtime checks (R1-R12)
  - validation_report.py  — phase-3 merge + LLM-friendly report
"""
import asyncio
import json
import os
import shutil
import sys
import logging

from pydantic import BaseModel, Field
from imperal_sdk.chat import ActionResult

from app import chat, _gw_get, _gw_post, _user_id, EXTENSIONS_DIR
from validation import validate_extension_full
from deploy_git import _git_pull_or_clone
from deploy_sync import (
    _record_deploy,
    _sync_tools_to_registry,
    _sync_panel_config_to_unified_config,
)

log = logging.getLogger("developer")
PIPE = asyncio.subprocess.PIPE

# Make scripts importable for R11 check
sys.path.insert(0, "/home/imperal-platform-worker/scripts")


class DeployParams(BaseModel):
    app_id: str = Field(..., description="App to deploy")


class SubmitParams(BaseModel):
    app_id: str = Field(..., description="App to submit for review")


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

    action, error = await _git_pull_or_clone(
        app_dir, git_url, caller_role=caller_role, app_id=app_id,
    )

    if action == "backup_failed":
        return ActionResult.error(error)
    if action == "squatting_refused":
        log.warning("squatting_refused uid=%s app_id=%s reason=%s", uid, app_id, error)
        return ActionResult.error(error, retryable=False)
    if action in ("clone_failed", "pull_failed"):
        await _record_deploy(uid, app_id, "000000", "failed", error)
        return ActionResult.error(f"Git {action.replace('_', ' ')}: {error}")

    sha_proc = await asyncio.create_subprocess_exec(
        "git", "-C", app_dir, "rev-parse", "HEAD", stdout=PIPE,
    )
    sha_out, _ = await sha_proc.communicate()
    commit_sha = sha_out.decode().strip()[:40]

    for root, dirs, _ in os.walk(app_dir):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)

    # Replay kernel-side migrations against the freshly-checked-out tree.
    # Closes the inner-git drift gap from
    # ``feedback_devportal_migration_drift_open_gap.md``: previously,
    # kernel-side reformats wrote directly to /opt/extensions/<app> but
    # never round-tripped back to the portal's git origin, so
    # `git reset --hard origin/main` would roll them back.
    # Invariant I-PORTAL-REPLAY-1. Failure policy: log + continue.
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
    # report — a future release will convert this to a hard reject.
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

    db_status = {"passed": "success", "warning": "warning", "failed": "failed"}

    validation_json = json.dumps({
        "checks": checks, "passed": passed, "total": total,
    })
    await _record_deploy(uid, app_id, commit_sha, db_status.get(deploy_status, deploy_status), validation_json)

    tools_synced = 0
    panels_synced = False
    icon_synced = False
    manifest_synced = False
    if deploy_status in ("passed", "warning"):
        tools_synced = await _sync_tools_to_registry(app_id, app_dir, owner_id=uid)
        panels_synced = await _sync_panel_config_to_unified_config(app_id, app_dir)
        # B-icon-db (2026-05-11): persist icon.svg into developer_apps.icon_svg
        # so the marketplace + sidebar can render it via
        # GET /v1/marketplace/apps/{app_id}/icon (proxied through Next.js
        # /api/extensions/{appId}/icon.svg). DB is the single source of
        # truth — no filesystem sync between hosts. Failure here is
        # non-fatal: the deploy still succeeded; icon just won't render
        # until the next deploy retries.
        icon_path = os.path.join(app_dir, "icon.svg")
        if os.path.isfile(icon_path):
            try:
                with open(icon_path, "r", encoding="utf-8") as _icf:
                    _icon_bytes = _icf.read()
                # Bound the payload — federal manifests cap icons at ~64KB.
                if 0 < len(_icon_bytes) <= 65536:
                    _res = await _gw_post(
                        f"/v1/developer/apps/{app_id}/_sync_manifest",
                        {"icon_svg": _icon_bytes},
                    )
                    icon_synced = bool(_res.get("updated"))
            except Exception as _icx:
                log.warning(
                    "B-icon-db sync failed for %s (non-fatal): %s",
                    app_id, _icx,
                )

        # EXT-SECRETS-V1 (2026-05-13): persist full imperal.json into
        # developer_apps.manifest_json so /v1/secrets/* router can read
        # secrets[] for I-SECRETS-CONTRACT-DECLARED enforcement. Without
        # this sync, ctx.secrets.get() against any newly-deployed ext
        # would 404 with SECRET_NOT_DECLARED even when the manifest
        # declared the name. Non-fatal — deploy still succeeds.
        manifest_path = os.path.join(app_dir, "imperal.json")
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as _mfp:
                    _manifest_blob = _mfp.read()
                # Soft sanity cap — auth-gw enforces 1 MB ceiling.
                if 0 < len(_manifest_blob) <= 1_048_576:
                    _res = await _gw_post(
                        f"/v1/developer/apps/{app_id}/_sync_manifest",
                        {"manifest_json": _manifest_blob},
                    )
                    manifest_synced = bool(_res.get("updated"))
            except Exception as _mfx:
                log.warning(
                    "EXT-SECRETS-V1 manifest_json sync failed for %s "
                    "(non-fatal): %s",
                    app_id, _mfx,
                )

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
    if icon_synced:
        summary += " Icon synced to DB."
    if manifest_synced:
        summary += " Manifest synced to DB (secrets[] available)."
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
              "icon_synced": icon_synced,
              "manifest_synced": manifest_synced,
              "migrations_applied": migrations_applied},
        summary=summary,
    refresh_panels=["sidebar", "dashboard"],
    )


@chat.function("submit_for_review", action_type="write",
               description="Submit app for admin review")
async def submit_for_review(ctx, params: SubmitParams) -> ActionResult:
    from app import _gw_post
    uid = _user_id(ctx)
    try:
        result = await _gw_post(f"/v1/developer/apps/{params.app_id}/submit", {"user_id": uid})
        if result.get("status") == "failed":
            checks = result.get("checks", [])
            failed = [c["check"] for c in checks if not c.get("ok") and not c.get("passed")]
            return ActionResult.error(f"Submission failed — fix: {', '.join(failed)}")
        return ActionResult.success(data=result, summary=f"App '{params.app_id}' submitted for review.", refresh_panels=["sidebar", "dashboard"])
    except Exception as e:
        return ActionResult.error(f"Failed to submit: {e}")
