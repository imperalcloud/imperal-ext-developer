"""Regression tests for the Developer Portal's skeleton-section derivation.

Guards the dual-source logic in
``handlers_deploy.py::_derive_skeleton_sections_from_ext``:

  (A) Primary   — ``@ext.skeleton(…)`` decorator metadata on
                  ``ToolDef._skeleton`` (SDK 1.5.22+).
  (B) Fallback  — naming convention: ``@ext.tool("skeleton_refresh_<X>")``
                  registers section ``<X>``; sibling
                  ``skeleton_alert_<X>`` enables ``alert_on_change=True``.

Also guards the Registry contract: output dict must use key ``name``
(not ``section_name``) because Registry INSERT reads
``body.skeleton_sections[i]["name"]`` into ``app_skeleton_config.section_name``.
See ``/home/imperal-registry/v1/tools.py::replace_tools`` for the authority.

R9 of the portal's own deploy pipeline will run this suite on every
self-deploy — the portal extension is not magically exempt.
"""
from __future__ import annotations

import os
import sys

# Make handlers_deploy.py importable (it lives alongside tests/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from imperal_sdk import Extension  # noqa: E402


def _load_helper():
    """Import helper lazily so the module import path matches the prod layout."""
    # handlers_deploy imports from `app` (extension runtime module). When the
    # test harness runs it under pytest, `app` isn't on the path. We mock just
    # enough to let handlers_deploy import, then reach for the helper.
    import types
    mock_app = types.ModuleType("app")
    async def _noop(*a, **k):  # pragma: no cover — never called by the helper
        return {}
    mock_app.chat = type("C", (), {"function": lambda *a, **k: lambda f: f})()
    mock_app._gw_get = _noop
    mock_app._gw_post = _noop
    mock_app._gw_put = _noop
    mock_app._registry_post = _noop
    mock_app._registry_put = _noop
    mock_app._user_id = _noop
    mock_app.EXTENSIONS_DIR = "/opt/extensions"
    sys.modules["app"] = mock_app

    # validation module is imported at top of handlers_deploy
    mock_val = types.ModuleType("validation")
    async def _noop2(*a, **k):
        return {"ok": True, "checks": [], "passed": 0, "total": 0}
    mock_val.validate_extension_full = _noop2
    sys.modules["validation"] = mock_val

    import handlers_deploy  # type: ignore
    return handlers_deploy._derive_skeleton_sections_from_ext


derive = _load_helper()


# ---------------------------------------------------------------------
# (A) Primary path — @ext.skeleton decorator metadata
# ---------------------------------------------------------------------

def test_ext_skeleton_decorator_produces_section():
    ext = Extension(app_id="web-tools", version="1.0.0")

    @ext.skeleton("web_tools")
    async def refresh_web_tools(ctx):
        return {"response": {"total": 0}}

    sections = derive(ext)
    assert len(sections) == 1
    s = sections[0]
    # Registry-contract key is "name", not "section_name"
    assert s["name"] == "web_tools"
    assert s["refresh_activity"] == "skeleton_refresh_web_tools"
    assert s["ttl"] == 300
    assert s["alert_on_change"] is False
    assert s.get("alert_activity") is None


def test_ext_skeleton_with_alert_flag_finds_sibling_tool():
    ext = Extension(app_id="notes", version="1.0.0")

    @ext.skeleton("notes", alert=True, ttl=60)
    async def refresh_notes(ctx):
        return {"response": {"total_notes": 41}}

    @ext.tool("skeleton_alert_notes", description="Notify on notes change")
    async def alert_notes(ctx, section_name, old, new, **kwargs):
        return {"response": {"acknowledged": True}}

    sections = derive(ext)
    assert len(sections) == 1
    s = sections[0]
    assert s["name"] == "notes"
    assert s["refresh_activity"] == "skeleton_refresh_notes"
    assert s["alert_activity"] == "skeleton_alert_notes"
    assert s["ttl"] == 60
    assert s["alert_on_change"] is True


def test_ext_skeleton_alert_flag_true_but_no_sibling_tool():
    """User declared alert=True but didn't define skeleton_alert_<X>. We
    preserve the flag but leave alert_activity None — kernel will skip."""
    ext = Extension(app_id="x", version="1.0.0")

    @ext.skeleton("thing", alert=True)
    async def r(ctx):
        return {"response": {}}

    sections = derive(ext)
    assert len(sections) == 1
    s = sections[0]
    assert s["alert_on_change"] is True
    assert s.get("alert_activity") is None


# ---------------------------------------------------------------------
# (B) Fallback path — naming convention
# ---------------------------------------------------------------------

def test_naming_convention_without_decorator():
    """Extensions built with plain @ext.tool still get picked up."""
    ext = Extension(app_id="legacy-ext", version="1.0.0")

    @ext.tool("skeleton_refresh_legacy", description="Legacy refresh")
    async def refresh(ctx):
        return {"response": {}}

    sections = derive(ext)
    assert len(sections) == 1
    s = sections[0]
    assert s["name"] == "legacy"
    assert s["refresh_activity"] == "skeleton_refresh_legacy"
    assert s["ttl"] == 300
    assert s["alert_on_change"] is False


def test_naming_convention_detects_sibling_alert():
    ext = Extension(app_id="x", version="1.0.0")

    @ext.tool("skeleton_refresh_things", description="Refresh things")
    async def r(ctx):
        return {"response": {}}

    @ext.tool("skeleton_alert_things", description="Alert on things change")
    async def a(ctx, **kw):
        return {"response": {}}

    sections = derive(ext)
    assert len(sections) == 1
    s = sections[0]
    assert s["alert_activity"] == "skeleton_alert_things"
    assert s["alert_on_change"] is True


def test_naming_convention_skips_non_skeleton_tools():
    ext = Extension(app_id="x", version="1.0.0")

    @ext.tool("tool_do_thing")
    async def a(ctx):
        return {"response": {}}

    @ext.tool("__panel__sidebar")
    async def p(ctx, **k):
        return {}

    @ext.tool("refresh_without_prefix")  # NOT skeleton_refresh_ — must be ignored
    async def wrong(ctx):
        return {"response": {}}

    sections = derive(ext)
    assert sections == []


def test_bare_skeleton_refresh_prefix_ignored():
    """`skeleton_refresh_` with nothing after the prefix must not become a section."""
    ext = Extension(app_id="x", version="1.0.0")

    # Bypass @ext.skeleton's validation (which would also reject this) and
    # register the malformed tool via plain @ext.tool to exercise the helper
    # directly.
    @ext.tool("skeleton_refresh_")
    async def r(ctx):
        return {"response": {}}

    sections = derive(ext)
    assert sections == []


# ---------------------------------------------------------------------
# Dedup + dual-source combination
# ---------------------------------------------------------------------

def test_decorator_wins_over_naming_convention_for_same_section():
    """If both the decorator and a plain @ext.tool register the same
    skeleton_refresh_<X> name (which would be a user error but shouldn't
    produce duplicate rows), the decorator's metadata wins."""
    ext = Extension(app_id="x", version="1.0.0")

    @ext.skeleton("dual", ttl=120)
    async def r1(ctx):
        return {"response": {}}

    sections = derive(ext)
    names = [s["name"] for s in sections]
    assert names == ["dual"]
    assert sections[0]["ttl"] == 120  # decorator's ttl, not fallback 300


def test_multiple_independent_sections_coexist():
    ext = Extension(app_id="x", version="1.0.0")

    @ext.skeleton("monitors")
    async def r1(ctx):
        return {"response": {}}

    @ext.tool("skeleton_refresh_stats")
    async def r2(ctx):
        return {"response": {}}

    @ext.tool("skeleton_alert_stats")
    async def a(ctx, **k):
        return {"response": {}}

    sections = derive(ext)
    names = sorted(s["name"] for s in sections)
    assert names == ["monitors", "stats"]
    stats = next(s for s in sections if s["name"] == "stats")
    assert stats["alert_on_change"] is True


# ---------------------------------------------------------------------
# Edge cases — empty / bad input
# ---------------------------------------------------------------------

def test_none_extension_returns_empty():
    assert derive(None) == []


def test_extension_with_no_tools_returns_empty():
    ext = Extension(app_id="x", version="1.0.0")
    assert derive(ext) == []


def test_extension_with_non_string_tool_names_skipped():
    """Defensive: the dict should always carry str keys, but guard anyway."""
    ext = Extension(app_id="x", version="1.0.0")
    # Inject a non-string key directly into _tools to simulate corruption
    ext._tools[12345] = object()  # type: ignore[index]

    @ext.tool("skeleton_refresh_valid")
    async def r(ctx):
        return {"response": {}}

    sections = derive(ext)
    # Valid one picks up; garbage entry ignored (no exception)
    names = [s["name"] for s in sections]
    assert names == ["valid"]


def test_ext_skeleton_empty_metadata_dict_ignored():
    """If _skeleton metadata is present but empty / missing section_name,
    the decorator path must skip and fall through to naming convention."""
    ext = Extension(app_id="x", version="1.0.0")

    @ext.tool("skeleton_refresh_okname")
    async def r(ctx):
        return {"response": {}}

    # Tamper: attach an empty _skeleton dict to a DIFFERENT tool
    # (simulating a partially-corrupt decorator result)
    @ext.tool("not_a_skeleton_tool")
    async def other(ctx):
        return {"response": {}}
    ext.tools["not_a_skeleton_tool"]._skeleton = {}  # type: ignore[attr-defined]

    sections = derive(ext)
    # The valid skeleton_refresh_okname picks up via naming convention;
    # the empty-metadata one is ignored.
    assert [s["name"] for s in sections] == ["okname"]


# ---------------------------------------------------------------------
# Registry contract shape
# ---------------------------------------------------------------------

def test_output_uses_registry_key_name_not_section_name():
    """Registry /v1/apps/{id}/tools INSERT reads body.skeleton_sections[i]["name"].

    If we emit "section_name" the INSERT silently stores NULL. This test
    locks the key choice in place so a well-meaning refactor can't drift."""
    ext = Extension(app_id="x", version="1.0.0")

    @ext.skeleton("check")
    async def r(ctx):
        return {"response": {}}

    s = derive(ext)[0]
    assert "name" in s
    assert "section_name" not in s
    # Required keys for Registry replace_tools
    assert "refresh_activity" in s
    assert "alert_activity" in s  # may be None — key must be present
    assert "ttl" in s
    assert "alert_on_change" in s
