"""
This file is based on the project "Mystique":
  https://github.com/Mystique-OpenSource/mystique-opensource.github.io
The original code is licensed under the GNU General Public License v3.0.
See third_party/mystique/LICENSE for the full license text.

本文件在 Mystique-OpenSource/mystique 项目的基础上进行了修改，以适配 CVEKit 的自动回移植流程。

Modifications for CVEKit MCP backport workflow:
  Copyright (c) 2025 CVEKit contributors
  Licensed under the Mulan PSL v2.
"""


import difflib
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass

from common import HunkType


@dataclass
class Hunk:
    type: HunkType


@dataclass
class ModHunk(Hunk):
    a_startline: int
    a_endline: int
    b_startline: int
    b_endline: int
    a_code: str
    b_code: str


@dataclass
class AddHunk(Hunk):
    b_startline: int
    b_endline: int
    b_code: str
    insert_line: int


@dataclass
class DelHunk(Hunk):
    a_startline: int
    a_endline: int
    a_code: str


def git_diff_file(file1: str, file2: str, remove_diff_header: bool = False, algorithm: str = "histogram") -> str:
    diff = subprocess.run(["git", "--no-pager", "diff", "--no-index", "-w", "-b",
                           "--unified=10000", "--function-context", f"--diff-algorithm={algorithm}", file1, file2],
                          stdout=subprocess.PIPE).stdout.decode()
    if remove_diff_header:
        diff_lines = diff.splitlines()[4:]
        diff = "\n".join(diff_lines)
    return diff


def git_diff_code(code1: str, code2: str, remove_diff_header: bool = False) -> str:
    tf1 = tempfile.NamedTemporaryFile()
    tf2 = tempfile.NamedTemporaryFile()
    tf1.write(code1.encode())
    tf2.write(code2.encode())
    tf1.flush()
    tf2.flush()
    diff = git_diff_file(tf1.name, tf2.name, remove_diff_header)
    return diff


def diff2html(diff: str, output_path: str, show_error: bool = True, title: str = "diff"):
    if show_error:
        subprocess.run(["diff2html", "-f", "html", "-F", output_path, "--su", "-s", "side", "--lm",
                        "lines", "-i", "stdin", "-t", title], input=bytes(diff, "utf-8"))
    else:
        subprocess.run(["diff2html", "-f", "html", "-F", output_path, "--su", "-s", "side", "--lm",
                        "lines", "-i", "stdin", "-t", title], input=bytes(diff, "utf-8"), stderr=subprocess.DEVNULL)


def diff2html_file(file1: str, file2: str, output_path: str, show_error: bool = True, title: str | None = None):
    if not os.path.exists(file1):
        return
    if not os.path.exists(file2):
        return
    diff = git_diff_file(file1, file2)
    if diff == "":
        with open(output_path + ".same", "w") as f:
            f.write("No difference")
        return
    if title is None:
        title = os.path.basename(output_path)
    diff2html(diff, output_path, show_error, title)


def diff2html_code(code1: str, code2: str, output_path: str, show_error: bool = True, title: str | None = None):
    diff = git_diff_code(code1, code2)
    if diff == "":
        with open(output_path + ".same", "w") as f:
            f.write("No difference")
        return
    if title is None:
        title = os.path.basename(output_path)
    diff2html(diff, output_path, show_error, title)


def parse_diff(diff: str, filename: str | None = None) -> dict[str, list[int]]:
    """解析 unified diff，通过 @@ 头计算每一行的原始行号和新行号。

    返回 {"add": [新文件中的行号], "delete": [原文件中的行号]}
    行号均为 1-based。
    """
    info = {
        "add": [],
        "delete": []
    }
    add_line = 0
    delete_line = 0
    lines = diff.split("\n")

    for line in lines:
        if line.startswith("@@"):
            # 格式: @@ -old_start,old_count +new_start,new_count @@
            delete_line = int(line.split("-")[1].split(",")[0].split(" ")[0]) - 1
            add_line = int(line.split("+")[1].split(",")[0]) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            add_line += 1
            info["add"].append(add_line)
        elif line.startswith("-") and not line.startswith("---"):
            delete_line += 1
            info["delete"].append(delete_line)
        else:
            add_line += 1
            delete_line += 1

    logging.debug("[PARSE_DIFF] 文件: %s | 新增行: %s | 删除行: %s",
                  filename or "未知", info['add'], info['delete'])

    return info


def parse_diff_from_codes(code1: str, code2: str) -> dict[str, list[int]]:
    """对两段代码执行 difflib 差异比较，通过 @@ 头解析出差异行号。

    完全基于 unified diff 格式，不依赖 difft 或 git diff。
    返回 {"add": [code2中的行号], "delete": [code1中的行号]}，均为 1-based。
    """
    code1_lines = code1.splitlines(keepends=True)
    code2_lines = code2.splitlines(keepends=True)
    diff_text = ''.join(difflib.unified_diff(
        code1_lines, code2_lines,
        fromfile="a", tofile="b",
        lineterm="\n", n=10000
    ))
    logging.debug("[PARSE_DIFF_FROM_CODES] code1 has %d lines, code2 has %d lines", len(code1_lines), len(code2_lines))
    logging.debug("[PARSE_DIFF_FROM_CODES] --- raw unified_diff output (%d chars) ---\n%s\n--- end diff ---",
                  len(diff_text), diff_text)
    return parse_diff(diff_text)


def sourtarContextMap(code_a: str, code_b: str, modifiedLines) -> tuple[dict, dict]:
    """构建 source (code_a) 和 target (code_b) 的"旧文件"上下文行号映射。

    对每一行，如果不在修改行集合中，则分配一个递增的序号（表示在"旧"文件中的位置）。
    """
    targetLines = code_b.split("\n")
    targetLinesNum = len(targetLines)

    i = 0
    targetMap = {}
    for targetLine in range(1, targetLinesNum + 1):
        if targetLine not in modifiedLines["add"]:
            i += 1
            targetMap[targetLine] = i

    sourcetMap = {}

    sourceLines = code_a.split("\n")
    sourceLinesNum = len(sourceLines)

    j = 0
    for sourceLine in range(1, sourceLinesNum + 1):
        if sourceLine not in modifiedLines["delete"]:
            j += 1
            sourcetMap[sourceLine] = j

    logging.debug("[SOUTARCONTEXTMAP] code_a行数: %d, code_b行数: %d, 映射条目: source=%d, target=%d",
                  sourceLinesNum, targetLinesNum, len(sourcetMap), len(targetMap))

    return sourcetMap, targetMap


def sourtarDiffMap(modifiedLines) -> tuple[list[list], list[list]]:
    """将修改行分组为连续区间。"""
    def group_consecutive_ints(nums: list[int]):
        if not nums:
            return []
        nums.sort()
        result = [[nums[0]]]
        for num in nums[1:]:
            if num == result[-1][-1] + 1:
                result[-1].append(num)
            else:
                result.append([num])
        return result

    delLinesGroup = group_consecutive_ints(modifiedLines["delete"])
    addLinesGroup = group_consecutive_ints(modifiedLines["add"])

    logging.debug("[SOUTARDIFFMAP] 删除组: %s | 新增组: %s", delLinesGroup, addLinesGroup)

    return delLinesGroup, addLinesGroup


def method_linemap(mapA, mapB) -> dict[int, int]:
    """建立两个上下文行号映射之间的对应关系。"""
    map_result = {}
    for line, pivot in mapA.items():
        for k, v in mapB.items():
            if pivot == v:
                map_result[line] = k
                break

    logging.debug("[METHOD_LINEMAP] 映射条目数: %d", len(map_result))

    return map_result


def method_hunkmap(delLinesGroup: list[list[int]], addLinesGroup: list[list[int]], line_map: dict[int, int]):
    """将删除组和新增组配对为修改型 hunk。

    配对的依据：删除组的前一行和后一行，在 line_map 中的映射值与新增组的前一行和后一行对应相同。
    """
    hunk_map: dict[tuple[int, int], tuple[int, int]] = {}
    line_map[0] = 0
    for i, delLines in enumerate(delLinesGroup):
        del_head = delLines[0] - 1
        del_tail = delLines[-1] + 1

        for j, addLines in enumerate(addLinesGroup):
            add_head = addLines[0] - 1
            add_tail = addLines[-1] + 1

            if (del_head in line_map and del_tail in line_map and
                    line_map[del_head] == add_head and line_map[del_tail] == add_tail):
                hunk_key = (del_head + 1, del_tail - 1)
                hunk_value = (add_head + 1, add_tail - 1)
                hunk_map[hunk_key] = hunk_value
                break

    logging.debug("[METHOD_HUNKMAP] 删除组数: %d, 新增组数: %d, 匹配hunk数: %d | hunk_map: %s",
                  len(delLinesGroup), len(addLinesGroup), len(hunk_map), hunk_map)

    return hunk_map


def get_patch_hunks(code1: str, code2: str, suffix: str = ".c") -> list[Hunk]:
    """根据两段代码的 unified diff 构建 hunk 列表。

    完全基于 difflib + @@ 头解析，不依赖 difft 或外部 git diff。
    返回的 hunk 行号为 code1/code2 内的 1-based 行号。
    """
    code1_lines = code1.split("\n")
    code2_lines = code2.split("\n")

    modifiedLines = parse_diff_from_codes(code1, code2)
    sourceOldFileMap, targetOldFileMap = sourtarContextMap(code1, code2, modifiedLines)
    delLinesGroup, addLinesGroup = sourtarDiffMap(modifiedLines)
    line_map = method_linemap(sourceOldFileMap, targetOldFileMap)
    modify_hunks_map = method_hunkmap(delLinesGroup, addLinesGroup, line_map)

    r_line_map = {v: k for k, v in line_map.items()}

    hunk_list: list[Hunk] = []

    for a_hunk, b_hunk in modify_hunks_map.items():
        a_content = "\n".join(code1_lines[a_hunk[0] - 1:a_hunk[1]])
        b_content = "\n".join(code2_lines[b_hunk[0] - 1:b_hunk[1]])
        hunk = ModHunk(HunkType.MOD, a_hunk[0], a_hunk[1], b_hunk[0], b_hunk[1], a_content, b_content)
        hunk_list.append(hunk)

    for add_hunk in addLinesGroup:
        first_line, last_line = add_hunk[0], add_hunk[-1]
        if (first_line, last_line) not in modify_hunks_map.values():
            insert_line = r_line_map.get(first_line - 1, 0)
            content = "\n".join(code2_lines[first_line - 1:last_line])
            hunk_list.append(AddHunk(HunkType.ADD, first_line, last_line, content, insert_line))

    for del_hunk in delLinesGroup:
        first_line, last_line = del_hunk[0], del_hunk[-1]
        if (first_line, last_line) not in modify_hunks_map.keys():
            content = "\n".join(code1_lines[first_line - 1:last_line])
            hunk_list.append(DelHunk(HunkType.DEL, first_line, last_line, content))

    logging.debug("[GET_PATCH_HUNKS] code1行数: %d, code2行数: %d, hunk数: %d (MOD:%d, ADD:%d, DEL:%d)",
                  len(code1_lines), len(code2_lines), len(hunk_list),
                  sum(1 for h in hunk_list if isinstance(h, ModHunk)),
                  sum(1 for h in hunk_list if isinstance(h, AddHunk)),
                  sum(1 for h in hunk_list if isinstance(h, DelHunk)))

    return hunk_list


if __name__ == "__main__":
    diff2html_code("...", "...", "/tmp/diff_test.html")
