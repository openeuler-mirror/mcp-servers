"""Tests for semantic_sanitizer module."""
import pytest
from semantic_sanitizer import (
    unescaped_newlines_in_strings,
    repair_broken_string_newlines,
)


class TestUnescapedNewlinesInStrings:
    def test_no_newlines(self):
        code = 'printf("hello world");'
        assert unescaped_newlines_in_strings(code) == []

    def test_escaped_newline(self):
        code = 'printf("hello\\nworld");'
        # escaped newline is legit \n sequence, not actual newline
        assert unescaped_newlines_in_strings(code) == []

    def test_actual_newline_in_string(self):
        code = 'printf("hello\nworld");'
        result = unescaped_newlines_in_strings(code)
        assert len(result) == 1
        assert result[0] == 1

    def test_multiline_string_spans_lines(self):
        # "line1\nline2\nline3" — newlines at end of line1 and line2 → [1, 2]
        code = 'char *s = "line1\nline2\nline3";'
        result = unescaped_newlines_in_strings(code)
        assert result == [1, 2]

    def test_no_false_positives_outside_strings(self):
        code = 'int x = 1;\nint y = 2;\nprintf("ok");'
        assert unescaped_newlines_in_strings(code) == []

    def test_empty_string(self):
        assert unescaped_newlines_in_strings("") == []

    def test_no_string_in_code(self):
        code = "int x = 1;\nint y = 2;\nreturn x + y;"
        assert unescaped_newlines_in_strings(code) == []

    def test_char_literal_not_string(self):
        code = "'\n'"
        # char literal with newline — not a string, should not match
        assert unescaped_newlines_in_strings(code) == []


class TestRepairBrokenStringNewlines:
    def test_repair_newline_before_closing_quote(self):
        code = 'pr_err("message\n");'
        result = repair_broken_string_newlines(code)
        assert result == 'pr_err("message\\n");'

    def test_no_repair_for_legit_escaped_newline(self):
        code = 'pr_err("message\\n");'
        result = repair_broken_string_newlines(code)
        assert result == code

    def test_no_repair_for_proper_string(self):
        code = 'printf("hello world");'
        result = repair_broken_string_newlines(code)
        assert result == code

    def test_repair_with_whitespace_before_quote(self):
        code = 'pr_err("message\n    ");'
        result = repair_broken_string_newlines(code)
        assert result == 'pr_err("message\\n");'

    def test_multiple_repairs(self):
        code = 'log("first\n");\nlog("second\n");'
        result = repair_broken_string_newlines(code)
        assert '\\n"' in result
        assert result.count('\\n"') == 2

    def test_newline_mid_string_not_repaired(self):
        # This pattern (newline in middle, not before closing quote) is ambiguous
        code = 'printf("hello\nworld");'
        result = repair_broken_string_newlines(code)
        # The newline is followed by "world", not a closing quote
        # Currently the function does NOT repair this (by design)
        assert "hello\nworld" in result

    def test_empty_code(self):
        assert repair_broken_string_newlines("") == ""

    def test_code_without_strings(self):
        code = "int x = 1;\nint y = 2;"
        assert repair_broken_string_newlines(code) == code

    def test_repair_with_tabs_before_quote(self):
        code = 'pr_err("message\n\t\t");'
        result = repair_broken_string_newlines(code)
        assert result == 'pr_err("message\\n");'
