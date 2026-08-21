import json
import os

import pytest

import deploy_sync_artifacts as mod


def test_prefers_manifest_icon_filename(tmp_path):
    (tmp_path / "mail.svg").write_text("<svg>MAIL</svg>")
    path = mod._resolve_icon_path(str(tmp_path), {"icon": "mail.svg"})
    assert path and os.path.basename(path) == "mail.svg"


def test_falls_back_to_icon_svg(tmp_path):
    (tmp_path / "icon.svg").write_text("<svg>I</svg>")
    path = mod._resolve_icon_path(str(tmp_path), {})
    assert path and os.path.basename(path) == "icon.svg"


def test_single_svg_fallback_when_manifest_and_iconsvg_absent(tmp_path):
    (tmp_path / "logo.svg").write_text("<svg>L</svg>")
    path = mod._resolve_icon_path(str(tmp_path), {})
    assert path and os.path.basename(path) == "logo.svg"


def test_none_when_no_svg(tmp_path):
    assert mod._resolve_icon_path(str(tmp_path), {}) is None


def test_path_traversal_blocked(tmp_path):
    (tmp_path / "icon.svg").write_text("<svg>I</svg>")
    # Hostile manifest icon must not escape app_dir; basename neutralizes it.
    path = mod._resolve_icon_path(str(tmp_path), {"icon": "../../etc/passwd.svg"})
    # No such file inside app_dir -> falls back to icon.svg
    assert path and os.path.basename(path) == "icon.svg"


def test_non_svg_manifest_value_ignored(tmp_path):
    (tmp_path / "icon.svg").write_text("<svg>I</svg>")
    path = mod._resolve_icon_path(str(tmp_path), {"icon": "icon.png"})
    assert path and os.path.basename(path) == "icon.svg"


# ---------------------------------------------------------------------------
# I-SYSTEM-FLAG-MANIFEST-SYNC: system bool must self-heal into developer_apps
# on every deploy, mirroring icon_svg/manifest_json.
# ---------------------------------------------------------------------------

def _write_manifest(tmp_path, **fields):
    manifest = {"app_id": "test-app", "name": "Test App", "version": "1.0.0", **fields}
    (tmp_path / "imperal.json").write_text(json.dumps(manifest))
    return manifest


@pytest.mark.asyncio
async def test_manifest_system_true_included_in_sync_payload(tmp_path):
    _write_manifest(tmp_path, system=True)
    calls = []

    async def fake_gw_post(path, payload):
        calls.append((path, payload))
        return {"updated": True}

    await mod.sync_icon_and_manifest_to_gw("test-app", str(tmp_path), fake_gw_post)

    sync_calls = [c for c in calls if c[0].endswith("/_sync_manifest")]
    assert len(sync_calls) == 1
    assert sync_calls[0][1]["system"] is True


@pytest.mark.asyncio
async def test_manifest_system_false_included_as_false_not_omitted(tmp_path):
    _write_manifest(tmp_path, system=False)
    calls = []

    async def fake_gw_post(path, payload):
        calls.append((path, payload))
        return {"updated": True}

    await mod.sync_icon_and_manifest_to_gw("test-app", str(tmp_path), fake_gw_post)

    sync_calls = [c for c in calls if c[0].endswith("/_sync_manifest")]
    assert len(sync_calls) == 1
    # False is a legitimate value (un-marking a system app) — must NOT be
    # dropped as falsy; the key must be present with value False.
    assert "system" in sync_calls[0][1]
    assert sync_calls[0][1]["system"] is False


@pytest.mark.asyncio
async def test_manifest_without_system_field_omits_it_from_payload(tmp_path):
    _write_manifest(tmp_path)  # no "system" key at all
    calls = []

    async def fake_gw_post(path, payload):
        calls.append((path, payload))
        return {"updated": True}

    await mod.sync_icon_and_manifest_to_gw("test-app", str(tmp_path), fake_gw_post)

    sync_calls = [c for c in calls if c[0].endswith("/_sync_manifest")]
    assert len(sync_calls) == 1
    assert "system" not in sync_calls[0][1]
    assert "manifest_json" in sync_calls[0][1]


# ---------------------------------------------------------------------------
# B-manifest-indent (2026-08-21): a pretty-printed manifest must not be
# rejected for bytes that are pure whitespace.
#
# Live report: deploying WordPress Hub returned manifest_synced=false with no
# error in any log. imperal.json is written with indent=2 and weighed 1212 KB
# on disk -- past the gateway's 1 MB cap -- so the size guard skipped the POST
# and no exception was ever raised for the except branch to report. The SAME
# manifest serialized compactly is 609 KB: 603 KB of the "overflow" was
# indentation. The gateway compacts a dict payload itself, so the fix posts the
# parsed dict and measures the compact form.
# ---------------------------------------------------------------------------

def _write_fat_manifest(tmp_path, *, n_tools: int = 1500):
    """A manifest that is over the 1 MB cap pretty-printed, under it compact --
    exactly the WordPress Hub shape that exposed the bug."""
    manifest = {
        "app_id": "fat-app", "name": "Fat App", "version": "1.0.0",
        "tools": [
            {
                "name": f"do_something_number_{i}",
                "description": "A described tool. " * 12,
                "parameters": {f"param_{j}": {"type": "string", "required": False}
                               for j in range(6)},
            }
            for i in range(n_tools)
        ],
    }
    pretty = json.dumps(manifest, indent=2, ensure_ascii=False)
    compact = json.dumps(manifest, separators=(",", ":"), ensure_ascii=False)
    # Guard the fixture itself: if these stop straddling the cap the test below
    # would silently stop testing anything.
    assert len(pretty.encode()) > mod._MANIFEST_MAX_BYTES, "fixture no longer exceeds cap when pretty"
    assert len(compact.encode()) < mod._MANIFEST_MAX_BYTES, "fixture no longer fits cap when compact"
    (tmp_path / "imperal.json").write_text(pretty)
    return manifest


@pytest.mark.asyncio
async def test_pretty_printed_manifest_over_cap_still_syncs(tmp_path):
    """The regression itself: indentation must never cost a sync."""
    _write_fat_manifest(tmp_path)
    calls = []

    async def fake_gw_post(path, payload):
        calls.append((path, payload))
        return {"updated": True}

    result = await mod.sync_icon_and_manifest_to_gw("fat-app", str(tmp_path), fake_gw_post)

    sync_calls = [c for c in calls if c[0].endswith("/_sync_manifest")]
    assert len(sync_calls) == 1, "over-cap-when-pretty manifest was silently skipped"
    assert result["manifest_synced"] is True


@pytest.mark.asyncio
async def test_manifest_posted_as_dict_not_raw_text(tmp_path):
    """Post the parsed object: the gateway compacts a dict, and only a dict
    lets it derive version/display_name/secrets without re-parsing our text."""
    _write_manifest(tmp_path, system=True)
    calls = []

    async def fake_gw_post(path, payload):
        calls.append((path, payload))
        return {"updated": True}

    await mod.sync_icon_and_manifest_to_gw("test-app", str(tmp_path), fake_gw_post)

    sync_calls = [c for c in calls if c[0].endswith("/_sync_manifest")]
    blob = sync_calls[0][1]["manifest_json"]
    assert isinstance(blob, dict), f"manifest_json must be posted parsed, got {type(blob).__name__}"
    assert blob["app_id"] == "test-app"


@pytest.mark.asyncio
async def test_genuinely_oversized_manifest_is_skipped_loudly(tmp_path, caplog):
    """Still refuse what genuinely cannot fit -- but never in silence."""
    huge = {"app_id": "huge-app", "version": "1.0.0",
            "blob": "x" * (mod._MANIFEST_MAX_BYTES + 5_000)}
    (tmp_path / "imperal.json").write_text(json.dumps(huge))
    calls = []

    async def fake_gw_post(path, payload):
        calls.append((path, payload))
        return {"updated": True}

    with caplog.at_level("WARNING"):
        result = await mod.sync_icon_and_manifest_to_gw("huge-app", str(tmp_path), fake_gw_post)

    assert [c for c in calls if c[0].endswith("/_sync_manifest")] == []
    assert result["manifest_synced"] is False
    # getMessage() renders the lazy %-args the logger was called with.
    assert any("exceeds" in r.getMessage() for r in caplog.records), \
        "the skip must be logged, not silent"


@pytest.mark.asyncio
async def test_unparseable_manifest_falls_back_to_raw_text(tmp_path):
    """A hand-edited/invalid manifest still syncs as text rather than vanishing."""
    (tmp_path / "imperal.json").write_text("{ this is not json ]")
    calls = []

    async def fake_gw_post(path, payload):
        calls.append((path, payload))
        return {"updated": True}

    await mod.sync_icon_and_manifest_to_gw("broken-app", str(tmp_path), fake_gw_post)

    sync_calls = [c for c in calls if c[0].endswith("/_sync_manifest")]
    assert len(sync_calls) == 1
    assert isinstance(sync_calls[0][1]["manifest_json"], str)
