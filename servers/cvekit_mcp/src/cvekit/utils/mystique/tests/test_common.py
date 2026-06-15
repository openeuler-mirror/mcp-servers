"""Tests for mystique common enums."""
import pytest
from common import Mode, Language, HunkType, ErrorCode


class TestMode:
    def test_mode_values(self):
        assert Mode.CVE.value == "cve"
        assert Mode.PATCH.value == "patch"

    def test_mode_membership(self):
        assert Mode("cve") == Mode.CVE
        assert Mode("patch") == Mode.PATCH

    def test_mode_invalid_raises(self):
        with pytest.raises(ValueError):
            Mode("unknown")


class TestLanguage:
    def test_language_values(self):
        assert Language.JAVA.value == "javasrc"
        assert Language.C.value == "newc"

    def test_language_membership(self):
        assert Language("javasrc") == Language.JAVA
        assert Language("newc") == Language.C


class TestHunkType:
    def test_hunk_type_values(self):
        assert HunkType.ADD.value == "add"
        assert HunkType.DEL.value == "del"
        assert HunkType.MOD.value == "mod"

    def test_hunk_type_set_operations(self):
        all_types = {HunkType.ADD, HunkType.DEL, HunkType.MOD}
        assert len(all_types) == 3


class TestErrorCode:
    def test_error_code_values(self):
        assert ErrorCode.SUCCESS.value == "SUCCESS"
        assert ErrorCode.EXCEPTION.value == "EXCEPTION"
        assert ErrorCode.AST_ERROR.value == "AST_ERROR"
        assert ErrorCode.METHOD_NOT_FOUND.value == "METHOD_NOT_FOUND"
        assert ErrorCode.PDG_NOT_FOUND.value == "PDG_NOT_FOUND"
        assert ErrorCode.SLICE_FAILED.value == "SLICE_FAILED"
        assert ErrorCode.GROUNDTRUTH_SLICE_FAILED.value == "GROUNDTRUTH_FAILED"

    def test_error_code_str_equality(self):
        assert str(ErrorCode.SUCCESS.value) == "SUCCESS"
