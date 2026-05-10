"""Skeleton-sync regression tests — edge cases + Registry contract shape.

Companion to ``test_skeleton_sync.py`` (split when the original crossed 300L).
Primary paths (decorator + naming convention) are covered there; this file
locks down empty/bad-input handling and the Registry-contract dict shape.
"""
from __future__ import annotations

from imperal_sdk import Extension  # noqa: E402

from _skeleton_helper import derive  # noqa: E402


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
