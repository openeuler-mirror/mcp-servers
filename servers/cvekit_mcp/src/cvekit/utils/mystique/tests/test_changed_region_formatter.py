"""Tests for changed_region_formatter — pure functions only."""
import pytest

# conftest.py mocks llm before import
from changed_region_formatter import (
    _line_match_key,
    _clean_llm_result,
    _restore_equivalent_function_header,
    restore_patch_added_blank_lines,
)


class TestLineMatchKey:
    def test_removes_whitespace_preserves_text(self):
        result = _line_match_key("  int   x  =  1;  ")
        assert result == "intx=1;"

    def test_preserves_string_literal_whitespace(self):
        result = _line_match_key('printf("  hello  world  ");')
        assert result == 'printf("  hello  world  ");'

    def test_preserves_single_line_comment(self):
        result = _line_match_key("int x; // comment here")
        assert result == "intx;// comment here"

    def test_preserves_block_comment_start(self):
        result = _line_match_key("int /* comment */ x;")
        # After `/*` everything from that position is appended verbatim
        assert result == "int/* comment */ x;"

    def test_empty_line(self):
        assert _line_match_key("") == ""

    def test_whitespace_only_line(self):
        assert _line_match_key("   \t  ") == ""


class TestCleanLlmResult:
    def test_removes_thinking_tags(self):
        code = "<thinking>some reasoning</thinking>\nint x = 1;"
        result = _clean_llm_result(code)
        assert "<thinking>" not in result
        assert "some reasoning" not in result
        assert "int x = 1;" in result

    def test_removes_ant_thinking_tags(self):
        code = "<antThinking>reason</antThinking>\ncode;"
        result = _clean_llm_result(code)
        assert "reason" not in result
        assert "code;" in result

    def test_removes_begin_thinking_tags(self):
        code = "<|begin_thinking|>reason<|end_thinking|>\ncode;"
        result = _clean_llm_result(code)
        assert "reason" not in result
        assert "code;" in result

    def test_removes_think_tags(self):
        code = "<think>reason</think>\ncode;"
        result = _clean_llm_result(code)
        assert "reason" not in result
        assert "code;" in result

    def test_removes_markdown_fence(self):
        code = "```c\nint x = 1;\n```"
        result = _clean_llm_result(code)
        assert "```" not in result
        assert "int x = 1;" in result

    def test_removes_cpp_fence(self):
        code = "```cpp\nint x = 1;\n```"
        result = _clean_llm_result(code)
        assert "```" not in result

    def test_strips_trailing_newlines(self):
        code = "int x = 1;\n\n\n"
        result = _clean_llm_result(code)
        assert result == "int x = 1;"

    def test_no_tags_returns_same(self):
        code = "int x = 1;"
        result = _clean_llm_result(code)
        assert result == code

    def test_multiple_thinking_blocks(self):
        code = "<thinking>a</thinking>code;<thinking>b</thinking>more;"
        result = _clean_llm_result(code)
        assert result == "code;more;"


class TestRestoreEquivalentFunctionHeader:
    def test_restores_when_only_whitespace_differs(self):
        target = ["static int foo(void)", "{"]
        patched = ["static int foo(void) {", "..."]
        result = _restore_equivalent_function_header(target, patched)
        assert result[0] == "static int foo(void)"
        assert result[1] == "{"

    def test_no_change_when_no_brace(self):
        target = ["static int foo(void)"]
        patched = ["static int foo(void)"]
        result = _restore_equivalent_function_header(target, patched)
        assert result == patched

    def test_no_change_when_content_differs(self):
        target = ["static int foo(void)", "{"]
        patched = ["static int bar(void)", "{"]
        result = _restore_equivalent_function_header(target, patched)
        # Different function name → should NOT replace
        assert "bar" in result[0]


class TestRestorePatchAddedBlankLines:
    def test_no_file_patch_returns_unchanged(self):
        code = "line1\nline2"
        assert restore_patch_added_blank_lines(code, None) == code

    def test_empty_file_patch_returns_unchanged(self):
        code = "line1\nline2"
        assert restore_patch_added_blank_lines(code, "") == code

    def test_no_blank_line_additions(self):
        patch = "@@ -1,2 +1,2 @@\n line1\n line2"
        code = "line1\nline2"
        result = restore_patch_added_blank_lines(code, patch)
        assert result == code

    def test_restores_blank_line_between_anchors(self):
        patch = """\
@@ -1,3 +1,4 @@
 statement1;
+
 statement2;"""
        code = "statement1;\nstatement2;"
        result = restore_patch_added_blank_lines(code, patch)
        lines = result.split("\n")
        assert lines[0] == "statement1;"
        assert lines[1] == ""
        assert lines[2] == "statement2;"
