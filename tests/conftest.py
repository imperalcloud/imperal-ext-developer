"""Pytest config — make `_skeleton_helper` importable by sibling test files."""
import os
import sys

# Add tests/ dir to sys.path so `from _skeleton_helper import derive` works.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# queries.py builds its engine AT IMPORT TIME and hard-refuses to start
# without DATABASE_URL (no plaintext credential fallback — federal/CJIS).
# Importing any handler therefore drags in that check, so tests need a URL
# present. This is a syntactically-valid DUMMY that is never connected to:
# every test stubs the gateway/DB seam it exercises. Set before the handler
# modules are imported, and only if the developer has not set a real one.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:5432/test"
)
