"""根据 checkpatch 精确诊断，对补丁变化区域进行一次保守的格式修复重试。

本模块只接收白名单中的纯格式问题，将诊断反馈给局部格式化流程，并由调用方
重新运行 checkpatch；若问题数量没有减少，则继续保留重试前的代码。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from collections.abc import Callable

import llm
from changed_region_formatter import normalize_changed_regions


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
    "labels should not be indented",
    "open brace '{' following function definitions go on the next line",
}


def _is_format_only_message(message: str) -> bool:
    """Return whether a known checkpatch diagnostic needs whitespace changes only."""
    return message in _FORMAT_ONLY_MESSAGES


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
    diagnostics: list[CheckpatchDiagnostic] = []
    for match in _DIAGNOSTIC_RE.finditer(checkpatch_output):
        file_path = match.group("file")
        if file_path != target_file_path:
            continue
        message = match.group("message")
        if not _is_format_only_message(message):
            continue
        diagnostics.append(
            CheckpatchDiagnostic(
                level=match.group("level"),
                message=message,
                file=file_path,
                line=int(match.group("line")),
            )
        )
    return diagnostics


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
