"""Skeleton-sync regression tests — primary paths.

Guards the dual-source logic in
``deploy_sync.py::_derive_skeleton_sections_from_ext``:

  (A) Primary   — ``@ext.skeleton(…)`` decorator metadata on
                  ``ToolDef._skeleton`` (SDK 1.5.22+).
  (B) Fallback  — naming convention: ``@ext.tool("skeleton_refresh_<X>")``
                  registers section ``<X>``; sibling
                  ``skeleton_alert_<X>`` enables ``alert_on_change=True``.

Edge cases + Registry contract shape live in
``test_skeleton_sync_edges.py`` (split when this file crossed 300L).

R9 of the portal's own deploy pipeline runs this suite on every self-deploy.
"""
from __future__ import annotations

import pytest  # noqa: E402

from imperal_sdk import Extension  # noqa: E402

from _skeleton_helper import derive  # noqa: E402


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
