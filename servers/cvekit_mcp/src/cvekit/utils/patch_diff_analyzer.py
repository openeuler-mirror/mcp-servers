"""
补丁差异分析工具 - 分析 LLM 修复后的补丁与原始补丁的差异

用于在人工确认模式下，向开发者展示 LLM 做了哪些修改。
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple


@dataclass
class HunkInfo:
    """hunk 信息"""
    old_start: int  # 原文件起始行号
    old_count: int  # 原文件行数
    new_start: int  # 新文件起始行号
    new_count: int  # 新文件行数
    context_lines: List[str] = field(default_factory=list)  # 上下文行（未修改）
    added_lines: List[str] = field(default_factory=list)  # 新增的行
    removed_lines: List[str] = field(default_factory=list)  # 删除的行


@dataclass
class PatchDifference:
    """补丁差异信息"""
    file_path: str  # 文件路径
    original_hunks: List[HunkInfo] = field(default_factory=list)  # 原始 hunks
    resolved_hunks: List[HunkInfo] = field(default_factory=list)  # 修复后的 hunks
    line_number_changed: bool = False  # 行号是否变化
    context_changed: bool = False  # 上下文是否变化
    logic_changed: bool = False  # 逻辑是否变化（实质性修改）
    changes_summary: List[str] = field(default_factory=list)  # 变更摘要


def parse_patch(patch_content: str) -> Dict[str, List[HunkInfo]]:
    """
    解析 unified diff 格式的补丁

    Returns:
        {file_path: [HunkInfo, ...]}
    """
    result = {}
    current_file = None
    current_hunk = None

    lines = patch_content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        # 解析文件头部
        if line.startswith('--- a/'):
            # 提取文件路径
            file_path_match = re.match(r'--- a/(.+)', line)
            if file_path_match:
                current_file = file_path_match.group(1)
                result[current_file] = []
            i += 1
            continue

        # 跳过 +++ 行
        if line.startswith('+++ b/'):
            i += 1
            continue

        # 解析 hunk header
        if line.startswith('@@ '):
            hunk_match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
            if hunk_match:
                hunk = HunkInfo(
                    old_start=int(hunk_match.group(1)),
                    old_count=int(hunk_match.group(2)) if hunk_match.group(2) else 1,
                    new_start=int(hunk_match.group(3)),
                    new_count=int(hunk_match.group(4)) if hunk_match.group(4) else 1,
                )

                if current_file:
                    result[current_file].append(hunk)
                    current_hunk = hunk
            i += 1
            continue

        # 解析 hunk 内容
        if current_hunk and (line.startswith('+') or line.startswith('-') or line.startswith(' ')):
            if line.startswith('+'):
                current_hunk.added_lines.append(line[1:])  # 去掉开头的 +
            elif line.startswith('-'):
                current_hunk.removed_lines.append(line[1:])  # 去掉开头的 -
            else:
                current_hunk.context_lines.append(line[1:])  # 去掉开头的空格

        i += 1

    return result


def compare_hunks(original: HunkInfo, resolved: HunkInfo) -> Dict[str, bool]:
    """
    比较两个 hunks 的差异

    Returns:
        {'line_number_changed': bool, 'context_changed': bool, 'logic_changed': bool}
    """
    result = {
        'line_number_changed': False,
        'context_changed': False,
        'logic_changed': False,
    }

    # 检查行号变化
    if original.old_start != resolved.old_start or original.new_start != resolved.new_start:
        result['line_number_changed'] = True

    # 检查上下文变化
    if set(original.context_lines) != set(resolved.context_lines):
        result['context_changed'] = True

    # 检查实质性逻辑变化
    # 如果新增或删除的代码行不同，说明逻辑有变化
    if set(original.added_lines) != set(resolved.added_lines):
        result['logic_changed'] = True
    if set(original.removed_lines) != set(resolved.removed_lines):
        result['logic_changed'] = True

    return result


def analyze_patch_differences(original_patch: str, resolved_patch: str) -> List[PatchDifference]:
    """
    分析原始补丁和修复后补丁的差异

    Args:
        original_patch: 原始补丁内容
        resolved_patch: 修复后的补丁内容

    Returns:
        PatchDifference 列表
    """
    # 解析两个补丁
    original_parsed = parse_patch(original_patch)
    resolved_parsed = parse_patch(resolved_patch)

    differences = []

    # 对比每个文件
    all_files = set(original_parsed.keys()) | set(resolved_parsed.keys())

    for file_path in all_files:
        original_hunks = original_parsed.get(file_path, [])
        resolved_hunks = resolved_parsed.get(file_path, [])

        diff = PatchDifference(file_path=file_path)
        diff.original_hunks = original_hunks
        diff.resolved_hunks = resolved_hunks

        # 如果文件只在其中一个补丁中存在，说明有重大修改
        if file_path not in original_parsed or file_path not in resolved_parsed:
            diff.logic_changed = True
            diff.changes_summary.append(f"文件 {file_path} 的补丁结构发生变化")
            differences.append(diff)
            continue

        # 对比 hunks（简单的一一对比，实际可能需要更复杂的匹配算法）
        for i, (orig_hunk, res_hunk) in enumerate(zip(original_hunks, resolved_hunks)):
            comparison = compare_hunks(orig_hunk, res_hunk)

            if comparison['line_number_changed']:
                diff.line_number_changed = True

            if comparison['context_changed']:
                diff.context_changed = True
                # 找出具体的上下文变化
                orig_ctx = set(orig_hunk.context_lines)
                res_ctx = set(res_hunk.context_lines)
                added_ctx = res_ctx - orig_ctx
                removed_ctx = orig_ctx - res_ctx

                if added_ctx or removed_ctx:
                    diff.changes_summary.append(
                        f"Hunk {i+1}: 上下文已调整以适应目标版本"
                    )

            if comparison['logic_changed']:
                diff.logic_changed = True
                # 找出具体的逻辑变化
                orig_added = set(orig_hunk.added_lines)
                res_added = set(res_hunk.added_lines)
                logic_diff = res_added - orig_added

                if logic_diff:
                    for line in logic_diff:
                        diff.changes_summary.append(
                            f"Hunk {i+1}: 新增代码 '{line.strip()[:50]}...'"
                        )

        if diff.line_number_changed or diff.context_changed or diff.logic_changed:
            differences.append(diff)

    return differences


def generate_difference_summary(differences: List[PatchDifference]) -> str:
    """
    生成差异摘要文本，用于显示给用户

    Returns:
        格式化的摘要文本
    """
    if not differences:
        return "✓ 补丁仅调整了行号，核心修改与原始补丁一致"

    summary_parts = []

    has_logic_change = any(d.logic_changed for d in differences)
    has_context_change = any(d.context_changed for d in differences)
    has_line_change = any(d.line_number_changed for d in differences)

    # 警告：实质性修改
    if has_logic_change:
        summary_parts.append("⚠️  警告：发现以下实质性修改（可能影响行为）：")
        for diff in differences:
            if diff.logic_changed:
                for change in diff.changes_summary:
                    if '新增代码' in change:
                        summary_parts.append(f"    {change}")

    # 提示：上下文调整
    if has_context_change:
        context_count = sum(len(d.changes_summary) for d in differences if d.context_changed)
        summary_parts.append(f"\nℹ️  上下文调整：{context_count} 处（已适配目标版本代码）")

    # 提示：行号调整
    if has_line_change:
        summary_parts.append("\nℹ️  行号调整：已适应目标版本的代码位置")

    return "\n".join(summary_parts)
