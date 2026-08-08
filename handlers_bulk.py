"""Developer · bulk app operations.

A developer with a portfolio works in the plural: "deploy all three",
"pause everything while I fix the billing bug", "submit both for review".
Before this module every one of those meant calling a single-app tool N
times -- N confirmation gates, N round trips, and a single mistyped app_id
aborting the whole intent.

Every handler here follows the same contract:

  * app names are resolved FIRST against the developer's OWN app list, so
    partials and display names work ('analytics' -> 'matomo-analytics') and
    a typo is reported as a typo instead of a confusing gateway 404;
  * duplicates collapse on the RESOLVED app_id, so naming one app twice
    deploys it once;
  * partial success is reported as SUCCESS with per-app detail -- work that
    completed is never hidden behind an error;
  * the real single-app handlers do the actual work. Deploy in particular
    carries git validation, HEAD capture and rollback-on-failure; a second
    implementation here would be the perfect way to ship a subtly different,
    unvalidated deploy path.

Deliberately NOT bulk: delete_app. Permanent deletion requires typing the
exact app_id per app as its confirmation, and that per-app friction is the
entire safety mechanism -- batching it away would be a footgun, not a
feature.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import chat, _gw_get, _user_id

log = logging.getLogger("developer.handlers_bulk")

_MAX_APPS = 25


# ─── Models ───────────────────────────────────────────────────────────── #

class BulkAppsParams(BaseModel):
    """Target SEVERAL of your own apps at once."""
    app_ids: list[str] = Field(
        description=(
            "The apps to act on — exact app_ids, display names, or partials "
            "of either; each is resolved against YOUR apps. Pass EVERY app "
            "the user named in ONE call; do not loop. "
            "Example: ['matomo-analytics', 'article-writer']."
        ),
        min_length=1,
        max_length=_MAX_APPS,
    )


class BulkAppReceipt(BaseModel):
    """Uniform outcome shape for every bulk developer action."""
    model_config = {"extra": "allow"}

    action: str = ""
    succeeded: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    total: int = 0
    success_count: int = 0
    failure_count: int = 0


# ─── Shared plumbing ──────────────────────────────────────────────────── #

def _norm(s) -> str:
    return "".join(c for c in str(s or "").lower() if c.isalnum())


async def _resolve_apps(ctx, raw: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve every name against the developer's OWN apps.

    Returns ``(resolved, failures)`` where resolved is ``(term, app_id)``.
    De-dupes on the RESOLVED app_id so one app named two ways acts once.

    Resolution is exact-id, then exact-name, then unique-substring. An
    ambiguous partial is reported with its candidates rather than guessed:
    silently deploying the wrong app is far worse than asking.
    """
    uid = _user_id(ctx)
    try:
        apps = await _gw_get(f"/v1/developer/apps?user_id={uid}")
    except Exception as exc:                                   # noqa: BLE001
        log.warning("bulk: app list failed: %s", exc)
        return [], [f"could not load your app list ({type(exc).__name__})"]

    if not isinstance(apps, list):
        apps = []

    def _aid(a: dict) -> str:
        return a.get("app_id") or a.get("id") or ""

    def _name(a: dict) -> str:
        return a.get("display_name") or a.get("name") or ""

    resolved: list[tuple[str, str]] = []
    failures: list[str] = []
    seen: set[str] = set()

    for term in raw:
        t = _norm(term)
        if not t:
            continue
        hit = None
        for a in apps:                                   # 1. exact app_id
            if _norm(_aid(a)) == t:
                hit = _aid(a)
                break
        if hit is None:                                  # 2. exact name
            for a in apps:
                if _norm(_name(a)) == t:
                    hit = _aid(a)
                    break
        if hit is None:                                  # 3. unique partial
            cands = [
                a for a in apps
                if t in _norm(_aid(a)) or t in _norm(_name(a))
            ]
            uniq = {_aid(c) for c in cands if _aid(c)}
            if len(uniq) == 1:
                hit = next(iter(uniq))
            elif uniq:
                names = ", ".join(sorted(uniq)[:4])
                failures.append(f"{term} — ambiguous ({names})")
                continue

        if hit is None:
            failures.append(f"{term} — not one of your apps")
            continue
        if hit in seen:
            continue
        seen.add(hit)
        resolved.append((term, hit))

    return resolved, failures


def _receipt(action: str, ok: list[str], failed: list[str], **extra) -> ActionResult:
    """One uniform shape + honest summary for every bulk developer action."""
    data = {
        "action": action,
        "succeeded": ok,
        "failed": failed,
        "total": len(ok) + len(failed),
        "success_count": len(ok),
        "failure_count": len(failed),
        **extra,
    }
    if ok and not failed:
        summary = f"{action} {len(ok)}: {', '.join(ok)}."
    elif ok and failed:
        summary = (
            f"{action} {len(ok)} ({', '.join(ok)}); "
            f"{len(failed)} failed — {'; '.join(failed)}."
        )
    else:
        summary = f"Nothing done — {'; '.join(failed) or 'no apps matched'}."

    # Partial success is still success: the caller must see what DID happen.
    # Collapsing it into an error is how completed work gets repeated.
    if not ok:
        return ActionResult.error(summary)
    return ActionResult.success(
        data=data,
        summary=summary,
        refresh_panels=["sidebar", "dashboard"],
    )


async def _run_each(ctx, targets, runner, params_factory):
    """Apply one single-app handler across resolved targets."""
    ok: list[str] = []
    failures: list[str] = []
    for term, app_id in targets:
        try:
            res = await runner(ctx, params_factory(app_id))
            if getattr(res, "status", "success") == "error" or getattr(res, "error", None):
                failures.append(f"{term} — {getattr(res, 'error', 'failed')}")
            else:
                ok.append(app_id)
        except Exception as exc:                               # noqa: BLE001
            log.warning("bulk op on %s: %s", app_id, exc)
            failures.append(f"{term} — {str(exc)[:120]}")
    return ok, failures


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function(
    "bulk_deploy_apps",
    action_type="write",
    effects=["update:app"],
    data_model=BulkAppReceipt,
    description=(
        "Deploy SEVERAL of your apps in one call (git clone/pull + validate "
        "each). Use whenever the user names more than one app to deploy, or "
        "says 'deploy all my apps' / 'redeploy both'."
    ),
)
async def fn_bulk_deploy_apps(ctx, params: BulkAppsParams) -> ActionResult:
    """Deploy many apps, reporting per-app outcomes."""
    targets, failures = await _resolve_apps(ctx, params.app_ids)
    # Reuse the real deploy handler: it owns git validation, HEAD capture and
    # rollback-on-failure. Reimplementing it here would create a second,
    # unvalidated deploy path.
    from handlers_deploy import DeployParams, deploy_app

    ok, more = await _run_each(
        ctx, targets, deploy_app, lambda a: DeployParams(app_id=a),
    )
    return _receipt("Deployed", ok, failures + more)


@chat.function(
    "bulk_suspend_apps",
    action_type="write",
    effects=["update:app_status"],
    data_model=BulkAppReceipt,
    description=(
        "Pause/suspend SEVERAL of your apps at once — takes them off the "
        "Marketplace so pricing can be edited. Use for 'pause all my apps', "
        "'suspend these two'."
    ),
)
async def fn_bulk_suspend_apps(ctx, params: BulkAppsParams) -> ActionResult:
    """Suspend many apps, reporting per-app outcomes."""
    targets, failures = await _resolve_apps(ctx, params.app_ids)
    from handlers import SuspendParams, suspend_app

    ok, more = await _run_each(
        ctx, targets, suspend_app, lambda a: SuspendParams(app_id=a),
    )
    return _receipt("Paused", ok, failures + more)


@chat.function(
    "bulk_submit_for_review",
    action_type="write",
    effects=["update:app_status"],
    data_model=BulkAppReceipt,
    description=(
        "Submit SEVERAL of your apps for Marketplace review in one call. "
        "Use for 'publish both', 'submit all my drafts for review'."
    ),
)
async def fn_bulk_submit_for_review(ctx, params: BulkAppsParams) -> ActionResult:
    """Submit many apps for review, reporting per-app outcomes.

    A failing validation check on one app is reported for that app only --
    the others still go through.
    """
    targets, failures = await _resolve_apps(ctx, params.app_ids)
    from handlers_submit import SubmitParams, submit_for_review

    ok, more = await _run_each(
        ctx, targets, submit_for_review, lambda a: SubmitParams(app_id=a),
    )
    return _receipt("Submitted", ok, failures + more)
