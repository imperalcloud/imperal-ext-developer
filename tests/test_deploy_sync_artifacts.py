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
