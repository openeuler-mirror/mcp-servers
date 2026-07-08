"""Formatting pipeline for Mystique backport output.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

import config
from common import Language


GeneratePatch = Callable[[str], str | None]


@dataclass(frozen=True)
class CheckpatchRefinementResult:
    code: str
    diff: str | None
    changed: bool = False


def normalize_patched_formatting(
    patched_code: str,
    target_content: str,
    language: Language,
    file_signatures: list[str] | None = None,
    successful_target_names: list[str] | None = None,
    target_path: str | None = None,
    target_file_path: str | None = None,
    file_patch: str | None = None,
) -> str:
    """Normalize patched C code with the changed-region formatting pipeline."""
    if language != Language.C:
        logging.info("Skipping format normalization for non-C language: %s", language.value)
        return patched_code

    if config.FORMAT_NORMALIZATION_MODE != "changed_regions":
        return patched_code

    from changed_region_formatter import (
        apply_repo_clang_format,
        normalize_changed_regions,
        restore_patch_added_blank_lines,
        restore_target_blank_lines_around_changed_regions,
    )

    logging.info("Using changed-region LLM format normalization")
    format_signatures = (
        [f"3.target.c#{name}" for name in successful_target_names]
        if successful_target_names else file_signatures
    )
    normalized = normalize_changed_regions(
        patched_code,
        target_content,
        format_signatures,
    )
    if target_path and target_file_path:
        normalized = apply_repo_clang_format(
            normalized,
            target_content,
            target_path,
            target_file_path,
            allowed_function_names=successful_target_names,
        )
    normalized = restore_target_blank_lines_around_changed_regions(
        normalized,
        target_content,
        allowed_function_names=successful_target_names,
    )
    return restore_patch_added_blank_lines(
        normalized,
        file_patch,
        allowed_function_names=successful_target_names,
    )


def refine_with_checkpatch_pipeline(
    patched_code: str,
    patch_diff: str | None,
    target_content: str,
    target_path: str,
    target_file_path: str,
    file_signatures: list[str] | None,
    successful_target_names: list[str] | None,
    file_patch: str | None,
    generate_patch: GeneratePatch,
) -> CheckpatchRefinementResult:
    """Run checkpatch-guided formatting and accept only improved results."""
    checkpatch_path = os.path.join(target_path, "scripts", "checkpatch.pl")
    if (
        not patch_diff
        or config.FORMAT_NORMALIZATION_MODE != "changed_regions"
        or not os.path.isfile(checkpatch_path)
    ):
        return CheckpatchRefinementResult(patched_code, patch_diff, changed=False)

    from changed_region_formatter import (
        apply_repo_clang_format,
        restore_patch_added_blank_lines,
        restore_reference_blank_lines_around_changed_regions,
        restore_target_blank_lines_around_changed_regions,
    )
    from checkpatch_formatter import (
        _function_names_for_diagnostics,
        apply_deterministic_checkpatch_fixes,
        apply_function_level_clang_format_for_diagnostics,
        parse_target_diagnostics,
        refine_with_checkpatch_feedback,
        run_checkpatch,
    )

    pre_formatted = _try_function_level_clang_format_pass(
        patched_code,
        patch_diff,
        target_file_path,
        generate_patch,
        repo_path=target_path,
        function_format_names=successful_target_names,
    )
    pre_format_changed = pre_formatted.changed
    if pre_format_changed:
        patched_code = pre_formatted.code
        patch_diff = pre_formatted.diff

    _, checkpatch_output = run_checkpatch(checkpatch_path, patch_diff)
    diagnostics = parse_target_diagnostics(
        checkpatch_output,
        target_file_path,
    )
    if not diagnostics:
        return CheckpatchRefinementResult(
            patched_code,
            patch_diff,
            changed=pre_format_changed,
        )

    logging.info(
        "Checkpatch-guided formatting will address %d %s issue(s): %s",
        len(diagnostics),
        target_file_path,
        "; ".join(
            f"{item.level}: {item.message} (line {item.line})"
            for item in diagnostics
        ),
    )
    diagnostic_function_names = sorted(
        _function_names_for_diagnostics(
            patched_code,
            diagnostics,
            allowed_function_names=successful_target_names,
        )
    )
    formatting_target_names = diagnostic_function_names or successful_target_names
    if diagnostic_function_names:
        logging.info(
            "Checkpatch-guided formatting limited to diagnostic function(s): %s",
            ", ".join(diagnostic_function_names),
        )
    deterministic_first = _try_deterministic_checkpatch_pass(
        patched_code,
        patch_diff,
        diagnostics,
        diagnostics,
        checkpatch_path,
        target_file_path,
        generate_patch,
        label="Deterministic first formatting",
    )
    if deterministic_first.changed:
        patched_code = deterministic_first.code
        patch_diff = deterministic_first.diff
        _, checkpatch_output = run_checkpatch(
            checkpatch_path,
            patch_diff or "",
        )
        diagnostics = parse_target_diagnostics(
            checkpatch_output,
            target_file_path,
        )
        if not diagnostics:
            return deterministic_first
        diagnostic_function_names = sorted(
            _function_names_for_diagnostics(
                patched_code,
                diagnostics,
                allowed_function_names=successful_target_names,
            )
        )
        formatting_target_names = diagnostic_function_names or successful_target_names

    refine_signatures = (
        [f"3.target.c#{name}" for name in formatting_target_names]
        if formatting_target_names else file_signatures
    )
    refined_code = refine_with_checkpatch_feedback(
        target_content,
        patched_code,
        target_file_path,
        refine_signatures,
        diagnostics,
    )
    refined_code = apply_repo_clang_format(
        refined_code,
        target_content,
        target_path,
        target_file_path,
        allowed_function_names=formatting_target_names,
    )
    refined_code = apply_function_level_clang_format_for_diagnostics(
        refined_code,
        target_path,
        target_file_path,
        diagnostics,
        allowed_function_names=formatting_target_names,
    )
    refined_code = restore_reference_blank_lines_around_changed_regions(
        refined_code,
        patched_code,
        label="pre-checkpatch",
        allowed_function_names=formatting_target_names,
    )
    refined_code = restore_target_blank_lines_around_changed_regions(
        refined_code,
        target_content,
        allowed_function_names=formatting_target_names,
    )
    refined_code = restore_patch_added_blank_lines(
        refined_code,
        file_patch,
        allowed_function_names=formatting_target_names,
    )
    refined_code = apply_deterministic_checkpatch_fixes(
        refined_code,
        diagnostics,
    )
    refined_diff = generate_patch(refined_code)
    if not refined_diff:
        return CheckpatchRefinementResult(patched_code, patch_diff, changed=False)

    _, refined_checkpatch_output = run_checkpatch(
        checkpatch_path,
        refined_diff,
    )
    refined_diagnostics = parse_target_diagnostics(
        refined_checkpatch_output,
        target_file_path,
    )
    deterministic_final = _try_deterministic_checkpatch_pass(
        refined_code,
        refined_diff,
        refined_diagnostics,
        refined_diagnostics,
        checkpatch_path,
        target_file_path,
        generate_patch,
        label="Deterministic final formatting",
    )
    if deterministic_final.changed:
        refined_code = deterministic_final.code
        refined_diff = deterministic_final.diff
        _, refined_checkpatch_output = run_checkpatch(
            checkpatch_path,
            refined_diff or "",
        )
        refined_diagnostics = parse_target_diagnostics(
            refined_checkpatch_output,
            target_file_path,
        )

    original_diagnostic_keys = {
        (item.level, item.message) for item in diagnostics
    }
    introduced_diagnostics = [
        item
        for item in refined_diagnostics
        if (item.level, item.message) not in original_diagnostic_keys
    ]
    if len(refined_diagnostics) < len(diagnostics) and not introduced_diagnostics:
        logging.info(
            "Checkpatch-guided formatting reduced %s issues from %d to %d",
            target_file_path,
            len(diagnostics),
            len(refined_diagnostics),
        )
        return CheckpatchRefinementResult(refined_code, refined_diff, changed=True)

    if introduced_diagnostics:
        logging.info(
            "Checkpatch-guided formatting introduced new %s diagnostics "
            "for %s; keeping previous formatting",
            len(introduced_diagnostics),
            target_file_path,
        )
    logging.info(
        "Checkpatch-guided formatting did not reduce issues for %s; "
        "keeping previous formatting",
        target_file_path,
    )
    return CheckpatchRefinementResult(patched_code, patch_diff, changed=False)


def _try_deterministic_checkpatch_pass(
    code: str,
    diff: str | None,
    diagnostics: list,
    all_diagnostics: list,
    checkpatch_path: str,
    target_file_path: str,
    generate_patch: GeneratePatch,
    *,
    label: str,
) -> CheckpatchRefinementResult:
    """Apply deterministic style fixes and accept only if checkpatch improves."""
    if not diagnostics:
        return CheckpatchRefinementResult(code, diff, changed=False)

    from checkpatch_formatter import (
        apply_deterministic_checkpatch_fixes,
        parse_target_diagnostics,
        run_checkpatch,
    )

    original_keys = {
        (item.level, item.message) for item in all_diagnostics
    }
    current_code = code
    current_diff = diff
    current_diagnostics = diagnostics
    changed = False
    max_passes = 8

    for _ in range(max_passes):
        accepted = False
        # 为防止修改行号偏移，每轮只接受一种会改变行数的确定性修复。
        for fix_kind in ("non_line_count", "line_delete", "line_insert"):
            candidate_code = apply_deterministic_checkpatch_fixes(
                current_code,
                current_diagnostics,
                fix_kind=fix_kind,
            )
            if candidate_code == current_code:
                continue

            candidate_diff = generate_patch(candidate_code)
            if not candidate_diff:
                continue

            _, candidate_checkpatch_output = run_checkpatch(
                checkpatch_path,
                candidate_diff,
            )
            candidate_diagnostics = parse_target_diagnostics(
                candidate_checkpatch_output,
                target_file_path,
            )
            introduced = [
                item
                for item in candidate_diagnostics
                if (item.level, item.message) not in original_keys
            ]
            if introduced or len(candidate_diagnostics) >= len(current_diagnostics):
                continue

            current_code = candidate_code
            current_diff = candidate_diff
            current_diagnostics = candidate_diagnostics
            changed = True
            accepted = True
            break

        if not accepted or not current_diagnostics:
            break

    if changed:
        logging.info(
            "%s reduced %s issues from %d to %d%s",
            label,
            target_file_path,
            len(diagnostics),
            len(current_diagnostics),
            "" if not current_diagnostics else "; continuing refinement for remaining issues",
        )
        return CheckpatchRefinementResult(
            current_code,
            current_diff,
            changed=True,
        )

    return CheckpatchRefinementResult(code, diff, changed=False)


def _try_function_level_clang_format_pass(
    code: str,
    diff: str | None,
    target_file_path: str,
    generate_patch: GeneratePatch,
    *,
    repo_path: str | None,
    function_format_names: list[str] | set[str] | tuple[str, ...] | None,
) -> CheckpatchRefinementResult:
    """Run whole-function clang-format before checkpatch-guided cleanup."""
    if not (repo_path and function_format_names):
        return CheckpatchRefinementResult(code, diff, changed=False)

    from checkpatch_formatter import (
        apply_function_level_clang_format_for_functions,
    )

    formatted_code = apply_function_level_clang_format_for_functions(
        code,
        repo_path,
        target_file_path,
        function_format_names,
    )
    if formatted_code == code:
        return CheckpatchRefinementResult(code, diff, changed=False)

    formatted_diff = generate_patch(formatted_code)
    if not formatted_diff:
        return CheckpatchRefinementResult(code, diff, changed=False)

    logging.info(
        "Function-level clang-format pre-pass accepted for %s",
        target_file_path,
    )
    return CheckpatchRefinementResult(
        formatted_code,
        formatted_diff,
        changed=True,
    )
