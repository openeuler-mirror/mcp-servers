"""仅格式化补丁变化区域，并保留目标仓库中的原始代码。

本模块通过比较目标函数和回移植后的函数，保留相同区域，只把新增或替换
区域交给大模型；同时负责局部 clang-format 和上游新增空行恢复。
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable

import llm
from ast_parser import ASTParser
from common import Language
from func_parser import parse_functions_with_tree_sitter


FormatGenerator = Callable[[str], str | None]


def _restore_equivalent_function_header(
    target_lines: list[str],
    patched_lines: list[str],
) -> list[str]:
    """Use the target header when only its whitespace/brace style differs."""
    target_brace = next(
        (index for index, line in enumerate(target_lines) if "{" in line),
        None,
    )
    patched_brace = next(
        (index for index, line in enumerate(patched_lines) if "{" in line),
        None,
    )
    if target_brace is None or patched_brace is None:
        return patched_lines

    target_header = target_lines[:target_brace + 1]
    patched_header = patched_lines[:patched_brace + 1]
    target_key = re.sub(r"\s+", "", "\n".join(target_header))
    patched_key = re.sub(r"\s+", "", "\n".join(patched_header))
    if target_key != patched_key:
        return patched_lines

    return target_header + patched_lines[patched_brace + 1:]


def _line_match_key(line: str) -> str:
    """Remove formatting whitespace while preserving literal/comment content."""
    out: list[str] = []
    quote: str | None = None
    escaped = False
    i = 0

    while i < len(line):
        ch = line[i]
        next_ch = line[i + 1] if i + 1 < len(line) else ""

        if quote is not None:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch in {'"', "'"}:
            quote = ch
            out.append(ch)
        elif ch == "/" and next_ch in {"/", "*"}:
            out.append(line[i:])
            break
        elif not ch.isspace():
            out.append(ch)
        i += 1

    return "".join(out)


def _clean_llm_result(result: str) -> str:
    cleaned = re.sub(r"<antThinking>.*?</antThinking>", "", result, flags=re.DOTALL)
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<\|begin_thinking\|>.*?<\|end_thinking\|>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"^```(?:c|C|cpp|CPP)?\s*\n", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n```\s*$", "", cleaned, flags=re.DOTALL)
    return cleaned.strip("\n")


def _default_generate(prompt: str) -> str | None:
    return llm.llm_generate(
        prompt,
        temperature=0,
        system_message=(
            "You are a C code formatting expert. Format only the editable code "
            "region. Preserve every non-whitespace character exactly."
        ),
    )


def _format_region(
    patched_lines: list[str],
    before_context: list[str],
    after_context: list[str],
    generate: FormatGenerator,
) -> list[str]:
    """Format one changed region, falling back to the original region."""
    if not patched_lines or not any(line.strip() for line in patched_lines):
        return patched_lines

    patched_region = "\n".join(patched_lines)
    prompt = f"""\
Format only EDITABLE_CODE so it matches the surrounding TARGET context.

You may change whitespace, indentation, and line breaks only.
Never change identifiers, literals, comments, operators, braces, or statements.
Output only EDITABLE_CODE after formatting. Do not output the context.

=== TARGET_CONTEXT_BEFORE (read only) ===
{chr(10).join(before_context)}

=== EDITABLE_CODE ===
{patched_region}

=== TARGET_CONTEXT_AFTER (read only) ===
{chr(10).join(after_context)}
"""

    try:
        result = generate(prompt)
    except Exception as exc:
        logging.warning("Changed-region formatter LLM failed: %s", exc)
        return patched_lines

    if not result:
        logging.warning("Changed-region formatter returned empty output")
        return patched_lines

    cleaned = _clean_llm_result(result)
    if not cleaned:
        logging.warning("Changed-region formatter returned empty cleaned output")
        return patched_lines

    validation = llm.validate_formatting.invoke({
        "original_code": patched_region,
        "formatted_code": cleaned,
    })
    if validation:
        logging.warning(
            "Changed-region formatter rejected region: %s",
            str(validation)[:300],
        )
        return patched_lines

    return cleaned.split("\n")


def _extract_marked_regions(result: str, count: int) -> list[list[str]] | None:
    """Extract editable regions from a grouped formatter response."""
    lines = result.split("\n")
    regions: list[list[str]] = []

    for index in range(count):
        start = f"/* MYSTIQUE_EDITABLE_{index}_START */"
        end = f"/* MYSTIQUE_EDITABLE_{index}_END */"
        try:
            start_index = next(i for i, line in enumerate(lines) if line.strip() == start)
            end_index = next(
                i for i, line in enumerate(lines[start_index + 1:], start_index + 1)
                if line.strip() == end
            )
        except StopIteration:
            return None
        regions.append(lines[start_index + 1:end_index])

    return regions


def _format_control_flow_group(
    editable_regions: list[list[str]],
    readonly_lines: list[str],
    before_context: list[str],
    after_context: list[str],
    generate: FormatGenerator,
) -> list[str] | None:
    """Format edits around read-only control flow in one LLM request."""
    marked_parts: list[str] = []
    for index, region in enumerate(editable_regions):
        marked_parts.append(f"/* MYSTIQUE_EDITABLE_{index}_START */")
        marked_parts.extend(region)
        marked_parts.append(f"/* MYSTIQUE_EDITABLE_{index}_END */")
        if index == 0:
            marked_parts.append("/* MYSTIQUE_READ_ONLY_START */")
            marked_parts.extend(readonly_lines)
            marked_parts.append("/* MYSTIQUE_READ_ONLY_END */")

    prompt = f"""\
Format the editable regions so they match the surrounding TARGET context.

The read-only region shows the complete control-flow structure between edits.
Use it to determine indentation, but never change it.
Preserve every MYSTIQUE marker and output the complete marked code only.
You may change whitespace and line breaks inside editable regions only.

=== TARGET_CONTEXT_BEFORE (read only) ===
{chr(10).join(before_context)}

=== MARKED_CODE ===
{chr(10).join(marked_parts)}

=== TARGET_CONTEXT_AFTER (read only) ===
{chr(10).join(after_context)}
"""

    try:
        result = generate(prompt)
    except Exception as exc:
        logging.warning("Changed-region grouped formatter LLM failed: %s", exc)
        return None

    if not result:
        return None

    extracted = _extract_marked_regions(_clean_llm_result(result), len(editable_regions))
    if extracted is None:
        logging.warning("Changed-region grouped formatter lost editable markers")
        return None

    for original, formatted in zip(editable_regions, extracted):
        validation = llm.validate_formatting.invoke({
            "original_code": "\n".join(original),
            "formatted_code": "\n".join(formatted),
        })
        if validation:
            logging.warning(
                "Changed-region grouped formatter rejected region: %s",
                str(validation)[:300],
            )
            return None

    return extracted[0] + readonly_lines + extracted[1]


def format_function_changed_regions(
    target_function: str,
    patched_function: str,
    *,
    generate: FormatGenerator | None = None,
    context_lines: int = 3,
) -> str:
    """Rebuild a patched function from target text and formatted change regions."""
    if target_function == patched_function:
        return patched_function

    target_lines = target_function.split("\n")
    patched_lines = patched_function.split("\n")
    patched_lines = _restore_equivalent_function_header(target_lines, patched_lines)
    target_keys = [_line_match_key(line) for line in target_lines]
    patched_keys = [_line_match_key(line) for line in patched_lines]
    matcher = difflib.SequenceMatcher(None, target_keys, patched_keys, autojunk=False)
    opcodes = matcher.get_opcodes()

    meaningful_equal_lines = sum(
        ti2 - ti1
        for tag, ti1, ti2, _, _ in opcodes
        if tag == "equal" and any(target_keys[ti1:ti2])
    )
    if meaningful_equal_lines == 0:
        logging.warning(
            "Changed-region formatter found no stable target lines; preserving patched function"
        )
        return patched_function

    generator = generate or _default_generate
    rebuilt: list[str] = []
    changed_regions = 0

    opcode_index = 0
    while opcode_index < len(opcodes):
        tag, ti1, ti2, pi1, pi2 = opcodes[opcode_index]
        if tag == "equal":
            rebuilt.extend(target_lines[ti1:ti2])
            opcode_index += 1
            continue
        if tag == "delete":
            if all(not line.strip() for line in target_lines[ti1:ti2]):
                rebuilt.extend(target_lines[ti1:ti2])
                opcode_index += 1
                continue
            changed_regions += 1
            opcode_index += 1
            continue

        if opcode_index + 2 < len(opcodes):
            middle = opcodes[opcode_index + 1]
            next_change = opcodes[opcode_index + 2]
            middle_tag, mti1, mti2, _, _ = middle
            next_tag, nti1, nti2, npi1, npi2 = next_change
            readonly_lines = target_lines[mti1:mti2]
            grouped_lines = (
                patched_lines[pi1:pi2]
                + readonly_lines
                + patched_lines[npi1:npi2]
            )
            contains_control_flow = False
            if (
                middle_tag == "equal"
                and next_tag in {"insert", "replace"}
                and readonly_lines
                and len(grouped_lines) <= 20
            ):
                try:
                    grouped_parser = ASTParser(
                        "void mystique_format_window(void)\n{\n"
                        + "\n".join(grouped_lines)
                        + "\n}",
                        Language.C,
                    )
                    contains_control_flow = any(
                        node.type in {
                            "if_statement",
                            "for_statement",
                            "while_statement",
                            "do_statement",
                            "switch_statement",
                        }
                        for node in grouped_parser.traverse_tree()
                    )
                except Exception as exc:
                    logging.debug(
                        "Changed-region formatter could not parse grouped window: %s",
                        exc,
                    )
            if (
                middle_tag == "equal"
                and next_tag in {"insert", "replace"}
                and readonly_lines
                and len(grouped_lines) <= 20
                and contains_control_flow
            ):
                before = target_lines[max(0, ti1 - context_lines):ti1]
                after = target_lines[nti2:nti2 + context_lines]
                grouped = _format_control_flow_group(
                    [patched_lines[pi1:pi2], patched_lines[npi1:npi2]],
                    readonly_lines,
                    before,
                    after,
                    generator,
                )
                if grouped is not None:
                    rebuilt.extend(grouped)
                    changed_regions += 2
                    opcode_index += 3
                    continue

        changed_regions += 1
        before = target_lines[max(0, ti1 - context_lines):ti1]
        after = target_lines[ti2:ti2 + context_lines]
        rebuilt.extend(_format_region(patched_lines[pi1:pi2], before, after, generator))
        opcode_index += 1

    result = "\n".join(rebuilt)
    validation = llm.validate_formatting.invoke({
        "original_code": patched_function,
        "formatted_code": result,
    })
    if validation:
        logging.warning(
            "Changed-region formatter rejected rebuilt function: %s",
            str(validation)[:300],
        )
        return patched_function

    logging.info(
        "Changed-region formatter rebuilt function with %d editable region(s)",
        changed_regions,
    )
    return result


def normalize_changed_regions(
    patched_code: str,
    target_content: str,
    file_signatures: list[str] | None = None,
    *,
    generate: FormatGenerator | None = None,
) -> str:
    """Normalize modified C functions using target text plus changed regions."""
    modified_names: set[str] = set()
    for signature in file_signatures or []:
        modified_names.add(signature.rsplit("#", 1)[-1])

    target_lines = target_content.split("\n")
    patched_lines = patched_code.split("\n")
    target_functions = parse_functions_with_tree_sitter(target_content)
    patched_functions = parse_functions_with_tree_sitter(patched_code)

    target_by_name = {function.name: function for function in target_functions}
    work_items = [
        function
        for function in patched_functions
        if function.name in target_by_name
        and (not modified_names or function.name in modified_names)
    ]

    result_lines = list(patched_lines)
    for patched_function in sorted(work_items, key=lambda item: item.start_line, reverse=True):
        target_function = target_by_name[patched_function.name]
        target_text = "\n".join(
            target_lines[target_function.start_line - 1:target_function.end_line]
        )
        patched_text = "\n".join(
            patched_lines[patched_function.start_line - 1:patched_function.end_line]
        )
        formatted = format_function_changed_regions(
            target_text,
            patched_text,
            generate=generate,
        )
        result_lines[patched_function.start_line - 1:patched_function.end_line] = formatted.split("\n")

    return "\n".join(result_lines)


def apply_repo_clang_format(
    patched_code: str,
    target_content: str,
    repo_path: str,
    target_file_path: str,
) -> str:
    """Use the target repository's clang-format style on changed lines only."""
    style_path = os.path.join(repo_path, ".clang-format")
    clang_format = shutil.which("clang-format")
    if not os.path.isfile(style_path):
        logging.info("Skipping local clang-format: target repository has no .clang-format")
        return patched_code
    if clang_format is None:
        logging.info("Skipping local clang-format: clang-format executable not found")
        return patched_code

    target_lines = target_content.splitlines()
    patched_lines = patched_code.splitlines()
    matcher = difflib.SequenceMatcher(None, target_lines, patched_lines, autojunk=False)
    ranges: list[tuple[int, int]] = []
    for tag, _, _, pi1, pi2 in matcher.get_opcodes():
        if tag not in {"insert", "replace"} or pi1 == pi2:
            continue
        start, end = pi1 + 1, pi2
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))

    if not ranges:
        return patched_code

    command = [
        clang_format,
        "--style=file",
        f"--assume-filename={os.path.join(repo_path, target_file_path)}",
    ]
    command.extend(f"--lines={start}:{end}" for start, end in ranges)
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
            "Local clang-format failed: %s",
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
            "Local clang-format changed code content, rejected: %s",
            str(validation)[:300],
        )
        return patched_code

    logging.info(
        "Applied target repository clang-format to %d changed line range(s)",
        len(ranges),
    )
    return formatted


def restore_patch_added_blank_lines(patched_code: str, file_patch: str | None) -> str:
    """Restore only blank lines explicitly added by the upstream patch."""
    if not file_patch:
        return patched_code

    patch_lines = file_patch.splitlines()
    anchors: list[tuple[str, str]] = []
    for index, line in enumerate(patch_lines):
        if line != "+":
            continue

        before: str | None = None
        for candidate in reversed(patch_lines[:index]):
            if candidate.startswith("@@") or candidate.startswith("diff --git"):
                break
            if candidate.startswith(("+", " ")) and candidate[1:].strip():
                before = candidate[1:]
                break

        after: str | None = None
        for candidate in patch_lines[index + 1:]:
            if candidate.startswith("@@") or candidate.startswith("diff --git"):
                break
            if candidate.startswith(("+", " ")) and candidate[1:].strip():
                after = candidate[1:]
                break

        if before is not None and after is not None:
            anchors.append((_line_match_key(before), _line_match_key(after)))

    if not anchors:
        return patched_code

    lines = patched_code.split("\n")
    restored = 0
    for before_key, after_key in anchors:
        matches = [
            index
            for index in range(len(lines) - 1)
            if _line_match_key(lines[index]) == before_key
            and _line_match_key(lines[index + 1]) == after_key
        ]
        if len(matches) != 1:
            continue
        lines.insert(matches[0] + 1, "")
        restored += 1

    if restored:
        logging.info("Restored %d blank line(s) explicitly added by upstream patch", restored)
    return "\n".join(lines)
