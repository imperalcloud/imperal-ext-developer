"""Scope badge rendering tests for panels_secrets.py.

Guards that build_secrets renders an `app (shared)` scope badge when the
manifest declares scope="app" on a secret.
"""
import asyncio
import sys
import os

# Ensure the dev-ext root is importable so `import panels_secrets` (and its
# `from app import _gw_get`) resolves correctly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import panels_secrets as ps


def _find_badges(node):
    """Recursively collect Badge labels from a UINode tree.

    Handles UINode objects (imperal_sdk.ui.base.UINode), plain dicts, and lists.
    """
    found = []

    def walk(n):
        # UINode object
        t = getattr(n, "type", None)
        props = getattr(n, "props", None)
        if t == "Badge" and isinstance(props, dict):
            found.append(props.get("label", ""))
        if isinstance(props, dict):
            for v in props.values():
                walk(v)
        if isinstance(n, dict):
            if n.get("type") == "Badge":
                found.append((n.get("props") or {}).get("label", n.get("label", "")))
            for v in n.values():
                walk(v)
        elif isinstance(n, (list, tuple)):
            for v in n:
                walk(v)

    walk(node)
    return found


def test_app_scope_badge_rendered(monkeypatch):
    async def fake_app(path):
        return {
            "manifest_json": (
                '{"secrets":[{"name":"client_secret","scope":"app",'
                '"description":"shared"}]}'
            )
        }

    async def fake_list(path, uid):
        return [
            {"name": "client_secret", "scope": "app", "is_set": True, "last_accessed_at": None}
        ]

    monkeypatch.setattr(ps, "_gw_get", fake_app)
    monkeypatch.setattr(ps, "_gw_get_as_user", fake_list)
    node = asyncio.run(ps.build_secrets("dev-1", "spotify"))
    badges = [b.lower() for b in _find_badges(node)]
    assert any("shared" in b or "app" in b for b in badges), (
        f"Expected a badge containing 'shared' or 'app', got: {badges}"
    )
