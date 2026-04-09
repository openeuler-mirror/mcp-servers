"""
This file is based on the project "patch-backporting":
  https://github.com/OS3Lab/patch-backporting
The original code is licensed under the MIT License.
See third_party/patch-backporting/LICENSE for the full license text.

本文件在 OS3Lab/patch-backporting 项目的基础上进行了修改，以适配 CVEKit 的自动回移植流程。

Modifications for CVEKit MCP backport workflow:
  Copyright (c) 2025 CVEKit contributors
  Licensed under the Mulan PSL v2.
"""

import os
import re
import traceback
from typing import Generator, List, Tuple

import Levenshtein

from .logger import logger

blacklist = [
    ".rst",
    ".yaml",
    ".yml",
    ".md",
    ".tcl",
    "CHANGES",
    "ANNOUNCE",
    "NEWS",
    ".pem",
    ".js",
    ".sha1",
    ".sha256",
    ".uuid",
    ".test",
    "manifest",
    ".xml",
    "_test.go",
    ".json",
    ".golden",
    ".txt",
    ".mdx",
]


def validate_unified_diff_patch(patch: str) -> Tuple[bool, str, str]:
    """
    Validate patch text before revise/apply:
    - must look like unified diff (`---`, `+++`, `@@`)
    - must not contain bare commit metadata noise before first file header
    """
    if not patch or not patch.strip():
        return False, "empty patch", patch

    lines = patch.splitlines()
    first_file_header = -1
    for idx, line in enumerate(lines):
        if line.startswith("--- a/") or line.startswith("--- /dev/null"):
            first_file_header = idx
            break
    if first_file_header == -1:
        return False, "missing file header (`--- a/...` or `--- /dev/null`)", patch

    normalized_patch = "\n".join(lines[first_file_header:])
    if normalized_patch and not normalized_patch.endswith("\n"):
        normalized_patch += "\n"
    normalized_lines = normalized_patch.splitlines()

    has_plus_header = any(
        line.startswith("+++ b/") or line.startswith("+++ /dev/null")
        for line in normalized_lines
    )
    if not has_plus_header:
        return False, "missing file header (`+++ b/...` or `+++ /dev/null`)", normalized_patch

    if not any(line.startswith("@@ ") or line.startswith("@@") for line in normalized_lines):
        return False, "missing hunk header (`@@ ... @@`)", normalized_patch

    # Accept git-show / format-patch metadata before the first file header.
    # We already normalize by trimming to the first `---` header.
    # This avoids rejecting valid patches that include commit message blocks.

    return True, "", normalized_patch


def find_most_similar_files(target_filename: str, search_directory: str) -> List[str]:
    """
    Find the five file paths that are most similar to non-existent files.

    Args:
        target_filename (str): The target file's name which we want to find out.
        search_directory (str): Directory name which we need to find in.

    Returns:
        List[str]: List of the five most similar file.
    """
    top_n = 5
    similarity_list = []

    # Walk through all subdirectories and files in the search directory
    for root, dirs, files in os.walk(search_directory):
        for filename in files:
            # Calculate the Levenshtein distance between the target filename and the current filename
            distance = Levenshtein.distance(target_filename, filename)
            relative_path = os.path.relpath(
                os.path.join(root, filename), search_directory
            )
            similarity_list.append((distance, relative_path))

    # Sort the list by distance in ascending order and get the top N results
    similarity_list.sort(key=lambda x: x[0])
    top_similar_files = [
        relative_path for distance, relative_path in similarity_list[:top_n]
    ]

    return top_similar_files


def find_most_similar_block(
    pattern: List[str], main: List[str], p_len: int, dline_flag: bool = False
) -> Tuple[int, int]:
    """
    Finds the most similar block of lines in the main list compared to the pattern list using Levenshtein distance.

    Args:
        pattern (List[str]): The list of code lines to match.
        main (List[str]): The list of lines to search within.
        p_len (int): The length of the pattern.
        dline_flag (bool, optional): A flag indicating whether to ignore lines starting with '+' or '-'. Defaults to False.

    Returns:
        Tuple[int, int]: A tuple containing the starting index of the most similar block in the main list (1-based index)
                         and the minimum Levenshtein distance.
    """
    min_distance = float("inf")
    best_start_index = 1

    for i in range(len(main) - p_len + 1):
        distance = Levenshtein.distance(
            "\n".join(main[i : i + p_len]), "\n".join(pattern)
        )
        if distance < min_distance and not (
            dline_flag and (main[i].startswith("+") or main[i].startswith("-"))
        ):
            min_distance = distance
            best_start_index = i + 1

    # try to fix offset, align the pattern with the most similar block
    if not dline_flag:
        offset_flag = False
        offset = float("inf")
        lineno = best_start_index
        for i in range(p_len):
            if len(pattern[i].strip()) < 3:
                continue
            for j in range(-5, 6):
                try:
                    if pattern[i].strip() == main[lineno - 1 + j].strip():
                        offset_flag = True
                        if abs(j - i) < abs(offset):
                            offset = j - i
                except:
                    pass
            if offset_flag:
                best_start_index += offset
                break

    # Clamp to valid 1-based range to avoid downstream index overflow.
    if len(main) <= 0:
        return 1, min_distance
    max_start = max(1, len(main) - p_len + 1)
    best_start_index = max(1, min(best_start_index, max_start))
    return best_start_index, min_distance


def extract_context(lines: list) -> Tuple[list, int, list, int]:
    """
    Process the input string by removing certain lines and returning the processed string and the count of processed lines.

    Args:
        input_string (str): The input string to be processed.

    Returns:
        tuple[str, int]: A tuple containing the processed string and the count of processed lines.
    """
    processed_lines = []
    add_lines = []
    for line in lines:
        if line.startswith(" "):
            processed_lines.append(line[1:])
        elif line.startswith("-"):
            processed_lines.append(line[1:])
        elif line.startswith("+"):
            add_lines.append(line[1:])

    processed_lines_count = len(processed_lines)

    return processed_lines, processed_lines_count, add_lines, len(add_lines)


def revise_patch(
    patch: str, project_path: str, revise_context: bool = False
) -> Tuple[str, bool]:
    """fix mistakes in generated patch.
    1. wrong line numbers.
    2. wrong format: not startswith ` `, `-` or `+`
    3. wrong context lines: a) wrong indention. b) wrong lines.

    Args:
        patch (str): patch to be revised.
        project_path (str): CVE project source code in local.
        revise_context (bool, optional): True means force to revise all context lines. Defaults to False.

    Returns:
        Tuple[str, bool]: revised patch and fix flag.
    """

    def revise_hunk(lines: list[str], target_file_lines: list[str]) -> tuple[str, bool]:
        """fix lines from "@@" to the end"""
        fixed = False
        if not target_file_lines:
            return "\n".join(lines), fixed
        if len(lines[-1]) == 0 or "\\ No newline at end of file" in lines[-1]:
            lines = lines[:-1]

        # fix corrupt patch
        tmp_lines = []
        for line in lines[1:]:
            if line.startswith("+") or line.startswith("-") or line.startswith(" "):
                tmp_lines.append(line)
            else:
                tmp_lines.append(" " + line)

        # fix mismatched lines
        # force_flag: force to revise all mismatched lines, otherwise fix indentation only
        # TODO: if the distance is close, it should be revised
        # XXX: if the distance is far, it should not be revised
        contexts, num_context, _, _ = extract_context(tmp_lines)
        lineno, dist = find_most_similar_block(
            contexts, target_file_lines, num_context, False
        )
        # Guardrail: if anchor match confidence is low, avoid aggressive context
        # rewrites and keep model-provided hunk content as-is.
        non_empty_context = [x.strip() for x in contexts if x.strip()]
        context_chars = sum(len(x) for x in non_empty_context)
        max_rel_dist = float(os.getenv("CVEKIT_PATCH_ALIGN_MAX_REL_DIST", "0.35"))
        max_abs_dist = int(os.getenv("CVEKIT_PATCH_ALIGN_MAX_ABS_DIST", "80"))
        low_confidence_anchor = (
            num_context <= 0
            or context_chars <= 0
            or (dist > max_abs_dist and (dist / max(context_chars, 1)) > max_rel_dist)
        )
        if low_confidence_anchor:
            logger.debug(
                "[revise_patch] low confidence anchor, skip context rewrite: "
                "dist=%s, context_chars=%s, num_context=%s, rel=%.4f",
                dist,
                context_chars,
                num_context,
                (dist / max(context_chars, 1)),
            )
        i = 0
        revised_lines = []
        for line in tmp_lines:
            if line.startswith(" ") or line.startswith("-"):
                if low_confidence_anchor:
                    revised_lines.append(line)
                    i += 1
                    continue
                sign = line[0]
                target_idx = lineno - 1 + i
                if target_idx < 0 or target_idx >= len(target_file_lines):
                    # Keep original patch line when inferred anchor drifts out of file range.
                    revised_lines.append(line)
                    i += 1
                    continue
                new_line = target_file_lines[target_idx]
                if revise_context:
                    revised_lines.append(" " + new_line.strip("\n"))
                elif re.sub(r"\s+", "", line[1:]) == re.sub(r"\s+", "", new_line):
                    revised_lines.append(sign + new_line.strip("\n"))
                else:
                    revised_lines.append(line)
                i += 1
            else:
                revised_lines.append(line.replace("'s ", "->"))

        if revise_context and not low_confidence_anchor:
            logger.debug("force to revise all context lines")
            last_line = 0
            for line in tmp_lines:
                if not line.startswith("-"):
                    continue
                dline = []
                dline.append(line[1:])
                dlineno, dist = find_most_similar_block(
                    dline, revised_lines[last_line:], 1, True
                )
                dlineno = dlineno + last_line
                last_line = dlineno
                if 0 < dlineno <= len(revised_lines):
                    revised_lines[dlineno - 1] = "-" + revised_lines[dlineno - 1][1:]

            if revised_lines and not revised_lines[-1].startswith(" "):
                next_idx = lineno - 1 + i
                if next_idx < 0:
                    next_idx = 0
                if next_idx >= len(target_file_lines):
                    next_idx = len(target_file_lines) - 1
                revised_lines.append(
                    " " + target_file_lines[next_idx].strip("\n")
                )

        # fix wrong line number
        orignal_line_number = sum(
            1 for line in revised_lines if not line.startswith("+")
        )
        patched_line_number = sum(
            1 for line in revised_lines if not line.startswith("-")
        )
        chunks = re.findall(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)", lines[0])[0]
        if chunks[0] != chunks[2]:
            fixed = True
        header = f"@@ -{chunks[0]},{orignal_line_number} +{chunks[2]},{patched_line_number} @@{chunks[4]}\n"

        return header + "\n".join(revised_lines), fixed

    def revise_block(lines: list[str]) -> tuple[list[str], bool]:
        """fix "--- a/" and "+++ b/", and call revise_hunk."""
        try:
            file_path_a = re.findall(r"--- a/(.*)", lines[0])[0]
            fixed_file_path_a = os.path.normpath(file_path_a)
        except:
            file_path_a = fixed_file_path_a = lines[0]

        try:
            file_path_b = re.findall(r"\+\+\+ b/(.*)", lines[1])[0]
            fixed_file_path_b = os.path.normpath(file_path_b)
        except:
            file_path_b = fixed_file_path_b = lines[1]

        block_fixed = (
            file_path_a != fixed_file_path_a or file_path_b != fixed_file_path_b
        )
        assert (
            (file_path_a == file_path_b and fixed_file_path_a == fixed_file_path_b)
            or fixed_file_path_a == "--- /dev/null"
            or fixed_file_path_b == "--- /dev/null"
        )

        fixed_lines = [
            f"--- a/{fixed_file_path_a}".replace("a/--- ", ""),
            f"+++ b/{fixed_file_path_b}".replace("b/--- ", ""),
        ]
        try:
            with open(os.path.join(project_path, file_path_a), "rb") as f:
                content = f.read().decode("utf-8", errors="ignore")
                file_content = [line.rstrip("\n") for line in content.splitlines()]
        except:
            # do not revise patch if file changed, handle changed file in `_apply_hunk`
            return lines, False

        last_line = -1
        for line_no in range(2, len(lines)):
            if lines[line_no].startswith("@@"):
                if last_line != -1:
                    hunk_lines, hunk_fixed = revise_hunk(
                        lines[last_line:line_no], file_content
                    )
                    fixed_lines.append(hunk_lines)
                    block_fixed = block_fixed or hunk_fixed
                last_line = line_no
        if last_line != -1:
            hunk_lines, hunk_fixed = revise_hunk(lines[last_line:], file_content)
            fixed_lines.append(hunk_lines)
            block_fixed = block_fixed or hunk_fixed

        return fixed_lines, block_fixed

    try:
        lines = patch.splitlines()
        fixed_lines = []

        last_line = -1
        fixed = False
        for line_no in range(len(lines)):
            if lines[line_no].startswith("--- a/") or lines[line_no].startswith(
                "--- /dev/null"
            ):
                if last_line != -1:
                    block_lines, block_fixed = revise_block(lines[last_line:line_no])
                    fixed_lines += block_lines
                    fixed = fixed or block_fixed
                last_line = line_no
        if last_line != -1:
            block_lines, block_fixed = revise_block(lines[last_line:])
            fixed_lines += block_lines
            fixed = fixed or block_fixed

        return "\n".join(fixed_lines) + "\n", fixed
    except Exception as e:
        logger.debug("Failed to revise patch")
        logger.debug(e)
        logger.warning("".join(traceback.TracebackException.from_exception(e).format()))
        return patch, False


def split_patch(patch: str, flag_commit: bool) -> Generator[str, None, None]:
    """
    将补丁按文件拆分为多个 hunk 块。
    注意：该函数默认不输出调试日志，避免将大量流程细节注入 LLM 上下文。
    """

    def split_block(lines: list[str]) -> Generator[str, None, None]:
        if len(lines) < 3:
            return
        file_path_line_a = lines[0]
        file_path_line_b = lines[1]

        last_line = -1
        for line_no in range(2, len(lines)):
            if lines[line_no].startswith("@@"):
                if last_line != -1:
                    hunk_lines = lines[last_line:line_no]
                    yield file_path_line_a + "\n" + file_path_line_b + "\n" + "\n".join(hunk_lines)
                last_line = line_no

        if last_line != -1:
            hunk_lines = lines[last_line:]
            yield file_path_line_a + "\n" + file_path_line_b + "\n" + "\n".join(hunk_lines)

    try:
        lines = patch.splitlines()
        message = ""
        last_line = -1

        def _sanitize_block_lines(block_lines: list[str]) -> list[str]:
            if not block_lines:
                return block_lines
            cut = len(block_lines)
            for i, line in enumerate(block_lines):
                if line.startswith("diff --git ") or line.startswith("index "):
                    cut = i
                    break
            return block_lines[:cut]

        def _emit_block(end_line: int) -> Generator[str, None, None]:
            if last_line < 0:
                return
            block_lines = _sanitize_block_lines(lines[last_line:end_line])
            if not block_lines:
                return
            for x in split_block(block_lines):
                yield message + x

        for line_no in range(len(lines)):
            current_line = lines[line_no]

            # 主边界：diff --git
            if current_line.startswith("diff --git "):
                if last_line >= 0:
                    for chunk in _emit_block(line_no):
                        yield chunk
                last_line = -1
                continue

            # 文件头边界：--- a/
            if current_line.startswith("--- a/"):
                if last_line >= 0:
                    for chunk in _emit_block(line_no):
                        yield chunk

                if last_line == -1 and flag_commit:
                    message = "\n".join(lines[: max(line_no - 2, 0)])

                is_blacklisted = any(
                    current_line.endswith(blacklist_item)
                    for blacklist_item in blacklist
                )
                last_line = -2 if is_blacklisted else line_no

            # 新文件边界：--- /dev/null
            elif current_line.startswith("--- /dev/null"):
                if last_line >= 0:
                    for chunk in _emit_block(line_no):
                        yield chunk

                if last_line == -1 and flag_commit:
                    message = "\n".join(lines[: max(line_no - 3, 0)])

                if line_no + 1 < len(lines):
                    next_line = lines[line_no + 1]
                    is_blacklisted = any(
                        next_line.endswith(blacklist_item)
                        for blacklist_item in blacklist
                    )
                    last_line = -2 if is_blacklisted else line_no
                else:
                    last_line = line_no

        if last_line >= 0:
            for chunk in _emit_block(len(lines)):
                yield chunk

    except Exception as e:
        logger.error(f"[split_patch] 分割补丁时发生异常: {type(e).__name__}={e}")
        logger.warning("Failed to split patch")
        logger.warning("".join(traceback.TracebackException.from_exception(e).format()))
        return None
