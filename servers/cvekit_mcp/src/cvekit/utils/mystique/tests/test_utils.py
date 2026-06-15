"""Tests for mystique utils module — pure functions."""
import os
import tempfile
import pytest

# conftest.py mocks joern/cpu_heater before import
import utils


class TestGroupConsecutiveInts:
    def test_empty_list(self):
        assert utils.group_consecutive_ints([]) == []

    def test_single_element(self):
        assert utils.group_consecutive_ints([5]) == [[5]]

    def test_consecutive_group(self):
        result = utils.group_consecutive_ints([1, 2, 3])
        assert result == [[1, 2, 3]]

    def test_multiple_groups(self):
        result = utils.group_consecutive_ints([1, 2, 4, 5, 7])
        assert result == [[1, 2], [4, 5], [7]]

    def test_unsorted_input(self):
        result = utils.group_consecutive_ints([3, 1, 2, 8, 5, 6])
        assert result == [[1, 2, 3], [5, 6], [8]]

    def test_large_gap(self):
        result = utils.group_consecutive_ints([1, 100, 200])
        assert result == [[1], [100], [200]]

    def test_all_consecutive(self):
        result = utils.group_consecutive_ints([10, 11, 12, 13, 14])
        assert result == [[10, 11, 12, 13, 14]]

    def test_all_isolated(self):
        result = utils.group_consecutive_ints([1, 3, 5, 7])
        assert result == [[1], [3], [5], [7]]


class TestWrite2file:
    def test_writes_content_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            utils.write2file(path, "hello")
            with open(path) as f:
                assert f.read() == "hello"

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            utils.write2file(path, "first")
            utils.write2file(path, "second")
            with open(path) as f:
                assert f.read() == "second"

    def test_writes_empty_string(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "empty.txt")
            utils.write2file(path, "")
            with open(path) as f:
                assert f.read() == ""


class TestWrite2method:
    def test_writes_to_method_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            utils.write2method(tmpdir, "test.txt", "content")
            with open(os.path.join(tmpdir, "test.txt")) as f:
                assert f.read() == "content"


class TestRecursiveParentFind:
    def test_finds_file_in_current_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "subdir"))
            target = os.path.join(tmpdir, "subdir", "Makefile")
            with open(target, "w") as f:
                f.write("")
            all_files = [target]
            result = utils.recursive_parent_find(
                os.path.join(tmpdir, "subdir"), "Makefile", all_files
            )
            assert result == os.path.join(tmpdir, "subdir")

    def test_finds_file_in_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "a", "b", "c"))
            target = os.path.join(tmpdir, "a", "Makefile")
            with open(target, "w") as f:
                f.write("")
            all_files = [target]
            result = utils.recursive_parent_find(
                os.path.join(tmpdir, "a", "b", "c"), "Makefile", all_files
            )
            assert result == os.path.join(tmpdir, "a")

    def test_returns_none_when_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = utils.recursive_parent_find(tmpdir, "nonexistent", [])
            assert result is None

    def test_stops_at_root(self):
        result = utils.recursive_parent_find("/", "nonexistent", [])
        assert result is None
