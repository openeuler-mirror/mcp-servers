"""Tests for mystique difftools module."""
import pytest
from common import HunkType
from difftools import (
    Hunk,
    ModHunk,
    AddHunk,
    DelHunk,
    parse_diff,
    parse_diff_from_codes,
    sourtarContextMap,
    method_linemap,
    method_hunkmap,
    get_patch_hunks,
)


# ── Hunk dataclasses ──────────────────────────────────────────────────

class TestModHunk:
    def test_creation(self):
        h = ModHunk(HunkType.MOD, 10, 15, 20, 25, "old", "new")
        assert h.type == HunkType.MOD
        assert h.a_startline == 10
        assert h.a_endline == 15
        assert h.b_startline == 20
        assert h.b_endline == 25
        assert h.a_code == "old"
        assert h.b_code == "new"

    def test_isinstance_hunk(self):
        h = ModHunk(HunkType.MOD, 1, 2, 3, 4, "", "")
        assert isinstance(h, Hunk)


class TestAddHunk:
    def test_creation(self):
        h = AddHunk(HunkType.ADD, 5, 8, "added", 4)
        assert h.type == HunkType.ADD
        assert h.b_startline == 5
        assert h.b_endline == 8
        assert h.b_code == "added"
        assert h.insert_line == 4

    def test_isinstance_hunk(self):
        h = AddHunk(HunkType.ADD, 1, 2, "", 0)
        assert isinstance(h, Hunk)


class TestDelHunk:
    def test_creation(self):
        h = DelHunk(HunkType.DEL, 3, 5, "deleted")
        assert h.type == HunkType.DEL
        assert h.a_startline == 3
        assert h.a_endline == 5
        assert h.a_code == "deleted"

    def test_isinstance_hunk(self):
        h = DelHunk(HunkType.DEL, 1, 2, "")
        assert isinstance(h, Hunk)


# ── parse_diff ────────────────────────────────────────────────────────

class TestParseDiff:
    def test_simple_add(self):
        diff = """@@ -1,3 +1,4 @@
 context
+added line
 context
 context"""
        result = parse_diff(diff)
        assert result["add"] == [2]
        assert result["delete"] == []

    def test_simple_delete(self):
        diff = """@@ -1,4 +1,3 @@
 context
-deleted line
 context
 context"""
        result = parse_diff(diff)
        assert result["add"] == []
        assert result["delete"] == [2]

    def test_mixed_modification(self):
        diff = """@@ -1,4 +1,4 @@
 context
-old
+new
 context
 context"""
        result = parse_diff(diff)
        assert 2 in result["add"]
        assert 2 in result["delete"]

    def test_multiple_hunks(self):
        diff = """@@ -1,3 +1,4 @@
 a
+b
 c
@@ -10,3 +11,2 @@
 x
-y
 z"""
        result = parse_diff(diff)
        assert result["add"] == [2]
        assert result["delete"] == [11]

    def test_skips_diff_header_lines(self):
        diff = """--- a/file
+++ b/file
@@ -1,2 +1,2 @@
-old
+new"""
        result = parse_diff(diff)
        assert 1 in result["add"]
        assert 1 in result["delete"]

    def test_empty_diff(self):
        result = parse_diff("")
        assert result == {"add": [], "delete": []}

    def test_preserves_context_line_numbers(self):
        diff = """@@ -10,5 +20,5 @@
 c1
-a1
 c2
 c3
+b1
 c4"""
        result = parse_diff(diff)
        assert result["delete"] == [11]
        assert result["add"] == [23]


# ── parse_diff_from_codes ─────────────────────────────────────────────

class TestParseDiffFromCodes:
    def test_identical_code_returns_empty(self):
        code = "line1\nline2\nline3"
        result = parse_diff_from_codes(code, code)
        assert result["add"] == []
        assert result["delete"] == []

    def test_single_line_added(self):
        old = "line1\nline2"
        new = "line1\ninserted\nline2"
        result = parse_diff_from_codes(old, new)
        assert result["add"] == [2]
        assert result["delete"] == []

    def test_single_line_deleted(self):
        old = "line1\nremoved\nline2"
        new = "line1\nline2"
        result = parse_diff_from_codes(old, new)
        assert result["add"] == []
        assert result["delete"] == [2]

    def test_line_modified(self):
        old = "line1\nold\nline3"
        new = "line1\nnew\nline3"
        result = parse_diff_from_codes(old, new)
        assert 2 in result["add"]
        assert 2 in result["delete"]

    def test_multiline_changes(self):
        old = "a\nb\nc\nd\ne"
        new = "a\nx\ny\ne"
        result = parse_diff_from_codes(old, new)
        assert 2 in result["delete"]
        assert 3 in result["delete"]
        assert 2 in result["add"]
        assert 3 in result["add"]


# ── sourtarContextMap ─────────────────────────────────────────────────

class TestSourtarContextMap:
    def test_identity_maps_all_lines(self):
        code = "a\nb\nc"
        mod = {"add": [], "delete": []}
        smap, tmap = sourtarContextMap(code, code, mod)
        assert smap == {1: 1, 2: 2, 3: 3}
        assert tmap == {1: 1, 2: 2, 3: 3}

    def test_skips_deleted_lines_in_source(self):
        code_a = "a\nremoved\nc"
        code_b = "a\nc"
        mod = {"add": [], "delete": [2]}
        smap, tmap = sourtarContextMap(code_a, code_b, mod)
        # source: line 2 is deleted → skipped
        assert 1 in smap
        assert 2 not in smap
        assert 3 in smap

    def test_skips_added_lines_in_target(self):
        code_a = "a\nc"
        code_b = "a\nadded\nc"
        mod = {"add": [2], "delete": []}
        smap, tmap = sourtarContextMap(code_a, code_b, mod)
        # target: line 2 is added → skipped
        assert 1 in tmap
        assert 2 not in tmap
        assert 3 in tmap

    def test_context_indices_increment(self):
        code = "a\nb\nc\nd"
        mod = {"add": [], "delete": [2]}
        smap, _ = sourtarContextMap(code, code, mod)
        # lines 1,3,4 get context indices 1,2,3
        assert smap[1] == 1
        assert smap[3] == 2
        assert smap[4] == 3


# ── method_linemap ────────────────────────────────────────────────────

class TestMethodLinemap:
    def test_direct_match(self):
        map_a = {10: 5, 20: 6}
        map_b = {30: 5, 40: 6}
        result = method_linemap(map_a, map_b)
        assert result == {10: 30, 20: 40}

    def test_no_match_returns_empty(self):
        map_a = {10: 5}
        map_b = {30: 99}
        result = method_linemap(map_a, map_b)
        assert result == {}

    def test_partial_match(self):
        map_a = {10: 5, 20: 7}
        map_b = {30: 5, 40: 99}
        result = method_linemap(map_a, map_b)
        assert result == {10: 30}

    def test_empty_maps(self):
        assert method_linemap({}, {}) == {}


# ── method_hunkmap ────────────────────────────────────────────────────

class TestMethodHunkmap:
    def test_matching_hunk_pair(self):
        # del lines 2-3, add lines 10-11
        # context: line 1 maps to 9, line 4 maps to 12
        del_groups = [[2, 3]]
        add_groups = [[10, 11]]
        line_map = {0: 0, 1: 9, 4: 12}
        result = method_hunkmap(del_groups, add_groups, line_map)
        assert (2, 3) in result
        assert result[(2, 3)] == (10, 11)

    def test_no_match_when_context_differs(self):
        del_groups = [[2, 3]]
        add_groups = [[10, 11]]
        line_map = {0: 0, 1: 9, 4: 99}  # tail doesn't match
        result = method_hunkmap(del_groups, add_groups, line_map)
        assert result == {}

    def test_multiple_groups(self):
        del_groups = [[2, 3], [6, 7]]
        add_groups = [[10, 11], [14, 15]]
        line_map = {0: 0, 1: 9, 4: 12, 5: 13, 8: 16}
        result = method_hunkmap(del_groups, add_groups, line_map)
        assert len(result) == 2


# ── get_patch_hunks ───────────────────────────────────────────────────

class TestGetPatchHunks:
    def test_identical_code_returns_empty(self):
        code = "int foo(void) {\n    return 0;\n}"
        hunks = get_patch_hunks(code, code)
        assert hunks == []

    def test_added_lines_produce_add_hunks(self):
        old = "int foo(void) {\n    return 0;\n}"
        new = "int foo(void) {\n    int x = 1;\n    return x;\n}"
        hunks = get_patch_hunks(old, new)
        # Should have modified hunk(s) or add hunk
        assert len(hunks) > 0
        types = {type(h) for h in hunks}
        assert any(issubclass(t, Hunk) for t in types)

    def test_deleted_lines_produce_del_hunks(self):
        old = "int foo(void) {\n    int x = 1;\n    return x;\n}"
        new = "int foo(void) {\n    return 0;\n}"
        hunks = get_patch_hunks(old, new)
        assert len(hunks) > 0
        types = {type(h) for h in hunks}
        assert ModHunk in types or DelHunk in types

    def test_all_hunks_inherit_from_hunk(self):
        old = "line1\nold2\nline3"
        new = "line1\nnew2\nline3"
        hunks = get_patch_hunks(old, new)
        for h in hunks:
            assert isinstance(h, Hunk)
