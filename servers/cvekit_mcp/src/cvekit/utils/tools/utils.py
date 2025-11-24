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
        if len(lines[-1]) == 0 or "\ No newline at end of file" in lines[-1]:
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
        lineno, _ = find_most_similar_block(
            contexts, target_file_lines, num_context, False
        )
        i = 0
        revised_lines = []
        for line in tmp_lines:
            if line.startswith(" ") or line.startswith("-"):
                sign = line[0]
                new_line = target_file_lines[lineno - 1 + i]
                if revise_context:
                    revised_lines.append(" " + new_line.strip("\n"))
                elif re.sub(r"\s+", "", line[1:]) == re.sub(r"\s+", "", new_line):
                    revised_lines.append(sign + new_line.strip("\n"))
                else:
                    revised_lines.append(line)
                i += 1
            else:
                revised_lines.append(line.replace("'s ", "->"))

        if revise_context:
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
                revised_lines[dlineno - 1] = "-" + revised_lines[dlineno - 1][1:]

            if not revised_lines[-1].startswith(" "):
                revised_lines.append(
                    " " + target_file_lines[lineno - 1 + i].strip("\n")
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
    将补丁分割成多个独立的块（blocks）。
    
    每个块代表一个文件的修改，可能包含多个 hunk（以 @@ 开头的行）。
    函数会：
    1. 识别文件边界（--- a/ 或 --- /dev/null）
    2. 根据 flag_commit 决定是否包含 commit 消息
    3. 使用黑名单过滤某些文件类型
    4. 将每个文件块分割成多个 hunk

    Args:
        patch (str): 要分割的补丁内容
        flag_commit (bool): 是否包含 commit 消息

    Yields:
        str: 每个独立的补丁块（包含文件路径和 hunk）

    Returns:
        None
    """
    logger.debug("=" * 80)
    logger.debug("[split_patch] 开始分割补丁")
    logger.debug("=" * 80)
    logger.debug(f"[split_patch] 输入参数:")
    logger.debug(f"  - patch 长度: {len(patch)} 字符")
    logger.debug(f"  - flag_commit: {flag_commit}")
    logger.debug(f"  - patch 内容预览: {patch[:500]}..." if len(patch) > 500 else f"  - patch 内容: {patch}")

    def split_block(lines: list[str]):
        """
        将单个文件块分割成多个 hunk。
        
        每个 hunk 以 @@ 开头，包含文件路径行和 hunk 内容。
        
        Args:
            lines: 文件块的行列表，前两行是文件路径（--- a/ 和 +++ b/）
        
        Yields:
            str: 每个 hunk 的完整内容
        """
        logger.debug(f"[split_block] 分割文件块")
        
        file_path_line_a = lines[0]
        file_path_line_b = lines[1]
        logger.debug(f"[split_block] 文件路径:")
        logger.debug(f"  - file_path_line_a={file_path_line_a}")
        logger.debug(f"  - file_path_line_b={file_path_line_b}")
        
        last_line = -1
        hunk_count = 0
        
        # 查找所有 hunk（以 @@ 开头的行）
        logger.debug(f"[split_block] 查找 hunk（以 @@ 开头的行）...")
        for line_no in range(2, len(lines)):
            current_line = lines[line_no]            
            if current_line.startswith("@@"):
                logger.debug(f"  - 第 {line_no} 行是 hunk 开始标记（@@）")
                if last_line != -1:
                    # 生成前一个 hunk
                    hunk_count += 1
                    logger.debug(f"  - 生成 hunk {hunk_count}（从第 {last_line} 行到第 {line_no} 行）")
                    hunk_lines = lines[last_line:line_no]
                    logger.debug(f"    - hunk 行数: {len(hunk_lines)}")
                    logger.debug(f"    - hunk 内容预览: {hunk_lines[0][:100]}..." if len(hunk_lines) > 0 and len(hunk_lines[0]) > 100 else f"    - hunk 第一行: {hunk_lines[0] if len(hunk_lines) > 0 else 'N/A'}")
                    
                    content = (
                        file_path_line_a
                        + "\n"
                        + file_path_line_b
                        + "\n"
                        + "\n".join(hunk_lines)
                    )
                    yield content
                else:
                    logger.debug(f"  - 这是第一个 hunk，last_line={last_line}")
                last_line = line_no
        
        # 处理最后一个 hunk
        if last_line != -1:
            hunk_count += 1
            logger.debug(f"[split_block] 处理最后一个 hunk {hunk_count}（从第 {last_line} 行到末尾）")
            remaining_lines = lines[last_line:]
            logger.debug(f"  - 剩余行数: {len(remaining_lines)}")
            logger.debug(f"  - 剩余内容预览: {remaining_lines[0][:100]}..." if len(remaining_lines) > 0 and len(remaining_lines[0]) > 100 else f"  - 剩余第一行: {remaining_lines[0] if len(remaining_lines) > 0 else 'N/A'}")
            
            content = (
                file_path_line_a
                + "\n"
                + file_path_line_b
                + "\n"
                + "\n".join(remaining_lines)
            )
            yield content
        
        logger.debug(f"[split_block] 文件块分割完成，共生成 {hunk_count} 个 hunk")

    try:
        # 将补丁按行分割
        logger.debug("[split_patch] 将补丁按行分割...")
        lines = patch.splitlines()
        logger.debug(f"[split_patch] 补丁分割完成:")
        logger.debug(f"  - 总行数: {len(lines)}")
        logger.debug(f"  - 前 10 行预览:")
        for i, line in enumerate(lines[:10]):
            logger.debug(f"    [{i}] {line[:100]}..." if len(line) > 100 else f"    [{i}] {line}")
        
        message = ""
        last_line = -1
        block_count = 0
        total_hunks = 0
        
        logger.debug("[split_patch] 开始遍历补丁行，查找文件块...")
        for line_no in range(len(lines)):
            current_line = lines[line_no]
            logger.debug(f"[split_patch] 处理第 {line_no}/{len(lines)-1} 行:")
            logger.debug(f"  - 行内容: {current_line[:100]}..." if len(current_line) > 100 else f"  - 行内容: {current_line}")
            
            # 检查是否是文件块开始（--- a/）
            if current_line.startswith("--- a/"):
                logger.debug(f"  - 检测到文件块开始标记: --- a/")
                logger.debug(f"  - 提取文件路径: {current_line}")
                
                if last_line >= 0:
                    # 处理前一个文件块
                    block_count += 1
                    logger.debug(f"[split_patch] 处理文件块 {block_count}（从第 {last_line} 行到第 {line_no} 行）")
                    logger.debug(f"  - flag_commit={flag_commit}")
                    
                    if flag_commit:
                        block_lines = lines[last_line : line_no - 2]
                    else:
                        block_lines = lines[last_line:line_no]
                    
                    logger.debug(f"  - 块内容预览: {block_lines[0][:100]}..." if len(block_lines) > 0 and len(block_lines[0]) > 100 else f"  - 块第一行: {block_lines[0] if len(block_lines) > 0 else 'N/A'}")
                    
                    # 分割块中的 hunk
                    hunk_index = 0
                    for x in split_block(block_lines):
                        hunk_index += 1
                        total_hunks += 1
                        yield message + x
                
                # 提取 commit 消息（如果是第一个文件块且 flag_commit=True）
                if last_line == -1 and flag_commit:
                    message = "\n".join(lines[: max(line_no - 2, 0)])
                    logger.debug(f"[split_patch] 提取 commit 消息:")
                    logger.debug(f"  - message 长度: {len(message)} 字符")
                    logger.debug(f"  - message 内容: {message[:300]}..." if len(message) > 300 else f"  - message 内容: {message}")
                
                # 检查文件是否在黑名单中
                logger.debug(f"[split_patch] 检查文件是否在黑名单中...")
                logger.debug(f"  - 当前行: {current_line}")
                logger.debug(f"  - 黑名单: {blacklist}")
                is_blacklisted = any(
                    current_line.endswith(blacklist_item)
                    for blacklist_item in blacklist
                )
                logger.debug(f"  - 是否在黑名单中: {is_blacklisted}")
                
                if is_blacklisted:
                    matched_item = next(
                        (item for item in blacklist if current_line.endswith(item)),
                        None
                    )
                    logger.debug(f"  - 匹配的黑名单项: {matched_item}")
                    logger.debug(f"  - 跳过此文件（设置 last_line=-2）")
                    last_line = -2
                else:
                    logger.debug(f"  - 文件不在黑名单中，设置 last_line={line_no}")
                    last_line = line_no
            
            # 检查是否是新文件（--- /dev/null）
            elif current_line.startswith("--- /dev/null"):
                logger.debug(f"  - 检测到新文件标记: --- /dev/null")
                logger.debug(f"  - 这是新创建的文件")
                
                if last_line >= 0:
                    # 处理前一个文件块
                    block_count += 1
                    logger.debug(f"[split_patch] 处理文件块 {block_count}（从第 {last_line} 行到第 {line_no} 行）")
                    logger.debug(f"  - flag_commit={flag_commit}")
                    
                    if flag_commit:
                        block_lines = lines[last_line : line_no - 3]
                    else:
                        block_lines = lines[last_line:line_no]
                    
                    logger.debug(f"  - 块内容预览: {block_lines[0][:100]}..." if len(block_lines) > 0 and len(block_lines[0]) > 100 else f"  - 块第一行: {block_lines[0] if len(block_lines) > 0 else 'N/A'}")
                    
                    # 分割块中的 hunk
                    hunk_index = 0
                    for x in split_block(block_lines):
                        hunk_index += 1
                        total_hunks += 1
                        yield message + x
                
                # 提取 commit 消息（如果是第一个文件块且 flag_commit=True）
                if last_line == -1 and flag_commit:
                    message = "\n".join(lines[: max(line_no - 3, 0)])
                    logger.debug(f"[split_patch] 提取 commit 消息:")
                    logger.debug(f"  - message 长度: {len(message)} 字符")
                    logger.debug(f"  - message 内容: {message[:300]}..." if len(message) > 300 else f"  - message 内容: {message}")
                
                # 检查文件是否在黑名单中（检查下一行，即 +++ b/ 行）
                if line_no + 1 < len(lines):
                    next_line = lines[line_no + 1]
                    logger.debug(f"[split_patch] 检查文件是否在黑名单中...")
                    logger.debug(f"  - 下一行（+++ b/）: {next_line}")
                    logger.debug(f"  - 黑名单: {blacklist}")
                    is_blacklisted = any(
                        next_line.endswith(blacklist_item)
                        for blacklist_item in blacklist
                    )
                    logger.debug(f"  - 是否在黑名单中: {is_blacklisted}")
                    
                    if is_blacklisted:
                        matched_item = next(
                            (item for item in blacklist if next_line.endswith(item)),
                            None
                        )
                        logger.debug(f"  - 匹配的黑名单项: {matched_item}")
                        logger.debug(f"  - 跳过此文件（设置 last_line=-2）")
                        last_line = -2
                    else:
                        logger.debug(f"  - 文件不在黑名单中，设置 last_line={line_no}")
                        last_line = line_no
                else:
                    logger.warning(f"[split_patch] 警告：下一行不存在，无法检查黑名单")
                    last_line = line_no
        
        # 处理最后一个文件块
        if last_line >= 0:
            block_count += 1
            logger.debug("=" * 80)
            logger.debug(f"[split_patch] 处理最后一个文件块 {block_count}（从第 {last_line} 行到末尾）")
            logger.debug("=" * 80)
            remaining_lines = lines[last_line:]
            logger.debug(f"  - 剩余行数: {len(remaining_lines)}")
            logger.debug(f"  - 剩余内容预览: {remaining_lines[0][:100]}..." if len(remaining_lines) > 0 and len(remaining_lines[0]) > 100 else f"  - 剩余第一行: {remaining_lines[0] if len(remaining_lines) > 0 else 'N/A'}")
            
            # 分割块中的 hunk
            hunk_index = 0
            for x in split_block(remaining_lines):
                hunk_index += 1
                total_hunks += 1
                yield message + x
        else:
            logger.debug(f"[split_patch] last_line={last_line}，没有剩余文件块需要处理")
        
        logger.debug("=" * 80)
        logger.debug(f"[split_patch] 补丁分割完成:")
        logger.debug(f"  - 处理的文件块数: {block_count}")
        logger.debug(f"  - 生成的总 hunk 数: {total_hunks}")
        logger.debug(f"  - commit 消息长度: {len(message)} 字符")
        logger.debug("=" * 80)

    except Exception as e:
        logger.error(f"[split_patch] 分割补丁时发生异常: {type(e).__name__}={e}")
        logger.debug(f"[split_patch] 异常堆栈:")
        logger.debug("".join(traceback.TracebackException.from_exception(e).format()))
        logger.warning("Failed to split patch")
        logger.warning("".join(traceback.TracebackException.from_exception(e).format()))
        return None
