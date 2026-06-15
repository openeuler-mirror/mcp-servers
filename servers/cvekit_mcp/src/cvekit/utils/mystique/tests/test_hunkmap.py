"""Tests for hunkmap module — pure functions not requiring Method objects."""
import pytest

import difftools
import hunkmap
import utils


class TestSourtarDiffMap:
    def test_groups_delete_lines(self):
        mod = {"add": [], "delete": [1, 2, 4, 5, 7]}
        del_groups, add_groups = hunkmap.sourtarDiffMap(mod)
        assert del_groups == [[1, 2], [4, 5], [7]]
        assert add_groups == []

    def test_groups_add_lines(self):
        mod = {"add": [10, 11, 13], "delete": []}
        del_groups, add_groups = hunkmap.sourtarDiffMap(mod)
        assert add_groups == [[10, 11], [13]]
        assert del_groups == []

    def test_empty_modified(self):
        mod = {"add": [], "delete": []}
        del_groups, add_groups = hunkmap.sourtarDiffMap(mod)
        assert del_groups == []
        assert add_groups == []

    def test_equivalent_to_utils_group_consecutive_ints(self):
        nums = [3, 1, 2, 5, 6]
        mod = {"add": nums, "delete": []}
        _, add_groups = hunkmap.sourtarDiffMap(mod)
        expected = utils.group_consecutive_ints(nums)
        assert add_groups == expected


class TestMethodLinemap:
    def test_pivot_matching(self):
        map_a = {10: 100, 20: 200}
        map_b = {30: 100, 40: 200}
        result = hunkmap.method_linemap(map_a, map_b)
        assert result == {10: 30, 20: 40}

    def test_missing_pivot(self):
        map_a = {10: 100}
        map_b = {30: 999}
        result = hunkmap.method_linemap(map_a, map_b)
        assert result == {}

    def test_empty(self):
        assert hunkmap.method_linemap({}, {}) == {}


class TestMethodHunkmap:
    def test_single_matching_pair(self):
        del_groups = [[2, 3]]
        add_groups = [[10, 11]]
        line_map = {0: 0, 1: 9, 4: 12}
        result = hunkmap.method_hunkmap(del_groups, add_groups, line_map)
        assert (2, 3) in result
        assert result[(2, 3)] == (10, 11)

    def test_no_match(self):
        del_groups = [[2, 3]]
        add_groups = [[10, 11]]
        line_map = {0: 0}  # missing context
        result = hunkmap.method_hunkmap(del_groups, add_groups, line_map)
        assert result == {}

    def test_line_map_0_is_always_0(self):
        """line_map[0] is always set to 0 before matching."""
        del_groups = [[1, 2]]
        add_groups = [[5, 6]]
        line_map = {}  # 0 will be added automatically
        result = hunkmap.method_hunkmap(del_groups, add_groups, line_map)
        # del_head = 0, del_tail = 3 — need both to be in line_map
        assert result == {}


class TestCodeMap:
    def test_identical_code(self):
        code = "int foo(void) {\n    return 0;\n}"
        line_map, hunk_map, diff_add, diff_del = hunkmap.code_map(code, code)
        assert hunk_map == {}
        assert diff_add == set()
        assert diff_del == set()

    def test_single_line_change(self):
        old = "int foo(void) {\n    return 0;\n}"
        new = "int foo(void) {\n    return 1;\n}"
        line_map, hunk_map, diff_add, diff_del = hunkmap.code_map(old, new)
        # line 2 changed: add=2, del=2 → they should be mapped as a mod hunk
        assert len(hunk_map) > 0

    def test_addition_only(self):
        old = "line1\nline2"
        new = "line1\ninserted\nline2"
        line_map, hunk_map, diff_add, diff_del = hunkmap.code_map(old, new)
        # line 2 is inserted
        assert 2 in diff_add or len(hunk_map) > 0

    def test_deletion_only(self):
        old = "line1\nremoved\nline2"
        new = "line1\nline2"
        line_map, hunk_map, diff_add, diff_del = hunkmap.code_map(old, new)
        # line 2 is deleted
        assert 2 in diff_del or len(hunk_map) > 0
