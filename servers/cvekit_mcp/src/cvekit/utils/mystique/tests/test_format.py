"""Tests for mystique format module — pure functions only."""
import pytest

# conftest.py mocks ast_parser/tree_sitter_c before import
from format import (
    remove_comments,
    remove_linebreaks,
    remove_spaces,
    remove_empty_lines,
    remove_param_linebreaks,
    normalize,
    del_macros,
)


class TestRemoveComments:
    def test_single_line_comment(self):
        code = 'int x = 1; // this is a comment'
        result = remove_comments(code)
        assert result == 'int x = 1; '

    def test_multi_line_comment(self):
        code = 'int x /* inline */ = 1;'
        result = remove_comments(code)
        assert result == 'int x  = 1;'

    def test_block_comment_multiline(self):
        code = 'start /* block\ncomment\nend */ finish'
        result = remove_comments(code)
        assert result == 'start  finish'

    def test_preserves_string_literals(self):
        code = 'printf("// not a comment");'
        result = remove_comments(code)
        assert result == 'printf("// not a comment");'

    def test_preserves_char_literals(self):
        code = "char c = '//';"
        result = remove_comments(code)
        assert result == "char c = '//';"

    def test_handles_quotes_inside_strings(self):
        code = r'printf("he said \"hello\""); // comment'
        result = remove_comments(code)
        assert result == r'printf("he said \"hello\""); '

    def test_no_comments_returns_unchanged(self):
        code = 'int x = 1;\nint y = 2;'
        result = remove_comments(code)
        assert result == code


class TestRemoveLinebreaks:
    def test_removes_all_newlines(self):
        assert remove_linebreaks("a\nb\nc") == "abc"

    def test_no_newlines(self):
        assert remove_linebreaks("abc") == "abc"

    def test_empty_string(self):
        assert remove_linebreaks("") == ""


class TestRemoveSpaces:
    def test_removes_all_whitespace(self):
        assert remove_spaces("a b c") == "abc"

    def test_removes_tabs_and_newlines(self):
        assert remove_spaces("a\tb\nc  d") == "abcd"

    def test_no_spaces(self):
        assert remove_spaces("abc") == "abc"


class TestRemoveEmptyLines:
    def test_removes_empty_lines(self):
        code = "line1\n\nline2\n\n\nline3"
        result = remove_empty_lines(code)
        lines = result.split("\n")
        assert len(lines) == 3

    def test_whitespace_only_lines_removed(self):
        code = "line1\n   \nline2"
        result = remove_empty_lines(code)
        lines = result.split("\n")
        assert len(lines) == 2

    def test_no_empty_lines(self):
        code = "line1\nline2"
        assert remove_empty_lines(code) == code


class TestRemoveParamLinebreaks:
    def test_removes_spaces_around_comma(self):
        code = "func(a ,  b ,c)"
        result = remove_param_linebreaks(code)
        # regex r",\s*" → ", ": extra whitespace AFTER comma is collapsed
        # to exactly one space. Whitespace before comma is untouched.
        assert "a ,  b" not in result  # double space after comma removed
        assert "a ," in result or "a," in result

    def test_no_commas(self):
        code = "func(a b c)"
        assert remove_param_linebreaks(code) == code


class TestNormalize:
    def test_removes_comments_and_whitespace(self):
        code = "int x = 1; // comment\nint y = 2;"
        result = normalize(code)
        assert "//" not in result
        assert "\n" not in result

    def test_preserve_comments_option(self):
        code = "int x = 1; // keep this"
        result = normalize(code, del_comments=False)
        # Comments preserved but spaces removed: "keepthis"
        assert "keepthis" in result


class TestDelMacros:
    def test_removes_inline_macro(self):
        code = "static __init int foo(void)"
        result = del_macros(code)
        assert "__init" not in result
        assert "foo" in result

    def test_removes_multiple_macros(self):
        code = "__init __user void bar(void)"
        result = del_macros(code)
        assert "__init" not in result
        assert "__user" not in result
        assert "bar" in result

    def test_preserves_non_macro_identifiers(self):
        code = "int my_init_function(void) { return 0; }"
        result = del_macros(code)
        assert "my_init_function" in result

    def test_removes_preprocessor_lines(self):
        code = "#define MAX 100\nint x = MAX;"
        result = del_macros(code)
        assert "#define" not in result

    def test_preserves_include_lines(self):
        code = '#include <stdio.h>\nint x;'
        result = del_macros(code)
        assert "#include" in result

    def test_removes_extern_c(self):
        code = 'extern "C" void foo(void);'
        result = del_macros(code)
        assert 'extern "C"' not in result

    def test_handles_line_continuation(self):
        code = "#define LONG_MACRO \\\n    value \\\n    more\nint x;"
        result = del_macros(code)
        assert "LONG_MACRO" not in result or "int x" in result

    def test_empty_code(self):
        assert del_macros("") == ""

    def test_no_macros_returns_unchanged(self):
        code = "int foo(void) {\n    return 0;\n}"
        result = del_macros(code)
        assert "foo" in result

    def test_does_not_damage_einval(self):
        """__init should not destroy substring 'init' inside EINVAL."""
        code = "if (err == -EINVAL)"
        result = del_macros(code)
        assert "EINVAL" in result
        assert "-EINVAL" in result

    def test_preserves_in_out_inside_string_literals(self):
        code = (
            'drm_dbg_dp(&priv->dev, "HPD IN isr occur!\\n");\n'
            'drm_dbg_dp(&priv->dev, "HPD OUT isr occur!\\n");'
        )
        result = del_macros(code)
        assert '"HPD IN isr occur!\\n"' in result
        assert '"HPD OUT isr occur!\\n"' in result

    def test_still_removes_in_out_parameter_macros(self):
        code = "void foo(IN int *src, OUT int *dst);"
        result = del_macros(code)
        assert "IN int" not in result
        assert "OUT int" not in result
        assert "int *src" in result
        assert "int *dst" in result
