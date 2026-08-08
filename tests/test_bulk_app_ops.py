"""Functional tests for developer bulk app operations.

A developer with a portfolio works in the plural ("deploy all three",
"pause everything while I fix the bug"). These tests pin the properties
that make such a tool trustworthy rather than merely present:

  * every named app is acted on -- not just the first;
  * names resolve against the developer's OWN apps, so partials and display
    names work and a typo is reported as a typo;
  * duplicates collapse on the RESOLVED app_id (naming one app twice must
    not deploy it twice);
  * one bad name does not cancel the rest, and partial success is still a
    success result carrying per-app detail;
  * the real single-app handler does the work. Deploy carries git
    validation, HEAD capture and rollback-on-failure -- a bulk path that
    reimplemented it would be an unvalidated second deploy path.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handlers_bulk as hb  # noqa: E402

from imperal_sdk.chat import ActionResult  # noqa: E402


# ─── fixtures ─────────────────────────────────────────────────────────── #

MY_APPS = [
    {"app_id": "matomo-analytics", "display_name": "Matomo Analytics",
     "status": "active"},
    {"app_id": "meta-social", "display_name": "Meta Social", "status": "draft"},
    {"app_id": "mail-client", "display_name": "Mail Client", "status": "active"},
]


class _Ctx:
    """Minimal ctx: the handlers only need a user id off it."""

    class user:
        imperal_id = "imp_u_DEVELOPER1"
        id = "imp_u_DEVELOPER1"
        role = "developer"


@pytest.fixture
def ctx():
    return _Ctx()


def _patch_apps(monkeypatch, apps=None, fail=False):
    """Stub the developer's own app list (the resolution source)."""
    async def _get(path):
        if fail:
            raise RuntimeError("apps service unreachable")
        return MY_APPS if apps is None else apps

    monkeypatch.setattr(hb, "_gw_get", _get)
    monkeypatch.setattr(hb, "_user_id", lambda ctx: "imp_u_DEVELOPER1")


class _CallSpy:
    """Records each single-app call the bulk handler delegates to."""

    def __init__(self, failing: set[str] | None = None):
        self.failing = failing or set()
        self.calls: list[str] = []

    async def __call__(self, ctx, params):
        self.calls.append(params.app_id)
        if params.app_id in self.failing:
            return ActionResult.error(f"{params.app_id} exploded")
        return ActionResult.success(data={"app_id": params.app_id}, summary="ok")


def _patch_deploy(monkeypatch, spy):
    import handlers_deploy
    monkeypatch.setattr(handlers_deploy, "deploy_app", spy)


def _patch_suspend(monkeypatch, spy):
    import handlers
    monkeypatch.setattr(handlers, "suspend_app", spy)


def _patch_submit(monkeypatch, spy):
    import handlers_submit
    monkeypatch.setattr(handlers_submit, "submit_for_review", spy)


# ─── deploy ───────────────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_bulk_deploy_hits_every_named_app(ctx, monkeypatch):
    _patch_apps(monkeypatch)
    spy = _CallSpy()
    _patch_deploy(monkeypatch, spy)

    res = await hb.fn_bulk_deploy_apps(
        ctx, hb.BulkAppsParams(app_ids=["matomo-analytics", "meta-social"]),
    )

    assert res.status == "success"
    assert spy.calls == ["matomo-analytics", "meta-social"], (
        f"every named app must be deployed, got {spy.calls}"
    )


@pytest.mark.asyncio
async def test_bulk_deploy_delegates_instead_of_reimplementing(ctx, monkeypatch):
    """Deploy MUST go through the real handler (git validation + rollback)."""
    _patch_apps(monkeypatch)
    spy = _CallSpy()
    _patch_deploy(monkeypatch, spy)

    await hb.fn_bulk_deploy_apps(
        ctx, hb.BulkAppsParams(app_ids=["mail-client"]),
    )

    assert spy.calls == ["mail-client"], (
        "bulk deploy must call the validated single-app deploy path"
    )


# ─── name resolution ──────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_a_partial_name_resolves_to_the_real_app_id(ctx, monkeypatch):
    _patch_apps(monkeypatch)
    spy = _CallSpy()
    _patch_suspend(monkeypatch, spy)

    res = await hb.fn_bulk_suspend_apps(
        ctx, hb.BulkAppsParams(app_ids=["analytics"]),
    )

    assert spy.calls == ["matomo-analytics"], (
        f"'analytics' must resolve to the real app_id, got {spy.calls}"
    )
    assert res.status == "success"


@pytest.mark.asyncio
async def test_a_display_name_resolves_too(ctx, monkeypatch):
    _patch_apps(monkeypatch)
    spy = _CallSpy()
    _patch_suspend(monkeypatch, spy)

    await hb.fn_bulk_suspend_apps(
        ctx, hb.BulkAppsParams(app_ids=["Mail Client"]),
    )

    assert spy.calls == ["mail-client"]


@pytest.mark.asyncio
async def test_an_unknown_name_is_reported_not_silently_skipped(ctx, monkeypatch):
    _patch_apps(monkeypatch)
    spy = _CallSpy()
    _patch_suspend(monkeypatch, spy)

    res = await hb.fn_bulk_suspend_apps(
        ctx, hb.BulkAppsParams(app_ids=["matomo-analytics", "nope-not-real"]),
    )

    assert spy.calls == ["matomo-analytics"], "the good app must still be acted on"
    assert res.data["failure_count"] == 1
    blob = str(res.data["failed"])
    assert "nope-not-real" in blob, f"the bad name must be named back: {blob}"


# ─── de-duplication ───────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_naming_one_app_twice_acts_once(ctx, monkeypatch):
    """id + display name for the SAME app must not deploy it twice."""
    _patch_apps(monkeypatch)
    spy = _CallSpy()
    _patch_deploy(monkeypatch, spy)

    res = await hb.fn_bulk_deploy_apps(
        ctx,
        hb.BulkAppsParams(
            app_ids=["matomo-analytics", "Matomo Analytics", "analytics"],
        ),
    )

    assert spy.calls == ["matomo-analytics"], (
        f"one app named three ways must deploy ONCE, got {spy.calls}"
    )
    assert res.data["success_count"] == 1


# ─── partial success ──────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_one_failing_app_does_not_cancel_the_others(ctx, monkeypatch):
    _patch_apps(monkeypatch)
    spy = _CallSpy(failing={"meta-social"})
    _patch_deploy(monkeypatch, spy)

    res = await hb.fn_bulk_deploy_apps(
        ctx,
        hb.BulkAppsParams(
            app_ids=["matomo-analytics", "meta-social", "mail-client"],
        ),
    )

    assert spy.calls == ["matomo-analytics", "meta-social", "mail-client"], (
        "a failure mid-batch must not abort the remaining apps"
    )
    assert res.status == "success", "partial success stays a success result"
    assert res.data["success_count"] == 2
    assert res.data["failure_count"] == 1
    assert "meta-social" in str(res.data["failed"])


@pytest.mark.asyncio
async def test_every_app_failing_is_reported_as_an_error(ctx, monkeypatch):
    _patch_apps(monkeypatch)
    spy = _CallSpy(failing={"matomo-analytics", "mail-client"})
    _patch_deploy(monkeypatch, spy)

    res = await hb.fn_bulk_deploy_apps(
        ctx, hb.BulkAppsParams(app_ids=["matomo-analytics", "mail-client"]),
    )

    assert res.status == "error", "nothing succeeded — that is not a success"


# ─── submit for review ────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_bulk_submit_sends_every_app_to_review(ctx, monkeypatch):
    _patch_apps(monkeypatch)
    spy = _CallSpy()
    _patch_submit(monkeypatch, spy)

    res = await hb.fn_bulk_submit_for_review(
        ctx, hb.BulkAppsParams(app_ids=["meta-social", "mail-client"]),
    )

    assert spy.calls == ["meta-social", "mail-client"]
    assert res.data["success_count"] == 2


# ─── failure of the resolution source itself ──────────────────────────── #

@pytest.mark.asyncio
async def test_unreachable_app_list_says_so_instead_of_claiming_nothing_matched(
    ctx, monkeypatch,
):
    """A loading failure must not masquerade as 'no such app'."""
    _patch_apps(monkeypatch, fail=True)
    spy = _CallSpy()
    _patch_deploy(monkeypatch, spy)

    res = await hb.fn_bulk_deploy_apps(
        ctx, hb.BulkAppsParams(app_ids=["matomo-analytics"]),
    )

    assert res.status == "error"
    assert not spy.calls, "nothing may be deployed when the app list is unknown"
