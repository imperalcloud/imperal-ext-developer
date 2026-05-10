"""Pytest config — make `_skeleton_helper` importable by sibling test files."""
import os
import sys

# Add tests/ dir to sys.path so `from _skeleton_helper import derive` works.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
