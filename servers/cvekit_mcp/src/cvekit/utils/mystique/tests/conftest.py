"""conftest for mystique unit tests.

Sets up sys.path so that mystique/src modules can be imported as top-level
names (``import difftools``, ``from common import Language``, etc.).
"""
import sys
import os
from pathlib import Path

_MYSTIQUE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_MYSTIQUE_SRC) not in sys.path:
    sys.path.insert(0, str(_MYSTIQUE_SRC))

# Ignore old standalone test scripts (not pytest-compatible) during collection
collect_ignore = [
    "test_api_connection.py",
    "test_diff_debug.py",
    "test_fix_gap_splitting.py",
    "test_joint_fix.py",
    "test_normalize.py",
    "test_recover_placeholder.py",
    "test_review_fix.py",
    "test_show.py",
]


def _ensure_mock_modules():
    """Mock heavy/unavailable deps so format/hunkmap/etc. can be imported."""
    from unittest import mock

    _MOCK_DEPS = [
        "ast_parser",
        "tree_sitter",
        "tree_sitter_c",
        "joern",
        "networkx",
        "cpu_heater",
        "llm",
    ]
    for mod in _MOCK_DEPS:
        if mod not in sys.modules:
            # Only mock if the real module cannot be imported
            try:
                __import__(mod)
            except ImportError:
                sys.modules[mod] = mock.MagicMock()

    if "project" not in sys.modules:
        try:
            __import__("project")
        except ImportError:
            sys.modules["project"] = mock.MagicMock()


# Call once at collection time so format/hunkmap can be imported in tests
_ensure_mock_modules()
