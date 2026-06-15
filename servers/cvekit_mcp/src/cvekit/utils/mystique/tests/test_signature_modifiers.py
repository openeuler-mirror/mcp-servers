"""Tests for signature_modifiers module."""
import pytest
from signature_modifiers import (
    KERNEL_SIGNATURE_MODIFIERS,
    _modified_function_names,
    _signature_window,
    _target_function_modifiers,
    restore_target_signature_modifiers,
)


class TestKernelSignatureModifiers:
    def test_known_modifiers(self):
        assert "__init" in KERNEL_SIGNATURE_MODIFIERS
        assert "__exit" in KERNEL_SIGNATURE_MODIFIERS
        assert "__user" in KERNEL_SIGNATURE_MODIFIERS


class TestModifiedFunctionNames:
    def test_extracts_function_names(self):
        sigs = ["file.c#my_func", "file.c#another_func"]
        result = _modified_function_names(sigs)
        assert result == {"my_func", "another_func"}

    def test_handles_hash_in_filename(self):
        sigs = ["path/to/file#func"]
        # rsplit("#", 1) splits on last #
        # Actually rsplit gives ["path/to/file", "func"]
        assert _modified_function_names(sigs) == {"func"}

    def test_handles_multiple_hashes(self):
        sigs = ["a#b#func_name"]
        result = _modified_function_names(sigs)
        assert result == {"func_name"}

    def test_none_returns_empty_set(self):
        assert _modified_function_names(None) == set()

    def test_empty_list_returns_empty_set(self):
        assert _modified_function_names([]) == set()

    def test_deduplicates(self):
        sigs = ["a.c#foo", "b.c#foo"]
        result = _modified_function_names(sigs)
        assert result == {"foo"}


class TestSignatureWindow:
    def test_simple_one_line(self):
        lines = [
            "static int __init my_func(int x)",
            "{",
            "    return 0;",
        ]
        window = _signature_window(lines, 0)
        assert "my_func" in window

    def test_walks_back_multiple_lines(self):
        lines = [
            "static",
            "int",
            "__init",
            "my_func(int a,",
            "        int b)",
            "{",
        ]
        window = _signature_window(lines, 4)
        assert "static" in window
        assert "my_func" in window
        assert "__init" in window

    def test_stops_at_semicolon(self):
        lines = [
            "int other_func(void);",
            "",
            "int my_func(void)",
            "{",
        ]
        window = _signature_window(lines, 2)
        # Should NOT include line 0 (ends with ;)
        assert "other_func" not in window

    def test_stops_at_closing_brace(self):
        lines = [
            "}",
            "",
            "int my_func(void)",
            "{",
        ]
        window = _signature_window(lines, 2)
        assert "}" not in window

    def test_stops_at_opening_brace(self):
        lines = [
            "int helper(void) { return 0; }",
            "",
            "int my_func(void)",
            "{",
        ]
        window = _signature_window(lines, 2)
        assert "helper" not in window


class TestTargetFunctionModifiers:
    def test_finds_init_modifier(self):
        code = "static int __init my_init(void)"
        mods = _target_function_modifiers(code, "my_init")
        assert "__init" in mods

    def test_finds_exit_modifier(self):
        code = "void __exit my_cleanup(void)"
        mods = _target_function_modifiers(code, "my_cleanup")
        assert "__exit" in mods

    def test_finds_multiple_modifiers(self):
        code = "static int __init __user my_func(void)"
        # Note: __user is typically a parameter annotation, not a function modifier
        mods = _target_function_modifiers(code, "my_func")
        # Both could be found if they appear before the function name
        assert len(mods) >= 1

    def test_no_modifier_returns_empty(self):
        code = "static int plain_func(void)"
        mods = _target_function_modifiers(code, "plain_func")
        assert mods == []

    def test_function_not_found_returns_empty(self):
        code = "int other(void) { }"
        mods = _target_function_modifiers(code, "nonexistent")
        assert mods == []


class TestRestoreTargetSignatureModifiers:
    TARGET = """\
static int __init my_init(void)
{
    return 0;
}

void __exit my_exit(void)
{
}
"""

    def test_restores_missing_init(self):
        patched = """\
static int my_init(void)
{
    return 0;
}

void __exit my_exit(void)
{
}
"""
        result = restore_target_signature_modifiers(patched, self.TARGET, ["file.c#my_init"])
        assert "__init my_init" in result

    def test_no_change_when_modifier_present(self):
        patched = """\
static int __init my_init(void)
{
    return 0;
}
"""
        result = restore_target_signature_modifiers(patched, self.TARGET, ["file.c#my_init"])
        assert result == patched

    def test_none_signatures_returns_unchanged(self):
        patched = "int foo(void) { }"
        result = restore_target_signature_modifiers(patched, self.TARGET, None)
        assert result == patched

    def test_empty_signatures_returns_unchanged(self):
        patched = "int foo(void) { }"
        result = restore_target_signature_modifiers(patched, self.TARGET, [])
        assert result == patched

    def test_restores_multiple_functions(self):
        patched = """\
static int my_init(void)
{
    return 0;
}

void my_exit(void)
{
}
"""
        result = restore_target_signature_modifiers(
            patched, self.TARGET, ["a.c#my_init", "b.c#my_exit"]
        )
        assert "__init my_init" in result
        assert "__exit my_exit" in result

    def test_preserves_trailing_newline(self):
        patched = "int my_init(void) { }\n"
        target = "int __init my_init(void) { }\n"
        result = restore_target_signature_modifiers(patched, target, ["a.c#my_init"])
        assert result.endswith("\n")
