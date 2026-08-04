"""Deploy must go live on the WHOLE fleet without restarting workers.

Three defects made a Dev Portal deploy need a manual rolling restart, all
observed live on 2026-08-04 (8 deploys of wp-site-connector, plus gemini,
admin, media-studio, automations):

1. No fleet signal. The syncs run inside ONE worker. That worker re-loads the
   app (the loader re-reads an extension whose files changed), but its siblings
   kept serving the code already in memory -- so which version a user got
   depended on which worker answered. Every worker subscribes to
   ``imperal:catalog`` (worker_main catalog_listener) and on a signal re-runs
   catalog.load() + publish_event_catalog(), which re-walks every extension on
   disk. The IR deploy path already published that signal
   (registration.register_ir_app, I-IR-REGISTER-CATALOG-SIGNAL); the git path
   -- the one Dev Portal actually uses -- never did.

2. sys.path leak. Both sync helpers did ``sys.path.insert(0, app_dir)`` with no
   matching remove and no try/finally, so every deploy prepended another entry
   permanently (measured: 3 entries after two loads). Since sys.path is ordered
   most-recently-loaded-first, a LATER extension's bare ``import models`` could
   then resolve to an EARLIER app's models.py -- cross-extension bleed. The
   kernel loader resolves an extension's own modules by explicit path under an
   ext-unique namespace, so it never needed app_dir on sys.path at all.

3. Opaque failure. ``loader.load()`` returns None when the loader REJECTED the
   app; reaching straight for ``ext.tools`` raised "'NoneType' object has no
   attribute 'tools'", which named neither the app nor the real reason.

These are contract tests: they assert the SHAPE of the deploy path, so the
behaviour cannot silently regress. Source inspection is the established idiom
for handlers too heavy to invoke (mirrors the kernel's
test_v5_catalog_listener_reindex.py).
"""
import inspect
import re

import deploy_sync
import handlers_deploy


def _deploy_src() -> str:
    return inspect.getsource(handlers_deploy)


# --------------------------------------------------------------- fleet signal
def test_git_deploy_publishes_catalog_signal():
    """Without this the fleet keeps serving stale code until a manual restart."""
    src = _deploy_src()
    assert "imperal:catalog" in src, (
        "the git deploy path must publish the imperal:catalog refresh signal, "
        "otherwise only the worker that handled the deploy runs the new code "
        "and the operator has to restart the fleet by hand"
    )
    assert "get_shared_redis" in src, (
        "publish the signal through the kernel's shared redis helper "
        "(imperal_kernel.core.redis.get_shared_redis), as register_ir_app does"
    )


def test_catalog_signal_is_best_effort():
    """The app is already deployed — a Redis hiccup must not fail the deploy."""
    src = _deploy_src()
    # Anchor on the CALL, not the word: the surrounding comment explains the
    # invariant and would otherwise match first.
    idx = src.index('publish("imperal:catalog"')
    window = src[max(0, idx - 300):idx + 400]
    assert "try:" in window and "except" in window, (
        "the catalog publish must be wrapped in try/except: at that point the "
        "deploy has SUCCEEDED, so a signalling failure must never fail it"
    )


def test_signal_only_after_a_successful_deploy():
    """A failed/rejected deploy must not tell the fleet to pick anything up."""
    src = _deploy_src()
    sig_at = src.index('publish("imperal:catalog"')
    gate = src.rindex('deploy_status in ("passed", "warning")', 0, sig_at)
    # The signal must sit inside the success branch, after the syncs.
    assert gate < sig_at, (
        "the catalog signal must fire only when deploy_status is passed or "
        "warning — never for a rejected deploy"
    )
    sync_at = src.index("_sync_tools_to_registry(app_id", gate)
    assert sync_at < sig_at, (
        "signal the fleet only AFTER the registry/panel syncs, so a reloading "
        "worker sees consistent state"
    )


# ------------------------------------------------------------- sys.path leak
def test_sync_helpers_do_not_mutate_sys_path():
    """A leaked entry makes a later ext's bare import hit an earlier ext's file."""
    src = inspect.getsource(deploy_sync)
    offenders = re.findall(r"^\s*sys\.path\.(insert|append)\(", src, re.M)
    assert offenders == [], (
        f"deploy_sync must not put app_dir on sys.path ({len(offenders)} call(s) "
        "found): there is no matching remove, so every deploy grows sys.path "
        "permanently and later extensions can resolve bare imports to an "
        "earlier app's same-named module. The loader resolves an extension's "
        "own modules by explicit path — it needs no sys.path help."
    )


# ---------------------------------------------------- rejected app is honest
def test_sync_helpers_handle_a_rejected_extension():
    """loader.load() returns None for a rejected app — say so, don't crash."""
    for fn in (deploy_sync._sync_tools_to_registry,
               deploy_sync._sync_panel_config_to_unified_config):
        src = inspect.getsource(fn)
        assert "is None" in src, (
            f"{fn.__name__} must check the loaded extension for None. "
            "loader.load() returns None when the loader rejected the app "
            "(app_id mismatch, sdk too old); reaching for ext.tools then "
            "raised \"'NoneType' object has no attribute 'tools'\", naming "
            "neither the app nor the real reason."
        )
        assert "DISABLED_REASONS" in src, (
            f"{fn.__name__} should report WHY the app was rejected "
            "(loader.DISABLED_REASONS), so the operator sees the real cause"
        )


def test_load_is_called_before_touching_tools():
    """Guards the ordering the NoneType crash came from."""
    src = inspect.getsource(deploy_sync._sync_tools_to_registry)
    load_at = src.index("loader.load(app_id)")
    # The literal guard, not the words "is None" in the explanatory comment.
    none_at = src.index("if ext is None:")
    tools_at = src.index("ext.tools.items()")
    assert load_at < none_at < tools_at, (
        "the None check must sit between loading the extension and using "
        "ext.tools"
    )
