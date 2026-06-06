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


import logging

import difftools
try:
    import Levenshtein
except ImportError:
    # 如果没有安装Levenshtein，使用简单的字符串比较
    class Levenshtein:
        @staticmethod
        def ratio(s1, s2):
            if s1 == s2:
                return 1.0
            if not s1 or not s2:
                return 0.0
            # 简单的相似度计算
            common = sum(1 for a, b in zip(s1, s2) if a == b)
            return common / max(len(s1), len(s2))
import utils
from project import Method


def sourtarDiffMap(modifiedLines) -> tuple[list[list], list[list]]:
    delLinesGroup = utils.group_consecutive_ints(modifiedLines["delete"])
    addLinesGroup = utils.group_consecutive_ints(modifiedLines["add"])
    return delLinesGroup, addLinesGroup


def method_linemap(mapA, mapB) -> dict[int, int]:
    map_result = {}
    for line, pivot in mapA.items():
        for k, v in mapB.items():
            if pivot == v:
                map_result[line] = k
    return map_result


def method_hunkmap(delLinesGroup: list[list[int]], addLinesGroup: list[list[int]], line_map: dict[int, int]):
    hunk_map: dict[tuple[int, int], tuple[int, int]] = {}
    line_map[0] = 0
    for delLines in delLinesGroup:
        del_head = delLines[0] - 1
        del_tail = delLines[-1] + 1
        for addLines in addLinesGroup:
            add_head = addLines[0] - 1
            add_tail = addLines[-1] + 1
            if (del_head in line_map and del_tail in line_map and
                    line_map[del_head] == add_head and line_map[del_tail] == add_tail):
                hunk_map[(del_head + 1, del_tail - 1)] = (add_head + 1, add_tail - 1)
                continue
    return hunk_map


def method_map(a_method: Method, b_method: Method, sim_thres: float | None = None):
    a_code = a_method.code
    b_code = b_method.code

    logging.debug("=" * 70)
    logging.debug("[METHOD_MAP] a_method: %s (lines %d-%d)", a_method.signature, a_method.start_line, a_method.end_line)
    logging.debug("[METHOD_MAP] b_method: %s (lines %d-%d)", b_method.signature, b_method.start_line, b_method.end_line)
    logging.debug("[METHOD_MAP] sim_thres: %s", sim_thres)

    # 打印 a/b method 每行内容，方便定位映射错误
    a_lines = a_code.split('\n')
    b_lines = b_code.split('\n')
    logging.debug("[METHOD_MAP] --- a_method code (%d lines, relative) ---", len(a_lines))
    for i, line in enumerate(a_lines, 1):
        logging.debug("[METHOD_MAP]   a:%-4d | %s", i, line)
    logging.debug("[METHOD_MAP] --- b_method code (%d lines, relative) ---", len(b_lines))
    for i, line in enumerate(b_lines, 1):
        logging.debug("[METHOD_MAP]   b:%-4d | %s", i, line)

    # 步骤1: 生成差异
    modifiedLines = difftools.parse_diff_from_codes(a_code, b_code)
    logging.debug("[METHOD_MAP] step1 modifiedLines: %s", modifiedLines)

    # 步骤2: 构建上下文映射
    sourceOldFileMap, targetOldFileMap = difftools.sourtarContextMap(a_code, b_code, modifiedLines)
    logging.debug("[METHOD_MAP] step2 sourceOldFileMap (a-side context index): %s",
                  dict(sorted(sourceOldFileMap.items())))
    logging.debug("[METHOD_MAP] step2 targetOldFileMap (b-side context index): %s",
                  dict(sorted(targetOldFileMap.items())))

    # 步骤3: 分组差异行
    delLinesGroup, addLinesGroup = sourtarDiffMap(modifiedLines)
    logging.debug("[METHOD_MAP] step3 delLinesGroup: %s, addLinesGroup: %s",
                  delLinesGroup, addLinesGroup)

    # 步骤4: 构建行号映射 (context index 匹配)
    line_map = method_linemap(sourceOldFileMap, targetOldFileMap)
    logging.debug("[METHOD_MAP] step4 line_map (a->b): %s", dict(sorted(line_map.items())))

    # 步骤5: 构建 Hunk 映射
    hunk_map = method_hunkmap(delLinesGroup, addLinesGroup, line_map)
    logging.debug("[METHOD_MAP] step5 hunk_map: %s", hunk_map)

    # 步骤6: 计算未匹配的新增行
    diff_add_lines: set[int] = set()
    for add_line in modifiedLines["add"]:
        for hunk_start, hunk_end in hunk_map.keys():
            if hunk_start <= add_line <= hunk_end:
                break
        else:
            diff_add_lines.add(add_line)
    logging.debug("[METHOD_MAP] step6 diff_add_lines (unmatched): %s", sorted(diff_add_lines))

    # 步骤7: 计算未匹配的删除行
    diff_del_lines: set[int] = set()
    for del_line in modifiedLines["delete"]:
        for hunk_start, hunk_end in hunk_map.values():
            if hunk_start <= del_line <= hunk_end:
                break
        else:
            diff_del_lines.add(del_line)
    logging.debug("[METHOD_MAP] step7 diff_del_lines (unmatched): %s", sorted(diff_del_lines))

    # 步骤8: 针对 HunkMap 计算相似度
    if sim_thres is not None:
        logging.debug("[METHOD_MAP] step8 计算相似度 (阈值: %s)", sim_thres)
        for a_hunk, b_hunk in hunk_map.items():
            tmp_map_set = set()
            for a_line in range(a_hunk[0], a_hunk[1] + 1):
                a_code_line = a_method.rel_lines[a_line].strip()
                similarity = 0
                sim_line = 0
                for b_line in range(b_hunk[0], b_hunk[1] + 1):
                    if b_line in tmp_map_set:
                        continue
                    b_code_line = b_method.rel_lines[b_line].strip()
                    ratio = Levenshtein.ratio(a_code_line, b_code_line)
                    if ratio > similarity:
                        similarity = ratio
                        sim_line = b_line
                if similarity >= sim_thres:
                    line_map[a_line] = sim_line
                    tmp_map_set.add(sim_line)
                    logging.debug("[METHOD_MAP]   ✅ a:%-4d → b:%-4d (sim=%.3f) | %s",
                                  a_line, sim_line, similarity, a_code_line)
                else:
                    logging.debug("[METHOD_MAP]   ❌ a:%-4d (sim=%.3f < %.2f, best=%d) | %s",
                                  a_line, similarity, sim_thres, sim_line, a_code_line)
    else:
        logging.debug("[METHOD_MAP] step8 跳过相似度计算 (sim_thres=None)")

    logging.debug("[METHOD_MAP] 最终 line_map: %s", dict(sorted(line_map.items())))
    logging.debug("[METHOD_MAP] 最终 hunk_map: %s", hunk_map)
    logging.debug("[METHOD_MAP] 最终 diff_add_lines: %s", sorted(diff_add_lines))
    logging.debug("[METHOD_MAP] 最终 diff_del_lines: %s", sorted(diff_del_lines))
    logging.debug("=" * 70)

    return line_map, hunk_map, diff_add_lines, diff_del_lines


def code_map(a_code: str, b_code: str, suffix: str = ".c"):
    modifiedLines = difftools.parse_diff_from_codes(a_code, b_code)
    sourceOldFileMap, targetOldFileMap = difftools.sourtarContextMap(a_code, b_code, modifiedLines)
    delLinesGroup, addLinesGroup = sourtarDiffMap(modifiedLines)
    line_map = method_linemap(sourceOldFileMap, targetOldFileMap)
    hunk_map = method_hunkmap(delLinesGroup, addLinesGroup, line_map)

    # 计算未匹配上的新增行
    diff_add_lines: set[int] = set()
    for add_line in modifiedLines["add"]:
        for hunk_start, hunk_end in hunk_map.keys():
            if hunk_start <= add_line <= hunk_end:
                break
        else:
            diff_add_lines.add(add_line)

    # 计算未匹配上的删除行
    diff_del_lines: set[int] = set()
    for del_line in modifiedLines["delete"]:
        for hunk_start, hunk_end in hunk_map.values():
            if hunk_start <= del_line <= hunk_end:
                break
        else:
            diff_del_lines.add(del_line)
    return line_map, hunk_map, diff_add_lines, diff_del_lines


def common_pred_dominant_line(base_line: int, a_method: Method, b_method: Method, line_map: dict[int, int]) -> tuple[int, int] | None:
    assert a_method.pdg is not None
    nodes = a_method.pdg.get_nodes_by_line_number(base_line)
    assert len(nodes) == 1
    base_node = nodes[0]

    pred_dominance = base_node.pred_dominance
    while pred_dominance is not None:
        assert pred_dominance.line_number is not None
        pred_dominance_rel_line = pred_dominance.line_number - a_method.start_line + 1
        if pred_dominance_rel_line in line_map:
            logging.info(
                f"🔍 找到共同前向支配节点: {pred_dominance_rel_line} -> {line_map[pred_dominance_rel_line]}, {a_method.rel_lines[pred_dominance_rel_line].strip()} -> {b_method.rel_lines[line_map[pred_dominance_rel_line]].strip()}")
            return pred_dominance_rel_line, line_map[pred_dominance_rel_line]
        else:
            pred_dominance = base_node.pred_dominance

    # 如果没有 pred_dominance, 寻找共同行
    pred_line = base_line - 1
    while pred_line > a_method.start_line:
        pred_rel_line = pred_line - a_method.start_line + 1
        if pred_rel_line in line_map:
            logging.info(
                f"🔍 找到共同前向支配节点: {pred_rel_line} -> {line_map[pred_rel_line]}, {a_method.rel_lines[pred_rel_line].strip()} -> {b_method.rel_lines[line_map[pred_rel_line]].strip()}")
            return pred_rel_line, line_map[pred_rel_line]
        pred_line -= 1

    assert False


def common_succ_dominant_line(base_line: int, a_method: Method, b_method: Method, line_map: dict[int, int]) -> tuple[int, int] | None:
    assert a_method.pdg is not None
    nodes = a_method.pdg.get_nodes_by_line_number(base_line)
    assert len(nodes) == 1
    base_node = nodes[0]

    succ_dominance = base_node.succ_dominance
    while succ_dominance is not None:
        assert succ_dominance.line_number is not None
        succ_dominance_rel_line = succ_dominance.line_number - a_method.start_line + 1
        if succ_dominance_rel_line in line_map:
            logging.info(
                f"🔍 找到共同后向支配节点: {succ_dominance_rel_line} -> {line_map[succ_dominance_rel_line]}, {a_method.rel_lines[succ_dominance_rel_line].strip()} -> {b_method.rel_lines[line_map[succ_dominance_rel_line]].strip()}")
            return succ_dominance_rel_line, line_map[succ_dominance_rel_line]
        else:
            succ_dominance = base_node.succ_dominance

    # 如果没有 succ_dominance, 寻找共同行
    succ_line = base_line + 1
    while succ_line < a_method.end_line:
        succ_rel_line = succ_line - a_method.start_line + 1
        if succ_rel_line in line_map:
            logging.info(
                f"🔍 找到共同后向支配节点: {succ_rel_line} -> {line_map[succ_rel_line]}, {a_method.rel_lines[succ_rel_line].strip()} -> {b_method.rel_lines[line_map[succ_rel_line]].strip()}")
            return succ_rel_line, line_map[succ_rel_line]
        succ_line += 1

    assert False
