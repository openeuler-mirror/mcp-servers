"""根据 checkpatch 精确诊断，对补丁变化区域进行一次保守的格式修复重试。

本模块只接收白名单中的纯格式问题，将诊断反馈给局部格式化流程，并由调用方
重新运行 checkpatch；若问题数量没有减少，则继续保留重试前的代码。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from collections.abc import Callable

import llm
from changed_region_formatter import normalize_changed_regions
from func_parser import parse_functions


FormatGenerator = Callable[[str], str | None]

_DIAGNOSTIC_RE = re.compile(
    r"^(?P<level>ERROR|WARNING|CHECK): (?P<message>.+?)\n"
    r"#\d+: FILE: (?P<file>.+?):(?P<line>\d+):$",
    re.MULTILINE,
)
_FORMAT_ONLY_MESSAGES = {
    "Lines should not end with a '('",
    "Missing a blank line after declarations",
    "Block comments should align the * on each line",
    "Please use a blank line after function/struct/union/enum declarations",
    "labels should not be indented",
    "open brace '{' following function definitions go on the next line",
}
_FORMAT_ONLY_MESSAGE_PREFIXES = (
    "suspect code indent for conditional statements",
    "line length of ",
)
_DECLARATION_BLANK_LINE_MESSAGE = (
    "Please use a blank line after function/struct/union/enum declarations"
)
_LINE_ENDS_WITH_OPEN_PAREN_MESSAGE = "Lines should not end with a '('"
_MISSING_BLANK_LINE_AFTER_DECLARATIONS = "Missing a blank line after declarations"
_BLOCK_COMMENT_ALIGN_MESSAGE = "Block comments should align the * on each line"
_LABELS_INDENTED_MESSAGE = "labels should not be indented"
_DECLARATION_START_RE = re.compile(
    r"^\s*(?:struct|union|enum)\b|^\s*(?:static\s+)?[A-Za-z_][\w\s\*]*\([^;]*\)\s*\{?\s*$"
)
_C_DECLARATION_RE = re.compile(
    r"^\s*(?:"
    r"(?:const\s+|volatile\s+|static\s+|unsigned\s+|signed\s+|long\s+|short\s+)*"
    r"(?:struct\s+\w+|union\s+\w+|enum\s+\w+|bool|char|u8|u16|u32|u64|s8|s16|s32|s64|"
    r"int|unsigned|size_t|ssize_t|void|dma_addr_t|phys_addr_t|uintptr_t|"
    r"[A-Za-z_]\w*(?:_t)?)"
    r"(?:\s+|\s*\*)"
    r"[A-Za-z_]\w*"
    r")"
    r".*;\s*$"
)
_CONTROL_OR_STATEMENT_RE = re.compile(
    r"^\s*(?:if|for|while|switch|return|goto|break|continue|case|default|else|do)\b"
)
# 用于修复 labels should not be indented，把 err: 这类 label 顶到行首
_LABEL_RE = re.compile(r"^\s+([A-Za-z_]\w*:\s*(?:/\*.*\*/\s*)?)$")


def _is_format_only_message(message: str) -> bool:
    """Return whether a known checkpatch diagnostic needs whitespace changes only."""
    return (
        message in _FORMAT_ONLY_MESSAGES
        or any(message.startswith(prefix) for prefix in _FORMAT_ONLY_MESSAGE_PREFIXES)
    )


@dataclass(frozen=True)
class CheckpatchDiagnostic:
    level: str
    message: str
    file: str
    line: int


def run_checkpatch(checkpatch_path: str, patch_text: str) -> tuple[int, str]:
    """Run checkpatch against patch text without modifying the target repository."""
    patch_file = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as handle:
            handle.write(patch_text)
            patch_file = handle.name
        result = subprocess.run(
            [checkpatch_path, "--no-tree", "--strict", patch_file],
            capture_output=True,
            text=True,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except OSError as exc:
        logging.warning("Could not run target repository checkpatch.pl: %s", exc)
        return 1, ""
    finally:
        if patch_file:
            try:
                os.unlink(patch_file)
            except OSError:
                pass


def parse_code_style_diagnostics(
    checkpatch_output: str,
    target_file_path: str,
) -> list[CheckpatchDiagnostic]:
    """Extract diagnostics tied to concrete lines in the current target file."""
    return [
        item
        for item in parse_target_diagnostics(checkpatch_output, target_file_path)
        if _is_format_only_message(item.message)
    ]


def parse_target_diagnostics(
    checkpatch_output: str,
    target_file_path: str,
) -> list[CheckpatchDiagnostic]:
    """Extract all checkpatch diagnostics tied to the current target file."""
    diagnostics: list[CheckpatchDiagnostic] = []
    for match in _DIAGNOSTIC_RE.finditer(checkpatch_output):
        file_path = match.group("file")
        if file_path != target_file_path:
            continue
        message = match.group("message")
        diagnostics.append(
            CheckpatchDiagnostic(
                level=match.group("level"),
                message=message,
                file=file_path,
                line=int(match.group("line")),
            )
        )
    return diagnostics


def apply_deterministic_checkpatch_fixes(
    patched_code: str,
    diagnostics: list[CheckpatchDiagnostic],
    fix_kind: str | None = None,
) -> str:
    """Apply narrow, non-LLM fixes for checkpatch diagnostics with exact locations."""
    lines = patched_code.split("\n")
    insert_indexes: set[int] = set()
    deindent_lines: set[int] = set()
    merge_open_paren_lines: set[int] = set()
    for diagnostic in diagnostics:
        if (
            diagnostic.message == _LINE_ENDS_WITH_OPEN_PAREN_MESSAGE
            and fix_kind in {None, "line_delete"}
        ):
            merge_open_paren_lines.add(diagnostic.line - 1)
            continue
        if (
            diagnostic.message == _LABELS_INDENTED_MESSAGE
            and fix_kind in {None, "non_line_count"}
        ):
            line_index = diagnostic.line - 1
            if 0 <= line_index < len(lines) and _LABEL_RE.match(lines[line_index]):
                deindent_lines.add(line_index)
            continue
        if (
            diagnostic.message == _BLOCK_COMMENT_ALIGN_MESSAGE
            and fix_kind in {None, "non_line_count"}
        ):
            _fix_block_comment_alignment(lines, diagnostic.line - 1)
            continue
        if fix_kind not in {None, "line_insert"}:
            continue
        if diagnostic.message == _MISSING_BLANK_LINE_AFTER_DECLARATIONS:
            line_index = diagnostic.line - 1
            if _should_insert_blank_after_function_declarations(lines, line_index):
                insert_indexes.add(line_index)
            continue
        if diagnostic.message != _DECLARATION_BLANK_LINE_MESSAGE:
            continue
        center = diagnostic.line - 1
        for index in range(max(1, center - 2), min(len(lines), center + 3)):
            if _should_insert_declaration_blank_line(lines, index):
                insert_indexes.add(index)
                break
    
    # 先处理不改变行数的 label
    for index in deindent_lines:
        match = _LABEL_RE.match(lines[index])
        if match:
            lines[index] = match.group(1)

    merged = 0
    # 处理会删除一行的 open paren
    for index in sorted(merge_open_paren_lines, reverse=True):
        if _fix_line_ending_with_open_paren(lines, index):
            merged += 1

    inserted = 0
    # 处理会插入空行的 blank line，倒序处理
    for index in sorted(insert_indexes, reverse=True):
        lines.insert(index, "")
        inserted += 1

    if inserted:
        logging.info(
            "Applied %d deterministic checkpatch blank line fix(es)",
            inserted,
        )
    if deindent_lines:
        logging.info(
            "Applied %d deterministic checkpatch label indentation fix(es)",
            len(deindent_lines),
        )
    if merged:
        logging.info(
            "Applied %d deterministic checkpatch open-paren line fix(es)",
            merged,
        )
    return "\n".join(lines)


def apply_function_level_clang_format_for_diagnostics(
    patched_code: str,
    repo_path: str,
    target_file_path: str,
    diagnostics: list[CheckpatchDiagnostic],
    allowed_function_names: list[str] | set[str] | tuple[str, ...] | None = None,
) -> str:
    """Format whole successful functions that contain checkpatch style diagnostics."""
    function_names = _function_names_for_diagnostics(
        patched_code,
        diagnostics,
        allowed_function_names,
    )
    if not function_names:
        return patched_code

    return apply_function_level_clang_format_for_functions(
        patched_code,
        repo_path,
        target_file_path,
        function_names,
    )


def apply_function_level_clang_format_for_functions(
    patched_code: str,
    repo_path: str,
    target_file_path: str,
    function_names: list[str] | set[str] | tuple[str, ...] | None,
) -> str:
    """Format whole named functions with the target repository clang-format."""
    names = {
        item.rsplit("#", 1)[-1]
        for item in function_names or ()
    }
    if not names:
        return patched_code

    style_path = os.path.join(repo_path, ".clang-format")
    clang_format = shutil.which("clang-format")
    if not os.path.isfile(style_path):
        logging.info("Skipping function-level clang-format: target repository has no .clang-format")
        return patched_code
    if clang_format is None:
        logging.info("Skipping function-level clang-format: clang-format executable not found")
        return patched_code

    functions = [
        function
        for function in parse_functions(patched_code)
        if function.name in names
    ]
    if not functions:
        return patched_code

    command = [
        clang_format,
        "--style=file",
        f"--assume-filename={os.path.join(repo_path, target_file_path)}",
    ]
    command.extend(
        f"--lines={function.start_line}:{function.end_line}"
        for function in sorted(functions, key=lambda item: item.start_line)
    )
    try:
        result = subprocess.run(
            command,
            input=patched_code,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logging.warning(
            "Function-level clang-format failed: %s",
            (exc.stderr or str(exc)).strip()[:500],
        )
        return patched_code

    formatted = result.stdout
    validation = llm.validate_formatting.invoke({
        "original_code": patched_code,
        "formatted_code": formatted,
    })
    if validation:
        logging.warning(
            "Function-level clang-format changed code content, rejected: %s",
            str(validation)[:300],
        )
        return patched_code

    logging.info(
        "Applied function-level clang-format to %d function(s): %s",
        len(functions),
        ", ".join(sorted(function.name for function in functions)),
    )
    return formatted


def _function_names_for_diagnostics(
    patched_code: str,
    diagnostics: list[CheckpatchDiagnostic],
    allowed_function_names: list[str] | set[str] | tuple[str, ...] | None = None,
) -> set[str]:
    """Return allowed function names whose ranges contain reported diagnostics."""
    allowed_names = {
        item.rsplit("#", 1)[-1]
        for item in allowed_function_names or ()
    }
    line_numbers = {
        diagnostic.line
        for diagnostic in diagnostics
    }
    if not line_numbers:
        return set()

    names: set[str] = set()
    for function in parse_functions(patched_code):
        if allowed_names and function.name not in allowed_names:
            continue
        if any(function.start_line <= line <= function.end_line for line in line_numbers):
            names.add(function.name)
    return names


def _should_insert_declaration_blank_line(lines: list[str], index: int) -> bool:
    """判断是否应该修复 Please use a blank line after function/struct/union/enum declarations，
        即顶层 declaration/function/struct/union/enum 之间缺空行"""
    if index <= 0 or index >= len(lines):
        return False
    if not lines[index].strip() or not lines[index - 1].strip():
        return False
    previous = lines[index - 1].strip()
    current = lines[index]
    return previous in {"};", "}"} and bool(_DECLARATION_START_RE.match(current))


def _should_insert_blank_after_function_declarations(lines: list[str], index: int) -> bool:
    """判断是否应该修复 Missing a blank line after declarations，
        即局部变量声明结束后、普通语句前缺空行"""
    if index <= 0 or index >= len(lines):
        return False
    current = lines[index]
    previous = lines[index - 1]
    if not current.strip() or not previous.strip():
        return False
    if current.lstrip().startswith(("#", "}", "/*", "*", "//")):
        return False
    if not _C_DECLARATION_RE.match(previous):
        return False
    if _C_DECLARATION_RE.match(current) and not _CONTROL_OR_STATEMENT_RE.match(current):
        return False
    return bool(_CONTROL_OR_STATEMENT_RE.match(current) or "=" in current or "(" in current)


def _fix_block_comment_alignment(lines: list[str], line_index: int) -> None:
    """修复 Block comments should align the * on each line，把块注释里的 * 对齐到 /* 的缩进"""
    if not (0 <= line_index < len(lines)):
        return
    start = line_index
    while start >= 0 and "/*" not in lines[start]:
        if "*/" in lines[start]:
            return
        start -= 1
    if start < 0:
        return
    opener = re.match(r"^(\s*)/\*", lines[start])
    if not opener:
        return
    aligned_prefix = opener.group(1) + " "
    end = line_index
    while end < len(lines):
        if re.match(r"^\s*\*", lines[end]):
            lines[end] = re.sub(r"^\s*(?=\*)", aligned_prefix, lines[end])
        if "*/" in lines[end]:
            break
        end += 1


def _fix_line_ending_with_open_paren(lines: list[str], line_index: int) -> bool:
    """修复 Lines should not end with a '('，把下一行第一个参数合并到函数调用行。"""
    if not (0 <= line_index < len(lines) - 1):
        return False
    line = lines[line_index]
    if not line.rstrip().endswith("("):
        return False

    next_index = line_index + 1
    if not lines[next_index].strip():
        return False
    next_line = lines[next_index]
    next_stripped = next_line.strip()
    if next_stripped.startswith(("#", "/*", "//", "*")):
        return False

    lines[line_index] = line.rstrip() + next_stripped
    del lines[next_index]
    _align_call_continuation_lines(lines, line_index)
    return True


def _align_call_continuation_lines(lines: list[str], call_line_index: int) -> None:
    """Align continued call arguments to the column after the opening parenthesis."""
    call_line = lines[call_line_index]
    open_paren = call_line.rfind("(")
    if open_paren < 0:
        return
    target_column = _visual_column(call_line[:open_paren + 1])
    prefix = "\t" * (target_column // 8) + " " * (target_column % 8)

    depth = call_line.count("(") - call_line.count(")")
    index = call_line_index + 1
    while index < len(lines) and depth > 0:
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        lines[index] = prefix + stripped
        depth += stripped.count("(") - stripped.count(")")
        index += 1


def _visual_column(text: str, tab_width: int = 8) -> int:
    column = 0
    for char in text:
        if char == "\t":
            column += tab_width - (column % tab_width)
        else:
            column += 1
    return column


def refine_with_checkpatch_feedback(
    target_content: str,
    patched_code: str,
    target_file_path: str,
    file_signatures: list[str] | None,
    diagnostics: list[CheckpatchDiagnostic],
    *,
    generate: FormatGenerator | None = None,
) -> str:
    """Retry changed-region formatting with concrete checkpatch feedback."""
    if not diagnostics:
        return patched_code

    feedback = "\n".join(
        f"- {item.level}: {item.message} ({item.file}:{item.line})"
        for item in diagnostics
    )

    def generate_with_feedback(prompt: str) -> str | None:
        augmented_prompt = f"""\
The final patch was checked by Linux scripts/checkpatch.pl.
Fix only formatting issues that apply to EDITABLE_CODE. If none apply, return
EDITABLE_CODE unchanged. Preserve every non-whitespace character exactly.
Follow Linux kernel C style while fixing diagnostics:
- For "suspect code indent for conditional statements", indent statements
  inside if/else/for/while/switch blocks one tab level deeper than the
  controlling statement and keep closing braces aligned with their opener.
- For "Please use a blank line after function/struct/union/enum declarations",
  insert exactly one blank line between adjacent top-level declarations.
- Preserve existing blank lines that separate declarations, checks, loops,
  returns, and logical statement groups unless a listed diagnostic requires
  changing that specific gap.

=== CHECKPATCH_DIAGNOSTICS ===
{feedback}

{prompt}
"""
        if generate is not None:
            return generate(augmented_prompt)
        return llm.llm_generate(
            augmented_prompt,
            temperature=0,
            system_message=(
                "You are a Linux kernel code formatting expert. Fix only the "
                "reported checkpatch formatting issues and preserve every "
                "non-whitespace character exactly."
            ),
        )

    refined = normalize_changed_regions(
        patched_code,
        target_content,
        file_signatures,
        generate=generate_with_feedback,
    )
    validation = llm.validate_formatting.invoke({
        "original_code": patched_code,
        "formatted_code": refined,
    })
    if validation:
        logging.warning(
            "Checkpatch-guided formatting changed code content, rejected: %s",
            str(validation)[:300],
        )
        return patched_code
    return refined
