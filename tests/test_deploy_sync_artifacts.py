import os
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
