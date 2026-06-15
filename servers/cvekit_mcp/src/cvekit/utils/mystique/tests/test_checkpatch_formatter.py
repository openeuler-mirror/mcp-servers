"""Tests for checkpatch_formatter — pure functions only."""
import pytest

# conftest.py mocks llm before import
from checkpatch_formatter import (
    _is_format_only_message,
    CheckpatchDiagnostic,
    _DIAGNOSTIC_RE,
    parse_code_style_diagnostics,
)


class TestIsFormatOnlyMessage:
    def test_known_format_messages(self):
        assert _is_format_only_message("Lines should not end with a '('")
        assert _is_format_only_message("Missing a blank line after declarations")
        assert _is_format_only_message("Block comments should align the * on each line")
        assert _is_format_only_message("labels should not be indented")
        assert _is_format_only_message("open brace '{' following function definitions go on the next line")

    def test_unknown_message(self):
        assert not _is_format_only_message("some random error")

    def test_empty_message(self):
        assert not _is_format_only_message("")


class TestCheckpatchDiagnostic:
    def test_creation(self):
        d = CheckpatchDiagnostic(level="ERROR", message="bad thing", file="foo.c", line=42)
        assert d.level == "ERROR"
        assert d.message == "bad thing"
        assert d.file == "foo.c"
        assert d.line == 42

    def test_frozen(self):
        d = CheckpatchDiagnostic(level="WARNING", message="msg", file="f.c", line=1)
        with pytest.raises(Exception):
            d.line = 99  # type: ignore[misc]

    def test_equality(self):
        a = CheckpatchDiagnostic("WARNING", "msg", "f.c", 1)
        b = CheckpatchDiagnostic("WARNING", "msg", "f.c", 1)
        assert a == b

    def test_inequality(self):
        a = CheckpatchDiagnostic("WARNING", "msg", "f.c", 1)
        b = CheckpatchDiagnostic("ERROR", "msg", "f.c", 1)
        assert a != b


class TestDiagnosticRegex:
    def test_matches_checkpatch_output(self):
        output = """\
WARNING: Missing a blank line after declarations
#42: FILE: net/core/dev.c:1337:
+       int ret = 0;
+       spin_lock(&lock);

total: 0 errors, 1 warnings, 0 checks"""
        match = _DIAGNOSTIC_RE.search(output)
        assert match is not None
        assert match.group("level") == "WARNING"
        assert match.group("message") == "Missing a blank line after declarations"
        assert match.group("file") == "net/core/dev.c"
        assert match.group("line") == "1337"

    def test_multiple_diagnostics(self):
        output = """\
ERROR: Lines should not end with a '('
#10: FILE: foo.c:5:
WARNING: labels should not be indented
#11: FILE: foo.c:20:"""
        matches = _DIAGNOSTIC_RE.findall(output)
        assert len(matches) == 2


class TestParseCodeStyleDiagnostics:
    def test_filters_by_target_file(self):
        output = """\
WARNING: Missing a blank line after declarations
#42: FILE: foo.c:10:
WARNING: labels should not be indented
#43: FILE: bar.c:20:"""
        diags = parse_code_style_diagnostics(output, "foo.c")
        assert len(diags) == 1
        assert diags[0].file == "foo.c"
        assert diags[0].line == 10

    def test_filters_non_format_messages(self):
        output = """\
ERROR: some random logic error
#42: FILE: foo.c:10:"""
        diags = parse_code_style_diagnostics(output, "foo.c")
        assert len(diags) == 0

    def test_empty_output(self):
        assert parse_code_style_diagnostics("", "foo.c") == []

    def test_no_matching_file(self):
        output = """\
WARNING: Missing a blank line after declarations
#42: FILE: other.c:10:"""
        diags = parse_code_style_diagnostics(output, "foo.c")
        assert len(diags) == 0
