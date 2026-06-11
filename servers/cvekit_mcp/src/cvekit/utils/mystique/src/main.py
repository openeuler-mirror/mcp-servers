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


import argparse
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Iterable

import ast_parser
import config
import difftools
import format
import joern
import llm
import log
import utils
from ast_parser import ASTParser
from codefile import CodeFile, create_code_tree
from common import Language
from cross_method import (
    _find_functions_containing_lines,
    build_method_artifacts_for_signatures,
    build_method_dependency_clusters,
    detect_modified_methods,
    extract_new_defines,
    solve_cluster_jointly,
)
from external_migration import migrate_external_changes
from project import Project
from semantic_sanitizer import repair_broken_string_newlines
from signature_modifiers import restore_target_signature_modifiers

# Ensure the cvekit package root (4 levels up) is importable from this file.
# main.py → cvekit/utils/mystique/src/ → ../../../../ → cvekit_mcp/src/
_CVEKIT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if os.path.isdir(_CVEKIT_ROOT) and _CVEKIT_ROOT not in sys.path:
    sys.path.insert(0, _CVEKIT_ROOT)


def _get_changed_lines_from_diff(file1: str, file2: str) -> tuple[set[int], set[int]]:
    """通过 git diff 获取两个文件之间的变更行号（基于 @@ 头解析，不依赖 difft）。"""
    diff = difftools.git_diff_file(file1, file2)
    parsed = difftools.parse_diff(diff)
    return set(parsed["delete"]), set(parsed["add"])


def _resolve_input_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    if os.path.exists(path):
        return path
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    alt = os.path.join(project_root, path)
    if os.path.exists(alt):
        return alt
    return path


def detect_language(file_path: str) -> Language:
    if file_path.endswith(".java"):
        return Language.JAVA
    return Language.C


def _parse_patch_hunk_ranges(patch_text: str) -> dict[str, tuple[set[int], set[int]]]:
    """Parse git patch output, extract (pre_changed_lines, post_changed_lines) per file.

    Returns {file_path: (pre_lines, post_lines)} mapping.
    Only captures line numbers, not relying on hunk header function context.
    """
    file_ranges: dict[str, tuple[set[int], set[int]]] = {}
    current_file: str | None = None
    pre_changed: set[int] = set()
    post_changed: set[int] = set()
    pre_line = 0
    post_line = 0

    for line in patch_text.splitlines():
        if line.startswith("diff --git a/"):
            # Save previous file's ranges
            if current_file is not None:
                file_ranges[current_file] = (pre_changed, post_changed)
            parts = line.split(" b/")
            if len(parts) >= 2:
                current_file = parts[1]
                pre_changed = set()
                post_changed = set()
        elif line.startswith("@@"):
            m = re.match(r"@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@", line)
            if m:
                pre_line = int(m.group(1))
                post_line = int(m.group(2))
        elif line.startswith("-") and not line.startswith("---"):
            pre_changed.add(pre_line)
            pre_line += 1
        elif line.startswith("+") and not line.startswith("+++"):
            post_changed.add(post_line)
            post_line += 1
        else:
            pre_line += 1
            post_line += 1

    if current_file is not None:
        file_ranges[current_file] = (pre_changed, post_changed)

    return file_ranges


@dataclass
class PatchHunk:
    """Represents a single hunk in a git patch with extracted function context."""
    func_name: str  # Function name extracted from @@ ... @@ func context
    pre_start: int  # Starting line number in pre version
    pre_changed: set[int]  # Line numbers changed in pre version
    post_start: int  # Starting line number in post version
    post_changed: set[int]  # Line numbers changed in post version


def _parse_patch_hunks(patch_text: str) -> dict[str, list[PatchHunk]]:
    """Parse git patch output and extract detailed hunk information including function names.

    Parses the @@ -start,len +start,len @@ func_name pattern to extract:
    - Function name from the hunk header context
    - Line numbers changed in both pre and post versions

    Returns {file_path: [PatchHunk, ...]} mapping.
    """
    file_hunks: dict[str, list[PatchHunk]] = {}
    current_file: str | None = None
    pre_changed: set[int] = field(default_factory=set)
    post_changed: set[int] = field(default_factory=set)
    pre_line = 0
    post_line = 0
    current_func = ""

    for line in patch_text.splitlines():
        if line.startswith("diff --git a/"):
            # Save previous file's hunks
            if current_file is not None and (pre_changed or post_changed):
                file_hunks.setdefault(current_file, []).append(
                    PatchHunk(current_func, pre_line, pre_changed, post_line, post_changed)
                )
            parts = line.split(" b/")
            if len(parts) >= 2:
                current_file = parts[1]
                pre_changed = set()
                post_changed = set()
                current_func = ""
        elif line.startswith("@@"):
            # Save previous hunk if exists
            if current_file is not None and (pre_changed or post_changed):
                file_hunks.setdefault(current_file, []).append(
                    PatchHunk(current_func, pre_line, pre_changed, post_line, post_changed)
                )
            # Parse @@ -start,len +start,len @@ func_name
            m = re.match(r"@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@\s*(.*)$", line)
            if m:
                pre_line = int(m.group(1))
                post_line = int(m.group(2))
                current_func = m.group(3).strip() if m.group(3) else ""
                pre_changed = set()
                post_changed = set()
        elif line.startswith("-") and not line.startswith("---"):
            pre_changed.add(pre_line)
            pre_line += 1
        elif line.startswith("+") and not line.startswith("+++"):
            post_changed.add(post_line)
            post_line += 1
        else:
            pre_line += 1
            post_line += 1

    # Save last hunk
    if current_file is not None and (pre_changed or post_changed):
        file_hunks.setdefault(current_file, []).append(
            PatchHunk(current_func, pre_line, pre_changed, post_line, post_changed)
        )

    return file_hunks


def _normalize_signatures(signatures: str | Iterable[str] | None) -> list[str] | None:
    if signatures is None:
        return None
    if isinstance(signatures, str):
        raw_items = [signatures]
    else:
        raw_items = list(signatures)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item:
            continue
        for token in item.split(","):
            token = token.strip()
            if token and token not in seen:
                normalized.append(token)
                seen.add(token)
    return normalized or None


def _extract_c_method_name(node) -> str | None:
    name_node = node.child_by_field_name("declarator")
    while name_node is not None and name_node.type != "identifier":
        name_node = name_node.child_by_field_name("declarator")
    if name_node is None or name_node.text is None:
        return None
    return name_node.text.decode()


def _build_c_signature_line_map(target_code: str, target_filename: str) -> dict[str, tuple[int, int]]:
    from func_parser import parse_functions

    funcs = parse_functions(target_code)
    signature_map: dict[str, tuple[int, int]] = {}
    confirmed_ranges: list[tuple[int, int]] = []
    for func in funcs:
        signature = f"{target_filename}#{func.name}"
        signature_map[signature] = (func.start_line, func.end_line)
        confirmed_ranges.append((func.start_line, func.end_line))

    # 正则结果优先；Tree-sitter 只补充正则遗漏的函数行号。
    parser = ASTParser(target_code, Language.C)
    method_nodes = sorted(
        parser.query_all(ast_parser.TS_C_METHOD),
        key=lambda node: (node.start_point[0], -node.end_point[0]),
    )
    for method_node in method_nodes:
        name = _extract_c_method_name(method_node)
        if name is None:
            continue
        signature = f"{target_filename}#{name}"
        if signature in signature_map:
            continue
        start_line = method_node.start_point[0] + 1
        end_line = method_node.end_point[0] + 1
        if any(
            confirmed_start <= start_line
            and end_line <= confirmed_end
            and (confirmed_start < start_line or end_line < confirmed_end)
            for confirmed_start, confirmed_end in confirmed_ranges
        ):
            continue
        signature_map[signature] = (start_line, end_line)
        confirmed_ranges.append((start_line, end_line))
    return signature_map


def _handle_function_declarations(
    pre_file: str,
    post_file: str,
    target_file: str,
    signatures: list[str],
    language: Language,
) -> str | None:
    """Handle migration of function declarations in header files.

    When normal method migration fails (because declarations don't have method objects),
    this function provides a simpler text-based migration for function declarations.

    Returns the patched code or None if it fails.
    """
    # Read file contents
    with open(pre_file, "r") as f:
        pre_content = f.read()
    with open(post_file, "r") as f:
        post_content = f.read()
    with open(target_file, "r") as f:
        target_content = f.read()

    pre_lines = pre_content.splitlines(keepends=True)
    post_lines = post_content.splitlines(keepends=True)
    target_lines_list = target_content.splitlines(keepends=True)

    # Use git diff + @@-based parsing to find changed line numbers
    difft_pre, difft_post = _get_changed_lines_from_diff(pre_file, post_file)
    if not difft_pre and not difft_post:
        logging.debug("No changes detected in declarations")
        return None

    logging.debug(f"Declaration changed lines: pre={difft_pre}, post={difft_post}")

    # Extract function names from signatures
    func_names = [sig.rsplit("#", 1)[-1] if "#" in sig else sig for sig in signatures]
    logging.debug(f"Declaration function names: {func_names}")

    # For each function, find where its declaration is and what changed
    replacements = []

    for func_name in func_names:
        # Find the declaration in pre, post, and target
        pre_decl_lines = []
        post_decl_lines = []
        target_decl_start = None
        target_decl_end = None

        # Search for the function declaration in pre (function name + semicolon at end of line)
        for i, line in enumerate(pre_lines):
            if func_name in line and ';' in line:
                # Found start of declaration
                pre_decl_start = i
                pre_decl_lines = [line]
                # Check if declaration spans multiple lines
                j = i + 1
                while j < len(pre_lines) and ';' not in pre_lines[j]:
                    pre_decl_lines.append(pre_lines[j])
                    j += 1
                if j < len(pre_lines):
                    pre_decl_lines.append(pre_lines[j])  # line with closing semicolon
                break

        # Search for the function declaration in post
        for i, line in enumerate(post_lines):
            if func_name in line and ';' in line:
                # Found start of declaration
                post_decl_lines = [line]
                # Check if declaration spans multiple lines
                j = i + 1
                while j < len(post_lines) and ';' not in post_lines[j]:
                    post_decl_lines.append(post_lines[j])
                    j += 1
                if j < len(post_lines):
                    post_decl_lines.append(post_lines[j])  # line with closing semicolon
                break

        # Search for the function declaration in target
        for i, line in enumerate(target_lines_list):
            if func_name in line and ';' in line:
                # Found start of declaration
                target_decl_start = i
                target_decl_end = i
                # Check if declaration spans multiple lines
                j = i + 1
                while j < len(target_lines_list) and ';' not in target_lines_list[j]:
                    j += 1
                target_decl_end = j
                break

        if target_decl_start is None:
            logging.warning(f"Could not find declaration for {func_name} in target")
            continue

        # Check if this declaration actually changed (is in difft_pre/difft_post)
        pre_changed = any(i in difft_pre for i in range(pre_decl_start + 1, pre_decl_start + len(pre_decl_lines) + 1))
        if not pre_changed:
            logging.debug(f"Declaration for {func_name} was not changed")
            continue

        # Build old and new declaration text
        old_decl = "".join(pre_decl_lines).rstrip('\n')
        new_decl = "".join(post_decl_lines).rstrip('\n')

        logging.info(f"Declaration change for {func_name}:")
        logging.info(f"  OLD: {old_decl}")
        logging.info(f"  NEW: {new_decl}")

        replacements.append((
            target_decl_start + 1,  # 1-based
            target_decl_end + 1,    # 1-based
            old_decl,
            new_decl
        ))

    if not replacements:
        logging.debug("Could not find matching declarations in target")
        return None

    # Apply replacements to target
    patched_lines = target_lines_list.copy()

    # Process replacements in reverse order to maintain line numbers
    for target_start, target_end, old_decl, new_decl in replacements:
        logging.info(f"Replacing lines {target_start}-{target_end} in target")

        # Build replacement lines
        new_lines = []
        for line in new_decl.splitlines(keepends=True):
            if not line.endswith('\n'):
                line += '\n'
            new_lines.append(line)
        if not new_lines:
            new_lines = ['\n']

        # Replace in patched_lines
        idx_start = target_start - 1
        idx_end = target_end - 1
        if 0 <= idx_start <= idx_end < len(patched_lines):
            patched_lines[idx_start:idx_end + 1] = new_lines

    return "".join(patched_lines)


def _apply_method_replacements(
    target_code: str,
    replacements: list[tuple[str, int, int, str]],
    language: Language,
    target_filename: str,
) -> str:
    lines = target_code.splitlines(keepends=True)
    resolved_ranges: list[tuple[int, int, str]] = []
    raw_line_map: dict[str, tuple[int, int]] = {}
    if language == Language.C:
        raw_line_map = _build_c_signature_line_map(target_code, target_filename)

    for signature, fallback_start_line, fallback_end_line, replacement_code in replacements:
        start_line, end_line = raw_line_map.get(signature, (fallback_start_line, fallback_end_line))
        resolved_ranges.append((start_line, end_line, replacement_code))

    for start_line, end_line, replacement_code in sorted(resolved_ranges, key=lambda x: x[0], reverse=True):
        replacement_lines = replacement_code.splitlines(keepends=True)
        if replacement_lines and not replacement_lines[-1].endswith("\n"):
            replacement_lines[-1] += "\n"
        lines[start_line - 1:end_line] = replacement_lines
    return "".join(lines)


def _log_external_migration_result(result, message: str = "函数外迁移完成") -> None:
    logging.info(
        "📋 %s: detected=%d, applied=%d, unresolved=%d",
        message,
        len(result.detected),
        len(result.applied),
        len(result.unresolved),
    )
    for unresolved in result.unresolved:
        logging.warning(
            "⚠️ 函数外修改未解决: identity=%s, reason=%s",
            unresolved.change.identity,
            unresolved.reason,
        )


def _resolve_input_path(path: str) -> str:
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded

    cwd_candidate = os.path.abspath(expanded)
    if os.path.exists(cwd_candidate):
        return cwd_candidate

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    project_candidate = os.path.abspath(os.path.join(project_root, expanded))
    if os.path.exists(project_candidate):
        return project_candidate

    return cwd_candidate


def _require_readable_file(path: str, argument_name: str) -> str:
    resolved = _resolve_input_path(path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(
            f"{argument_name} file not found: '{path}' (resolved: '{resolved}', cwd: '{os.getcwd()}')"
        )
    return resolved


def _set_method_external_diff_lines(project: Project, changed_lines: set[int]) -> None:
    """Set _external_diff_lines on all methods in a project from pre-parsed patch data."""
    logging.debug("[_set_method_external_diff_lines] project=%s, changed_lines=%s",
                  project.project_name, sorted(changed_lines))
    for file in project.files:
        for clazz in file.classes:
            for method in clazz.methods:
                filtered = {l for l in changed_lines
                            if method.start_line <= l <= method.end_line}
                logging.debug("[_set_method_external_diff_lines] class method %s (lines %d-%d): "
                              "changed_lines in range = %s",
                              method.signature, method.start_line, method.end_line,
                              sorted(filtered))
                method._external_diff_lines = filtered
        for method in file.methods:
            filtered = {l for l in changed_lines
                        if method.start_line <= l <= method.end_line}
            logging.debug("[_set_method_external_diff_lines] file method %s (lines %d-%d): "
                          "changed_lines in range = %s",
                          method.signature, method.start_line, method.end_line,
                          sorted(filtered))
            method._external_diff_lines = filtered


def patchbp(
    pre_method_file: str,
    post_method_file: str,
    target_method_file: str,
    language: Language,
    signatures: list[str] | None = None,
    overwrite: bool = False,
    pre_changed_lines: set[int] | None = None,
    post_changed_lines: set[int] | None = None,
) -> str:
    pre_method_file = _resolve_input_path(pre_method_file)
    post_method_file = _resolve_input_path(post_method_file)
    target_method_file = _resolve_input_path(target_method_file)

    with open(pre_method_file, "r") as f:
        pre_method_code = f.read()
    with open(post_method_file, "r") as f:
        post_method_code = f.read()
    with open(target_method_file, "r") as f:
        target_method_code = f.read()

    input_hash = hashlib.md5((pre_method_code + post_method_code + target_method_code).encode()).hexdigest()[:10]
    cache_dir = f"cache/{input_hash}"
    os.makedirs(cache_dir, exist_ok=True)
    pre_dir = os.path.join(cache_dir, "pre")
    post_dir = os.path.join(cache_dir, "post")
    target_dir = os.path.join(cache_dir, "target")

    # 使用统一的虚拟文件名，保证 pre/post/target 方法签名可对齐
    virtual_file_name = os.path.basename(target_method_file)
    pre_codefile = CodeFile(virtual_file_name, pre_method_code)
    post_codefile = CodeFile(virtual_file_name, post_method_code)
    target_codefile = CodeFile(virtual_file_name, target_method_code)

    logging.info("main.py:create_code_tree: 在指定目录下创建代码树结构，将代码文件的格式化内容写入目录")
    logging.info(f"  输入: code_files=[{virtual_file_name}], dir={pre_dir}")
    create_code_tree([pre_codefile], pre_dir, overwrite=overwrite)
    logging.info(f"  输出: {pre_dir}/code")

    logging.info("main.py:create_code_tree: 在指定目录下创建代码树结构，将代码文件的格式化内容写入目录")
    logging.info(f"  输入: code_files=[{virtual_file_name}], dir={post_dir}")
    create_code_tree([post_codefile], post_dir, overwrite=overwrite)
    logging.info(f"  输出: {post_dir}/code")

    logging.info("main.py:create_code_tree: 在指定目录下创建代码树结构，将代码文件的格式化内容写入目录")
    logging.info(f"  输入: code_files=[{virtual_file_name}], dir={target_dir}")
    create_code_tree([target_codefile], target_dir, overwrite=overwrite)
    logging.info(f"  输出: {target_dir}/code")

    logging.info("main.py:export_joern_graph: 为三个代码目录导出 Joern 图（CPG 和 PDG）")
    logging.info(f"  输入: pre_dir={pre_dir}, post_dir={post_dir}, target_dir={target_dir}, language={language}")
    utils.export_joern_graph(
        pre_dir,
        post_dir,
        target_dir,
        need_cdg=False,
        language=language,
        multiprocess=True,
        overwrite=overwrite,
    )
    logging.info(f"  输出: {pre_dir}/cpg, {pre_dir}/pdg, {post_dir}/cpg, {post_dir}/pdg, {target_dir}/cpg, {target_dir}/pdg")

    logging.info("main.py:Project: 创建项目对象，管理项目中的文件、导入、类、方法和字段")
    logging.info(f"  输入: project_name=1.pre, files=[{virtual_file_name}], language={language}")
    pre_project = Project("1.pre", [pre_codefile], language)
    logging.info(f"  输出: pre_project")

    logging.info("main.py:Project: 创建项目对象，管理项目中的文件、导入、类、方法和字段")
    logging.info(f"  输入: project_name=2.post, files=[{virtual_file_name}], language={language}")
    post_project = Project("2.post", [post_codefile], language)
    logging.info(f"  输出: post_project")

    logging.info("main.py:Project: 创建项目对象，管理项目中的文件、导入、类、方法和字段")
    logging.info(f"  输入: project_name=3.target, files=[{virtual_file_name}], language={language}")
    target_project = Project("3.target", [target_codefile], language)
    logging.info(f"  输出: target_project")
    triple_projects = (pre_project, post_project, target_project)

    # 从格式化后的 pre/post 文件中直接 diff 获取正确的变更行号。
    # 外部传入的 pre_changed_lines/post_changed_lines 来自原始 commit 的补丁解析，
    # 其行号基于原始内核源码（含空行），而项目代码已经过 format() 处理（空行已删除、
    # 宏已删除），两套坐标系不一致。直接 diff 格式化后的文件可保证行号始终匹配。
    formatted_pre_file = os.path.join(pre_dir, "code", virtual_file_name)
    formatted_post_file = os.path.join(post_dir, "code", virtual_file_name)
    if os.path.exists(formatted_pre_file) and os.path.exists(formatted_post_file):
        with open(formatted_pre_file) as f:
            pre_code = f.read()
        with open(formatted_post_file) as f:
            post_code = f.read()
        # 使用 difflib.unified_diff 而非 git diff -w -b，避免缩进差异被忽略。
        parsed = difftools.parse_diff_from_codes(pre_code, post_code)
        pre_changed = set(parsed["delete"])
        post_changed = set(parsed["add"])
        pre_lines = pre_code.split('\n')
        post_lines = post_code.split('\n')
        logging.debug("[EXTERNAL_DIFF] 从格式化文件 diff 获取变更行: pre=%s, post=%s",
                      sorted(pre_changed), sorted(post_changed))
        logging.debug("[EXTERNAL_DIFF] --- 格式化 pre 文件变更行内容 (%d 行) ---", len(pre_changed))
        for ln in sorted(pre_changed):
            if 1 <= ln <= len(pre_lines):
                logging.debug("[EXTERNAL_DIFF]   pre:%-4d | %s", ln, pre_lines[ln - 1])
        logging.debug("[EXTERNAL_DIFF] --- 格式化 post 文件变更行内容 (%d 行) ---", len(post_changed))
        for ln in sorted(post_changed):
            if 1 <= ln <= len(post_lines):
                logging.debug("[EXTERNAL_DIFF]   post:%-3d | %s", ln, post_lines[ln - 1])
        _set_method_external_diff_lines(pre_project, pre_changed)
        _set_method_external_diff_lines(post_project, post_changed)
    else:
        if pre_changed_lines is not None:
            _set_method_external_diff_lines(pre_project, pre_changed_lines)
        if post_changed_lines is not None:
            _set_method_external_diff_lines(post_project, post_changed_lines)

    logging.info("main.py:load_joern_graph: 加载 Joern 图（CPG 和 PDG）到项目中")
    logging.info(f"  输入: cpg_dir={pre_dir}/cpg, pdg_dir={pre_dir}/pdg")
    pre_project.load_joern_graph(f"{pre_dir}/cpg", f"{pre_dir}/pdg")
    logging.info(f"  输出: pre_project.joern")

    logging.info("main.py:load_joern_graph: 加载 Joern 图（CPG 和 PDG）到项目中")
    logging.info(f"  输入: cpg_dir={post_dir}/cpg, pdg_dir={post_dir}/pdg")
    post_project.load_joern_graph(f"{post_dir}/cpg", f"{post_dir}/pdg")
    logging.info(f"  输出: post_project.joern")

    logging.info("main.py:load_joern_graph: 加载 Joern 图（CPG 和 PDG）到项目中")
    logging.info(f"  输入: cpg_dir={target_dir}/cpg, pdg_dir={target_dir}/pdg")
    target_project.load_joern_graph(f"{target_dir}/cpg", f"{target_dir}/pdg")
    logging.info(f"  输出: target_project.joern")

    if signatures:
        selected_signatures = signatures
    else:
        logging.info("main.py:detect_modified_methods: 检测两个项目之间被修改的方法")
        logging.info(f"  输入: pre_project=1.pre, post_project=2.post")
        selected_signatures = detect_modified_methods(pre_project, post_project,
                                                      pre_method_file, post_method_file)
        logging.info(f"  输出: {selected_signatures}")

    if not selected_signatures:
        if language == Language.C:
            external_result = migrate_external_changes(
                pre_method_code,
                post_method_code,
                target_method_code,
            )
            _log_external_migration_result(external_result)
            return external_result.code
        logging.warning("⚠️ 未检测到可迁移的修改函数，直接返回原始 target")
        return target_method_code

    logging.info(f"🔍 本次待迁移函数数: {len(selected_signatures)}")
    for sig in selected_signatures:
        logging.info(f"  - {sig}")

    new_defines = extract_new_defines(pre_method_code, post_method_code, language)
    if new_defines:
        logging.info(f"📋 检测到新增宏定义: {new_defines}")
    else:
        logging.info("📋 未检测到新增宏定义")

    logging.info("main.py:build_method_dependency_clusters: 根据方法间的调用关系和标识符共享关系，将方法签名聚类成依赖簇")
    logging.info(f"  输入: signatures={selected_signatures}, language={language}")
    clusters = build_method_dependency_clusters(
        selected_signatures,
        pre_project,
        post_project,
        target_project,
        language,
    )
    logging.info(f"  输出: clusters={clusters}")

    logging.info("main.py:build_method_artifacts_for_signatures: 为给定的方法签名列表构建补丁工件，包含切片代码、补丁代码等信息")
    logging.info(f"  输入: signatures={selected_signatures}, cache_dir={cache_dir}, language={language}")
    artifacts_by_signature, prepare_failed_signatures = build_method_artifacts_for_signatures(
        selected_signatures, triple_projects, cache_dir, language
    )
    logging.info(f"  输出: artifacts_by_signature.keys()={list(artifacts_by_signature.keys())}, prepare_failed_signatures={prepare_failed_signatures}")

    replacements: list[tuple[str, int, int, str]] = []
    solve_failed_signatures: list[str] = []
    for cluster in clusters:
        logging.info("main.py:solve_cluster_jointly: 联合求解一个方法簇的补丁问题，首先尝试直接移植，失败则使用 LLM 进行联合修复")
        logging.info(f"  输入: cluster={cluster}, language={language}")
        cluster_replacements, cluster_failed = solve_cluster_jointly(cluster, artifacts_by_signature, language, new_defines)
        logging.info(f"  输出: cluster_replacements={cluster_replacements}, cluster_failed={cluster_failed}")
        replacements.extend(cluster_replacements)
        solve_failed_signatures.extend(cluster_failed)

    if not replacements:
        # Check if we have function declarations that couldn't be processed
        # Try a simpler text-based approach for declarations
        if prepare_failed_signatures:
            logging.info("尝试处理函数声明...")
            try:
                decl_replacement = _handle_function_declarations(
                    pre_method_file, post_method_file, target_method_file,
                    prepare_failed_signatures, language
                )
                if decl_replacement:
                    logging.info("函数声明处理成功")
                    if language == Language.C:
                        external_result = migrate_external_changes(
                            pre_method_code,
                            post_method_code,
                            decl_replacement,
                        )
                        _log_external_migration_result(
                            external_result,
                            "函数声明回退后的函数外迁移完成",
                        )
                        return external_result.code
                    return decl_replacement
            except Exception as e:
                logging.warning(f"函数声明处理失败: {e}")

        if language == Language.C:
            external_result = migrate_external_changes(
                pre_method_code,
                post_method_code,
                target_method_code,
            )
            _log_external_migration_result(
                external_result,
                "函数迁移失败后的函数外迁移完成",
            )
            return external_result.code
        logging.warning("❌ 所有函数迁移失败，返回原始 target")
        return target_method_code

    logging.info("main.py:_apply_method_replacements: 将修复后的代码应用到目标代码中")
    logging.info(f"  输入: target_code={len(target_method_code)} chars, replacements={len(replacements)} 个, language={language}")
    patched_code = _apply_method_replacements(
        target_method_code,
        replacements,
        language,
        os.path.basename(target_method_file),
    )
    logging.info(f"  输出: patched_code={len(patched_code)} chars")

    if language == Language.C:
        external_result = migrate_external_changes(
            pre_method_code,
            post_method_code,
            patched_code,
        )
        patched_code = external_result.code
        _log_external_migration_result(external_result)

    failed_signatures = sorted(set(prepare_failed_signatures + solve_failed_signatures))
    return patched_code


def main(
    pre_method_file: str,
    post_method_file: str,
    target_method_file: str,
    signatures: list[str] | None = None,
) -> str:
    pre_method_file = _require_readable_file(pre_method_file, "--pre")
    post_method_file = _require_readable_file(post_method_file, "--post")
    target_method_file = _require_readable_file(target_method_file, "--target")

    language = detect_language(pre_method_file)
    normalized_signatures = _normalize_signatures(signatures)
    return patchbp(
        pre_method_file,
        post_method_file,
        target_method_file,
        language,
        signatures=normalized_signatures,
        overwrite=False,
    )


def _write_result_file(result: str, target_path: str, output_path: str | None = None) -> str:
    if output_path:
        resolved = os.path.abspath(os.path.expanduser(output_path))
        parent = os.path.dirname(resolved)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(resolved, "w") as f:
            f.write(result)
        return resolved

    preferred = os.path.abspath(os.path.join(os.path.dirname(target_path), "patched"))
    try:
        with open(preferred, "w") as f:
            f.write(result)
        return preferred
    except (PermissionError, IsADirectoryError) as exc:
        fallback = os.path.abspath(os.path.join(os.getcwd(), f"patched_{os.path.basename(target_path)}"))
        with open(fallback, "w") as f:
            f.write(result)
        logging.warning(
            "默认输出路径不可写或不可用 (%s)，已回退写入: %s",
            preferred,
            fallback,
        )
        logging.debug("写入失败原因: %s", exc)
        return fallback


def _git_get_file_content(repo_path: str, ref: str, file_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "show", f"{ref}:{file_path}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        logging.warning(f"无法获取文件内容: {repo_path}:{file_path} at {ref}")
        return None


def _git_get_commit_changed_files(repo_path: str, commit_id: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--name-status", f"{commit_id}^..{commit_id}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logging.error(f"获取 commit 修改文件列表失败: {e}")
        return []

    files = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", maxsplit=2)
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R"):
            old_path = parts[1]
            new_path = parts[2] if len(parts) > 2 else parts[1]
        else:
            old_path = parts[1]
            new_path = parts[1]

        if not new_path.endswith((".c", ".h", ".java")):
            continue
        files.append({
            "status": status[0],
            "old_path": old_path,
            "new_path": new_path,
        })
    return files


def _git_resolve_ref(repo_path: str, ref: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", ref],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _git_checkout(repo_path: str, ref: str) -> bool:
    try:
        subprocess.run(
            ["git", "-C", repo_path, "checkout", ref],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"切换分支失败: {repo_path} -> {ref}: {e}")
        return False


def _build_backported_patch_path(
    result_dir: str,
    cve_id: str | None,
    commit: str,
    timestamp: str,
) -> str:
    """Build a timestamped patch path."""
    short_cve = f"_{cve_id}" if cve_id else ""
    commit_short = commit[:12] if len(commit) >= 12 else commit
    stem = f"backported{short_cve}_{commit_short}_{timestamp}"
    return os.path.join(result_dir, f"{stem}.patch")


def _save_original_patch(
    project_dir: str,
    result_dir: str,
    commit: str,
) -> tuple[str | None, str | None]:
    """Save the source commit patch and return its content and path."""
    try:
        result = subprocess.run(
            ["git", "-C", project_dir, "format-patch", "-1", commit, "--stdout"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logging.warning("无法生成原始补丁文件: %s", exc.stderr.strip())
        return None, None

    original_patch_path = os.path.join(result_dir, f"original_{commit}.patch")
    with open(original_patch_path, "w") as f:
        f.write(result.stdout)
    logging.info(f"原始补丁文件已保存: {original_patch_path}")
    return result.stdout, original_patch_path


def _build_mystique_log_path(cve_id: str | None, timestamp: str) -> str:
    """Build the logfile path for one Mystique backport run."""
    log_dir = os.path.join(os.path.expanduser("~"), ".cvekit", "mystique_logs")
    tag = cve_id or "unknown"
    return os.path.join(log_dir, f"backport_{tag}_{timestamp}.log")


def _git_find_file_in_target(target_path: str, target_ref: str, source_file_path: str) -> str | None:
    content = _git_get_file_content(target_path, target_ref, source_file_path)
    if content is not None:
        return source_file_path

    basename = os.path.basename(source_file_path)
    try:
        result = subprocess.run(
            ["git", "-C", target_path, "ls-tree", "-r", "--name-only", target_ref],
            capture_output=True,
            text=True,
            check=True,
        )
        candidates = [
            line for line in result.stdout.strip().splitlines()
            if line.endswith(basename)
        ]
        if len(candidates) == 1:
            logging.info(f"文件路径映射: {source_file_path} -> {candidates[0]}")
            return candidates[0]
        if len(candidates) > 1:
            for candidate in candidates:
                if candidate.endswith(source_file_path):
                    logging.info(f"文件路径映射: {source_file_path} -> {candidate}")
                    return candidate
            logging.warning(
                f"目标仓库中找到多个同名文件 {basename}，无法自动映射: {candidates}"
            )
            return None
    except subprocess.CalledProcessError:
        pass

    logging.warning(f"目标仓库中未找到文件: {source_file_path}")
    return None




def _strip_format_only_changes(target_content: str, patched_code: str) -> str:
    """Strip format-only changes by comparing lines after removing trailing `{` / `}`.

    Uses SequenceMatcher to find replace blocks, then replaces patched lines
    with target's original lines when normalized content matches (handling
    brace migration between same-line and next-line).
    """
    import difflib

    target_lines = target_content.splitlines(keepends=True)
    patched_lines = patched_code.splitlines(keepends=True)

    def strip_brace(line: str) -> str:
        s = line.rstrip()
        if s.endswith(("{", "}")):
            s = s[:-1].rstrip()
        return re.sub(r"\s+", "", s)

    def is_brace_line(line: str) -> bool:
        return line.strip() in ("{", "}")

    # Merge standalone brace lines into previous line, track original ranges.
    def merge_with_ranges(lines: list[str]) -> tuple[list[str], list[tuple[int, int]]]:
        merged = []
        ranges = []
        for i, line in enumerate(lines):
            if merged and is_brace_line(line):
                merged[-1] = merged[-1].rstrip() + "\n" + line
                ranges[-1] = (ranges[-1][0], i + 1)
            else:
                merged.append(line)
                ranges.append((i, i + 1))
        return merged, ranges

    t_merged, t_ranges = merge_with_ranges(target_lines)
    p_merged, p_ranges = merge_with_ranges(patched_lines)

    sm = difflib.SequenceMatcher(None, t_merged, p_merged, autojunk=False)

    out = list(patched_lines)
    changed = False

    for tag, ti1, ti2, pi1, pi2 in sm.get_opcodes():
        if tag != "replace":
            continue

        # Build semantic match map within this replace block.
        # normalized target content -> target merged index
        norm_to_tidx: dict[str, int] = {}
        for tidx in range(ti1, ti2):
            n = strip_brace(t_merged[tidx])
            if n:
                norm_to_tidx[n] = tidx

        used_t: set[int] = set()
        for pidx in range(pi1, pi2):
            p_norm = strip_brace(p_merged[pidx])
            if not p_norm:
                continue
            tidx = norm_to_tidx.get(p_norm)
            if tidx is None or tidx in used_t:
                continue
            used_t.add(tidx)

            # Replace patched's original lines with target's original lines
            po_start, po_end = p_ranges[pidx]
            to_start, to_end = t_ranges[tidx]
            p_orig = "".join(patched_lines[po_start:po_end])
            t_orig = "".join(target_lines[to_start:to_end])
            if t_orig != p_orig:
                out[po_start:po_end] = [t_orig]
                changed = True

    if changed:
        return "".join(out)
    return patched_code


def _normalize_patched_formatting(
    patched_code: str,
    target_content: str,
    language: Language,
    file_signatures: list[str] | None = None,
    target_path: str | None = None,
    target_file_path: str | None = None,
    file_patch: str | None = None,
) -> str:
    """Normalize patched code formatting to match target style, function by function.

    Iterates until no more formatting differences are found (max 3 rounds).
    """
    import ast_parser

    if language != Language.C:
        logging.info("Skipping format normalization for non-C language: %s", language.value)
        return patched_code

    if config.FORMAT_NORMALIZATION_MODE == "changed_regions":
        from changed_region_formatter import (
            apply_repo_clang_format,
            normalize_changed_regions,
            restore_patch_added_blank_lines,
        )

        logging.info("Using changed-region LLM format normalization")
        normalized = normalize_changed_regions(
            patched_code,
            target_content,
            file_signatures,
        )
        if target_path and target_file_path:
            normalized = apply_repo_clang_format(
                normalized,
                target_content,
                target_path,
                target_file_path,
            )
        normalized = restore_patch_added_blank_lines(normalized, file_patch)
        return normalized

    logging.info(
        "Starting format normalization: patched=%d chars, target=%d chars",
        len(patched_code), len(target_content),
    )

    # Extract modified function names from signatures
    modified_names: set[str] = set()
    if file_signatures:
        for sig in file_signatures:
            if "#" in sig:
                modified_names.add(sig.rsplit("#", 1)[1])
            else:
                modified_names.add(sig)
        logging.info("Format normalization limited to modified functions: %s", sorted(modified_names))

    def _extract_functions(code: str) -> list:
        funcs: list[tuple[str, int, int, list[str]]] = []
        lines = code.split("\n")
        from func_parser import parse_functions_with_tree_sitter

        for func in parse_functions_with_tree_sitter(code):
            s = func.start_line
            e = func.end_line
            text = lines[s - 1 : e]
            funcs.append((func.name, s, e, text))
        return funcs

    def _process_one_pass(current_code: str, target_code: str) -> tuple[str, int]:
        """Do one pass of format normalization. Returns (new_code, fixes_count)."""
        t_funcs = _extract_functions(target_code)
        p_funcs = _extract_functions(current_code)

        logging.info(
            "  _process_one_pass: extracted %d target funcs, %d patched funcs",
            len(t_funcs), len(p_funcs),
        )
        t_func_names = sorted(set(f[0] for f in t_funcs))
        p_func_names = sorted(set(f[0] for f in p_funcs))
        logging.info("  target func names: %s", t_func_names)
        logging.info("  patched func names: %s", p_func_names)

        if not t_funcs or not p_funcs:
            logging.warning("  _process_one_pass: empty funcs, t=%d p=%d, returning early",
                          len(t_funcs), len(p_funcs))
            return current_code, 0

        t_map: dict[str, list] = {}
        for name, start, end, text in t_funcs:
            t_map.setdefault(name, []).append((start, end, text))

        p_map: dict[str, list] = {}
        for name, start, end, text in p_funcs:
            p_map.setdefault(name, []).append((start, end, text))

        if modified_names:
            in_t_not_p = modified_names & set(t_map.keys()) - set(p_map.keys())
            in_p_not_t = modified_names & set(p_map.keys()) - set(t_map.keys())
            check_names = modified_names & set(t_map.keys()) & set(p_map.keys())
            if in_t_not_p:
                logging.warning("  modified funcs in target but NOT in patched: %s", sorted(in_t_not_p))
            if in_p_not_t:
                logging.warning("  modified funcs in patched but NOT in target: %s", sorted(in_p_not_t))
        else:
            check_names = set(t_map.keys()) & set(p_map.keys())

        logging.info("  check_names (intersection): %s", sorted(check_names))

        # Sort by position in current file
        work_items: list[tuple[int, str, list, list]] = []
        for func_name in check_names:
            p_entries = p_map[func_name]
            t_entries = t_map[func_name]
            if p_entries:
                work_items.append((p_entries[0][1], func_name, t_entries, p_entries))
        work_items.sort(key=lambda x: x[0])

        if not work_items:
            return current_code, 0

        result_lines = current_code.split("\n")
        fixes = 0
        line_offset = 0
        processed: set[tuple[int, int]] = set()

        for _, func_name, t_entries, p_entries in work_items:
            for t_start, t_end, t_text in t_entries:
                for p_start, p_end, p_text in p_entries:
                    if (p_start, p_end) in processed:
                        continue

                    if t_text == p_text:
                        processed.add((p_start, p_end))
                        continue

                    # Pure whitespace (same line count, same stripped content)
                    t_ws = [l.strip() for l in t_text]
                    p_ws = [l.strip() for l in p_text]
                    if t_ws == p_ws and len(t_text) == len(p_text):
                        adj_s = p_start - 1 + line_offset
                        adj_e = p_end + line_offset
                        result_lines[adj_s:adj_e] = t_text
                        fixes += 1
                        processed.add((p_start, p_end))
                        logging.info(
                            "  FIX (local) %s: lines %d-%d (adj %d-%d)",
                            func_name, p_start, p_end, adj_s + 1, adj_e,
                        )
                        continue

                    # Real difference — send to LLM
                    target_str = "\n".join(t_text)
                    patched_str = "\n".join(p_text)
                    adj_s = p_start - 1 + line_offset
                    adj_e = p_end + line_offset

                    prompt = f"""\
Reformat the PATCHED function below to match the TARGET function's FORMATTING STYLE only.

CRITICAL: You MUST call the `validate_formatting` tool to verify your output before finalizing:
  validate_formatting(original_code=<PATCHED code below>, formatted_code=<your reformatted output>)
If the tool reports errors, fix them and call the tool again until it returns success (empty string).

Formatting changes ONLY:
- indentation (spaces vs tabs), whitespace, blank lines, spacing around operators
- brace style (K&R vs Allman), but every brace must keep its matching pair

NEVER change: identifiers, types, keywords, statements, parameters, logic, braces count, semicolons.

=== TARGET function ({len(t_text)} lines) — FORMATTING REFERENCE only ===
{target_str}

=== PATCHED function ({len(p_text)} lines) — reformat this, KEEP ALL CODE CHANGES ===
{patched_str}

Output ONLY the reformatted function, no explanations, no markdown fences.
"""

                    logging.info(
                        "  LLM '%s': patched lines %d-%d (adj %d-%d), prompt=%d chars",
                        func_name, p_start, p_end, adj_s + 1, adj_e, len(prompt),
                    )

                    try:
                        result = llm.llm_generate(
                            prompt,
                            temperature=0,
                            tools=[llm.validate_formatting],
                            system_message="You are a C code formatting expert. Reformat the patched function to match the target's style while preserving ALL code changes. Always call validate_formatting tool to verify your output before finalizing.",
                        )

                        if not result:
                            logging.warning("  LLM returned empty for '%s'", func_name)
                            continue

                        cleaned = re.sub(r"<antThinking>.*?</antThinking>", "", result, flags=re.DOTALL)
                        cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL)
                        cleaned = re.sub(r"<\|begin_thinking\|>.*?<\|end_thinking\|>", "", cleaned, flags=re.DOTALL)
                        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
                        cleaned = re.sub(r"^```(?:c|C|cpp|CPP)?\s*\n", "", cleaned, flags=re.MULTILINE)
                        cleaned = re.sub(r"\n```\s*$", "", cleaned, flags=re.DOTALL)
                        cleaned = cleaned.strip()

                        if not cleaned:
                            logging.warning("  Cleaned empty for '%s'", func_name)
                            continue

                        if len(cleaned) < len(patched_str) * 0.3:
                            logging.warning(
                                "  Result too small for '%s' (%d vs %d), skipping",
                                func_name, len(cleaned), len(patched_str),
                            )
                            continue

                        replacement_lines = cleaned.split("\n")
                        orig_count = p_end - p_start + 1
                        delta = len(replacement_lines) - orig_count

                        # Safety net: re-validate with the same logic the tool uses.
                        # The LLM should have self-corrected via validate_formatting tool,
                        # but reject here if something still slipped through.
                        val_result = llm.validate_formatting.invoke({
                            "original_code": patched_str,
                            "formatted_code": cleaned,
                        })
                        if val_result:
                            logging.warning(
                                "  REJECTED (safety net) '%s': %s",
                                func_name, val_result[:300],
                            )
                            processed.add((p_start, p_end))
                            continue

                        # Log what's being replaced
                        orig_preview = "; ".join(result_lines[adj_s:min(adj_s + 3, adj_e)])
                        if adj_e - adj_s > 3:
                            orig_preview += " ..."
                        logging.info(
                            "  FIX (LLM) '%s': adj %d-%d (%d lines -> %d lines), delta=%+d",
                            func_name, adj_s + 1, adj_e, orig_count, len(replacement_lines), delta,
                        )
                        logging.info("    Was: %s", orig_preview[:200])
                        logging.info("    Now: %s", "; ".join(replacement_lines[:3])[:200])

                        result_lines[adj_s:adj_e] = replacement_lines
                        line_offset += delta
                        fixes += 1
                        processed.add((p_start, p_end))

                    except Exception as e:
                        logging.warning("  LLM failed for '%s': %s", func_name, e)

        return "\n".join(result_lines), fixes

    # Iterative normalization: re-check after each round until clean or max rounds
    current_code = patched_code
    max_rounds = 3
    for round_num in range(1, max_rounds + 1):
        logging.info("=== Format normalization round %d/%d ===", round_num, max_rounds)
        current_code, fixes = _process_one_pass(current_code, target_content)
        logging.info("Round %d: %d fixes applied", round_num, fixes)
        if fixes == 0:
            logging.info("No more format differences found, done.")
            break

    return current_code


def _generate_unified_patch(
    target_path: str,
    target_ref: str,
    target_file_path: str,
    patched_code: str,
    simplified_target: str | None = None,
) -> str | None:
    """Generate unified diff between target and patched code.

    Args:
        target_path: Path to target git repository
        target_ref: Git ref (commit hash, branch, etc.)
        target_file_path: Path to file in repository
        patched_code: The patched code
        simplified_target: If provided, use this as reference instead of full git content.
                         This is needed when patchbp uses a simplified target file.
    """
    # If simplified_target is provided, use it for diff generation
    # This ensures line numbers match between patchbp and diff generation
    if simplified_target is not None:
        target_content = simplified_target
    else:
        target_content = _git_get_file_content(target_path, target_ref, target_file_path)
        if target_content is None:
            return None

    if target_content == patched_code:
        return None

    import difflib
    target_lines = target_content.splitlines(keepends=True)
    patched_lines = patched_code.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        target_lines,
        patched_lines,
        fromfile=f"a/{target_file_path}",
        tofile=f"b/{target_file_path}",
    ))
    if not diff_lines:
        return None

    header = f"diff --git a/{target_file_path} b/{target_file_path}\n"
    return header + "".join(diff_lines)


def _find_functions_by_hunk_lines(
    code: str,
    hunks: list[PatchHunk],
    language: Language,
) -> set[str]:
    """Find modified function names by combining git hunk context with line-based detection.

    For each hunk:
    1. Extract potential function name from git hunk context (may be inaccurate)
    2. Use line numbers to find which function actually contains the hunk
    3. Validate/override the git context function name with the line-based result

    Args:
        code: The source code (pre version)
        hunks: List of PatchHunks with line numbers and git context function names
        language: Programming language

    Returns:
        Set of verified function names that are actually modified
    """
    from func_parser import parse_functions

    # Build a map of line number -> function name using func_parser
    line_to_func: dict[int, str] = {}
    func_infos: dict[str, tuple[int, int]] = {}  # func_name -> (start_line, end_line)

    for func in parse_functions(code):
        for line_num in range(func.start_line, func.end_line + 1):
            line_to_func[line_num] = func.name
        func_infos[func.name] = (func.start_line, func.end_line)

    modified_funcs: set[str] = set()

    for hunk in hunks:
        # Collect all line numbers from this hunk (both pre and post)
        all_hunk_lines = hunk.pre_changed | hunk.post_changed
        if not all_hunk_lines and hunk.pre_start:
            # If no specific lines changed but hunk has a start, use the start line
            all_hunk_lines.add(hunk.pre_start)

        # Find which function(s) these lines belong to
        hunk_funcs: set[str] = set()
        for line_num in all_hunk_lines:
            if line_num in line_to_func:
                hunk_funcs.add(line_to_func[line_num])

        # Validate that found functions actually overlap with changed lines.
        # parse_functions may report incorrect ranges for inline functions in headers,
        # so we verify the overlap before accepting.
        validated_funcs: set[str] = set()
        for func_name in hunk_funcs:
            if func_name in func_infos:
                start, end = func_infos[func_name]
                # Check if any changed line falls within this function's range
                if any(start <= ln <= end for ln in all_hunk_lines):
                    validated_funcs.add(func_name)
        hunk_funcs = validated_funcs

        # If we found validated functions via line mapping, use them
        if hunk_funcs:
            modified_funcs.update(hunk_funcs)
        elif hunk.func_name:
            # Fallback: try to extract function name from git context
            # But first validate that the function actually contains changed lines
            import re
            m = re.match(r"^\s*(?:static\s+|inline\s+|__\w+\s+)*(?:const\s+)?[\w\*]+\s+(\w+)\s*\([^)]*\)\s*[{;]?\s*$", hunk.func_name)
            if m:
                func_name = m.group(1)
                # Filter out obvious non-functions
                if func_name not in ("if", "else", "while", "for", "switch", "do", "catch", "namespace"):
                    # Validate that this function overlaps with changed lines
                    if func_name in func_infos:
                        start, end = func_infos[func_name]
                        if any(start <= ln <= end for ln in all_hunk_lines):
                            modified_funcs.add(func_name)
                    else:
                        # func_name not found by parse_functions, trust git context but log warning
                        logging.warning(
                            "  函数 '%s' (来自git context) 未在代码中找到定义，跳过",
                            func_name
                        )

        # If still no functions found, try to find the function that actually contains
        # the changed lines (search all functions and find the one whose range contains
        # any of the changed lines, even if parse_functions reported wrong ranges)
        if not modified_funcs and all_hunk_lines:
            for func_name, (start, end) in func_infos.items():
                if any(start <= ln <= end for ln in all_hunk_lines):
                    modified_funcs.add(func_name)
                    logging.warning(
                        "  使用行范围重叠检测到修改的函数: %s (lines %d-%d, changed lines: %s)",
                        func_name, start, end, all_hunk_lines
                    )

    return modified_funcs


def _extract_file_patch(patch_text: str, file_path: str) -> str | None:
    """Extract the diff section for a single file from git format-patch output.

    Returns the ``diff --git a/<file> b/<file> ...`` block (inclusive), or None
    if the file is not found in the patch.
    """
    marker = f"\ndiff --git a/{file_path} b/{file_path}\n"
    idx = patch_text.find(marker)
    if idx == -1:
        # Try with a/ prefix already in patch_text
        marker = f"diff --git a/{file_path} b/{file_path}\n"
        idx = patch_text.find(marker)
    if idx == -1:
        return None

    # Find the next diff --git (if any) to delimit this file's section
    rest = patch_text[idx + len(marker):]
    next_idx = rest.find("\ndiff --git ")
    if next_idx != -1:
        return marker + rest[:next_idx] + "\n"
    else:
        # Last file in the patch — strip trailing marker like "-- \n2.x.x"
        tail_marker = "\n-- \n"
        tail_idx = rest.find(tail_marker)
        if tail_idx != -1:
            return marker + rest[:tail_idx] + "\n"
        return marker + rest.rstrip("\n") + "\n"


def _try_apply_patch(repo_path: str, file_patch: str, file_path: str) -> bool:
    """Try ``git apply --check`` a single-file patch against a repo.

    Returns True if the patch applies cleanly.
    """
    import subprocess
    proc = subprocess.run(
        ["git", "apply", "--check", "--verbose", "-"],
        cwd=repo_path,
        input=file_patch,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        logging.info(f"  ✅ git apply --check 成功，跳过迁移: {file_path}")
        return True
    else:
        stderr_first = proc.stderr.strip().split("\n")[0] if proc.stderr else ""
        logging.info(f"  ❌ git apply --check 失败，走 mystique 流程: {file_path} — {stderr_first}")
        return False


_mystique_env_initialized = False
_mystique_logfile: str | None = None


def _init_mystique_env(
    debug: bool = False,
    cve_id: str | None = None,
    timestamp: str | None = None,
) -> str | None:
    global _mystique_env_initialized, _mystique_logfile
    if _mystique_env_initialized:
        return _mystique_logfile
    log_level = logging.DEBUG if debug else logging.INFO
    joern.set_joern_env(config.JOERN_PATH)
    timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _mystique_logfile = _build_mystique_log_path(cve_id, timestamp)
    log.init_logger(
        logging.getLogger(),
        log_level,
        _mystique_logfile,
        exact_path=True,
    )
    _mystique_env_initialized = True
    return _mystique_logfile


def main_from_repo(
    project_dir: str,
    target_path: str,
    new_patch: str,
    target_release: str,
    signatures: list[str] | None = None,
    output: str | None = None,
    cve_id: str | None = None,
    skip_cherry_pick: bool = False,
    debug: bool = False,
) -> list[dict]:
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logfile = _init_mystique_env(debug=debug, cve_id=cve_id, timestamp=run_timestamp)
    project_dir = os.path.abspath(os.path.expanduser(project_dir))
    target_path = os.path.abspath(os.path.expanduser(target_path))

    if not os.path.isdir(project_dir):
        raise FileNotFoundError(f"源代码仓库路径不存在: {project_dir}")
    if not os.path.isdir(target_path):
        raise FileNotFoundError(f"目标代码仓库路径不存在: {target_path}")

    commit_hash = _git_resolve_ref(project_dir, new_patch)
    if not commit_hash:
        raise ValueError(f"无法解析源仓库中的 commit: {new_patch}")
    parent_hash = _git_resolve_ref(project_dir, f"{commit_hash}^")
    if not parent_hash:
        raise ValueError(f"无法获取 commit 的父提交: {commit_hash}^")

    target_ref = _git_resolve_ref(target_path, target_release)
    if not target_ref:
        logging.warning(f"目标仓库中无法解析引用: {target_release}，尝试 checkout")
        if not _git_checkout(target_path, target_release):
            raise ValueError(f"目标仓库中无法切换到分支: {target_release}")
        target_ref = _git_resolve_ref(target_path, "HEAD")
        if not target_ref:
            raise ValueError(f"目标仓库中无法解析 HEAD")

    if output:
        result_dir = os.path.abspath(os.path.expanduser(output))
    else:
        result_dir = os.path.abspath(os.path.join(os.getcwd(), "patched_output"))
    os.makedirs(result_dir, exist_ok=True)
    patch_text, original_patch_path = _save_original_patch(
        project_dir, result_dir, commit_hash
    )

    # ── Fast path: git cherry-pick before the per-file LLM pipeline ──
    if not skip_cherry_pick:
        from cvekit.utils.tools.project import Project as CvekitProject, safe_git_reset_hard
        from cvekit.utils.agent.invoke_llm import _try_cherry_pick_backport

        _cp_data = SimpleNamespace(
            project_dir=project_dir,
            target_path=target_path,
            project_url="",
            error_message="",
            new_patch_parent=parent_hash,
            target_release=target_ref,
            new_patch=commit_hash,
            target_release_name=target_release,
            equivalent_exists=False,
        )
        _cp_project = CvekitProject(_cp_data)
        cherry_ok, cherry_patch = _try_cherry_pick_backport(_cp_project, _cp_data)
        if cherry_ok and cherry_patch:
            logging.info("cherry-pick 成功，跳过 mystique 流程")
            patch_path = _build_backported_patch_path(
                result_dir, cve_id, commit_hash, run_timestamp
            )
            with open(patch_path, "w") as f:
                f.write(cherry_patch)
            logging.info(f"补丁文件已生成: {patch_path}")
            return [{
                "status": "cherry_pick_success",
                "source_file": new_patch,
                "patched_file": patch_path,
                "original_patch_path": original_patch_path,
                "backported_patch_path": patch_path,
                "logfile": logfile,
            }]
        else:
            logging.info("cherry-pick 冲突，继续 mystique 逐文件迁移流程")

    changed_files = _git_get_commit_changed_files(project_dir, commit_hash)
    if not changed_files:
        logging.warning(f"commit {commit_hash} 未修改任何 C/H/Java 文件")
        return []

    logging.info(f"commit {commit_hash[:8]} 修改了 {len(changed_files)} 个文件:")
    for f in changed_files:
        logging.info(f"  [{f['status']}] {f['old_path']} -> {f['new_path']}")

    # Parse git format-patch to extract changed line ranges per file,
    # then use tree-sitter to map those lines to actual function names.
    file_hunk_ranges: dict[str, tuple[set[int], set[int]]] = {}
    file_hunks: dict[str, list[PatchHunk]] = {}
    if signatures is None and patch_text:
        try:
            file_hunk_ranges = _parse_patch_hunk_ranges(patch_text)
            file_hunks = _parse_patch_hunks(patch_text)
        except Exception as e:
            logging.warning(f"解析 git format-patch 失败，回退到 detect_modified_methods: {e}")

    all_patch_parts: list[str] = []
    results = []
    for file_info in changed_files:
        source_path = file_info["new_path"]
        status = file_info["status"]

        if status == "D":
            logging.info(f"跳过已删除的文件: {source_path}")
            continue

        if status == "A":
            logging.info(f"跳过新增的文件（源仓库中无 pre 版本）: {source_path}")
            continue

        pre_content = _git_get_file_content(project_dir, parent_hash, source_path)
        post_content = _git_get_file_content(project_dir, commit_hash, source_path)

        if not pre_content or not post_content:
            logging.warning(f"无法获取源仓库文件内容: {source_path}，跳过")
            continue

        target_file_path = _git_find_file_in_target(target_path, target_ref, source_path)
        if not target_file_path:
            logging.warning(f"目标仓库中未找到对应文件: {source_path}，跳过")
            continue

        target_content = _git_get_file_content(target_path, target_ref, target_file_path)
        if not target_content:
            logging.warning(f"无法获取目标仓库文件内容: {target_file_path}，跳过")
            continue

        file_patch = _extract_file_patch(patch_text, source_path) if patch_text else None

        # ── Fast path: try git apply --check with the original file patch ──
        if patch_text:
            if file_patch and _try_apply_patch(target_path, file_patch, source_path):
                all_patch_parts.append(file_patch)
                results.append({
                    "source_file": source_path,
                    "target_file": target_file_path,
                    "patched_file": "(original patch applied cleanly)",
                    "language": detect_language(source_path).value,
                })
                continue

        language = detect_language(source_path)
        file_ext = ".java" if language == Language.JAVA else ".c"

        with tempfile.TemporaryDirectory(prefix="mystique_repo_") as tmpdir:
            pre_file = os.path.join(tmpdir, f"1.pre{file_ext}")
            post_file = os.path.join(tmpdir, f"2.post{file_ext}")
            target_file = os.path.join(tmpdir, f"3.target{file_ext}")

            with open(pre_file, "w") as f:
                f.write(pre_content)
            with open(post_file, "w") as f:
                f.write(post_content)
            with open(target_file, "w") as f:
                f.write(target_content)

            # Determine signatures: user-provided > difft > git patch hunk > auto-detect
            if signatures is not None:
                file_signatures = _normalize_signatures(signatures)
            else:
                # Try git diff + @@-based parsing first
                difft_pre_changed, difft_post_changed = _get_changed_lines_from_diff(pre_file, post_file)
                if difft_pre_changed or difft_post_changed:
                    logging.info(f"  diff 检测到修改: pre行 {sorted(difft_pre_changed)}, post行 {sorted(difft_post_changed)}")
                    modified_funcs = (
                        _find_functions_containing_lines(pre_content, difft_pre_changed, language)
                        | _find_functions_containing_lines(post_content, difft_post_changed, language)
                    )
                    if modified_funcs:
                        virtual_file_name = os.path.basename(target_file)
                        file_signatures = [f"{virtual_file_name}#{fn}" for fn in sorted(modified_funcs)]
                        logging.info(f"  从 diff + func_parser 解析到函数: {sorted(modified_funcs)}")
                    else:
                        file_signatures = None
                elif source_path in file_hunks:
                    # Fallback to git patch hunk + func_parser
                    modified_funcs = _find_functions_by_hunk_lines(
                        pre_content, file_hunks[source_path], language
                    )
                    if modified_funcs:
                        virtual_file_name = os.path.basename(target_file)
                        file_signatures = [f"{virtual_file_name}#{fn}" for fn in sorted(modified_funcs)]
                        logging.info(f"  从 git patch hunk + func_parser 解析到函数: {sorted(modified_funcs)}")
                    else:
                        file_signatures = None
                elif source_path in file_hunk_ranges:
                    # Fallback to line-based function detection
                    pre_changed, post_changed = file_hunk_ranges[source_path]
                    modified_funcs = (
                        _find_functions_containing_lines(pre_content, pre_changed, language)
                        | _find_functions_containing_lines(post_content, post_changed, language)
                    )
                    if modified_funcs:
                        virtual_file_name = os.path.basename(target_file)
                        file_signatures = [
                            f"{virtual_file_name}#{fn}"
                            for fn in sorted(modified_funcs)
                        ]
                        logging.info(f"  从 git format-patch + tree-sitter 解析到函数: {sorted(modified_funcs)}")
                    else:
                        file_signatures = None
                else:
                    file_signatures = None

            logging.info(f"开始迁移文件: {source_path}")
            logging.info(f"  函数签名: {file_signatures}")
            pre_changed = file_hunk_ranges.get(source_path, (set(), set()))[0] if file_hunk_ranges else None
            post_changed = file_hunk_ranges.get(source_path, (set(), set()))[1] if file_hunk_ranges else None
            patched_code = patchbp(
                pre_file,
                post_file,
                target_file,
                language,
                signatures=file_signatures,
                overwrite=False,
                pre_changed_lines=pre_changed,
                post_changed_lines=post_changed,
            )

        safe_name = source_path.replace("/", "_").replace(".", "_")

        # Detect whether any actual changes were made — if the patched code is
        # equivalent to the target after normalisation, all functions in this
        # file were already ported (equivalent changes already present).
        need_not_ported = (
            format.normalize(patched_code) == format.normalize(target_content)
        )

        if need_not_ported:
            logging.info(
                "⚡ 文件 %s 所有函数已合入目标,无需移植 (need not ported)",
                source_path,
            )
            results.append({
                "source_file": source_path,
                "target_file": target_file_path,
                "patched_file": None,
                "language": language.value,
                "status": "need_not_ported",
            })
            continue

        # 1. Save raw LLM output (before any formatting)
        patched_code = restore_target_signature_modifiers(
            patched_code, target_content, file_signatures
        )
        # Repair the common LLM error that turns an escaped "\n" into a real newline.
        patched_code = repair_broken_string_newlines(patched_code)

        raw_path = os.path.join(result_dir, f"0_raw_{safe_name}{file_ext}")
        with open(raw_path, "w") as f:
            f.write(patched_code)

        # 2. Final patched file (raw output used directly)
        result_path = os.path.join(result_dir, f"2_patched_{safe_name}{file_ext}")
        with open(result_path, "w") as f:
            f.write(patched_code)

        # 2.5. Normalize formatting to match target style via LLM
        patched_code = _normalize_patched_formatting(
            patched_code,
            target_content,
            language,
            file_signatures,
            target_path,
            target_file_path,
            file_patch,
        )

        # 2.6. Save normalized patched file (for verification)
        normalized_path = os.path.join(result_dir, f"3_normalized_{safe_name}{file_ext}")
        with open(normalized_path, "w") as f:
            f.write(patched_code)

        # 3. Generate unified diff
        patch_diff = _generate_unified_patch(
            target_path, target_ref, target_file_path, patched_code,
            simplified_target=target_content,
        )

        # 4.  checkpatch.pl检测patch，提取可通过空白调整修复的问题,将诊断反馈给现有 changed-region 格式器
        checkpatch_path = os.path.join(target_path, "scripts", "checkpatch.pl")
        if (
            patch_diff
            and config.FORMAT_NORMALIZATION_MODE == "changed_regions"
            and os.path.isfile(checkpatch_path)
        ):
            from checkpatch_formatter import (
                parse_code_style_diagnostics,
                refine_with_checkpatch_feedback,
                run_checkpatch,
            )

            _, checkpatch_output = run_checkpatch(checkpatch_path, patch_diff)
            diagnostics = parse_code_style_diagnostics(
                checkpatch_output, target_file_path
            )
            if diagnostics:
                refined_code = refine_with_checkpatch_feedback(
                    target_content,
                    patched_code,
                    target_file_path,
                    file_signatures,
                    diagnostics,
                )
                refined_diff = _generate_unified_patch(
                    target_path,
                    target_ref,
                    target_file_path,
                    refined_code,
                    simplified_target=target_content,
                )
                if refined_diff:
                    _, refined_checkpatch_output = run_checkpatch(
                        checkpatch_path, refined_diff
                    )
                    refined_diagnostics = parse_code_style_diagnostics(
                        refined_checkpatch_output, target_file_path
                    )
                    if len(refined_diagnostics) < len(diagnostics):
                        logging.info(
                            "Checkpatch-guided formatting reduced %s issues from %d to %d",
                            target_file_path,
                            len(diagnostics),
                            len(refined_diagnostics),
                        )
                        patched_code = refined_code
                        patch_diff = refined_diff
                        with open(normalized_path, "w") as f:
                            f.write(patched_code)
                    else:
                        logging.info(
                            "Checkpatch-guided formatting did not reduce issues for %s; "
                            "keeping previous formatting",
                            target_file_path,
                        )
        if patch_diff:
            all_patch_parts.append(patch_diff)
            logging.info(f"文件 {source_path} 迁移完成，已生成 diff")
        else:
            logging.warning(f"文件 {source_path} 迁移完成，但无法生成 diff")

        logging.info(f"文件 {source_path} 迁移完成，结果写入: {result_path}")
        results.append({
            "source_file": source_path,
            "target_file": target_file_path,
            "patched_file": result_path,
            "language": language.value,
            "status": "ported",
        })

    if all_patch_parts:
        combined_patch_path = _build_backported_patch_path(
            result_dir, cve_id, commit_hash, run_timestamp
        )
        with open(combined_patch_path, "w") as f:
            f.write("\n".join(all_patch_parts))
        for result in results:
            result["backported_patch_path"] = combined_patch_path
        logging.info(f"统一补丁文件已生成: {combined_patch_path}")
        checkpatch_path = os.path.join(target_path, "scripts", "checkpatch.pl")
        if os.path.isfile(checkpatch_path):
            try:
                checkpatch = subprocess.run(
                    [checkpatch_path, "--no-tree", "--strict", combined_patch_path],
                    capture_output=True,
                    text=True,
                )
                checkpatch_output = (checkpatch.stdout + checkpatch.stderr).strip()
                if checkpatch.returncode == 0:
                    logging.info("Target repository checkpatch.pl passed")
                else:
                    logging.warning(
                        "Target repository checkpatch.pl reported style issues:\n%s",
                        checkpatch_output[-4000:],
                    )
            except OSError as exc:
                logging.warning("Could not run target repository checkpatch.pl: %s", exc)
        logging.info(f"可通过以下命令应用到目标仓库:")
        logging.info(f"  git -C {target_path} apply --check {combined_patch_path}")
        logging.info(f"  git -C {target_path} apply {combined_patch_path}")
    elif results and all(r.get("status") == "need_not_ported" for r in results):
        logging.info(
            "✅ 所有文件均无需移植 (need not ported) — "
            "补丁改动已存在于目标代码中"
        )

    for result in results:
        result.setdefault("original_patch_path", original_patch_path)
        result.setdefault("logfile", logfile)

    return results


def cli():
    parser = argparse.ArgumentParser(
        description="Mystique 补丁迁移工具（支持多函数迁移）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "两种使用模式:\n"
            "  仓库模式: 通过 --project-dir / --target-path / --new-patch / --target-release 从 Git 仓库自动提取\n"
            "  文件模式: 通过 --pre / --post / --target 直接指定三个代码文件\n"
        ),
    )

    repo_group = parser.add_argument_group("仓库模式参数")
    repo_group.add_argument(
        "-p", "--project-dir",
        dest="project_dir",
        type=str,
        default=None,
        help="源代码仓库路径（包含待迁移 commit 的仓库）",
    )
    repo_group.add_argument(
        "-t", "--target-path",
        dest="target_path",
        type=str,
        default=None,
        help="目标代码仓库路径（待迁移补丁的目标仓库）",
    )
    repo_group.add_argument(
        "-n", "--new-patch",
        dest="new_patch",
        type=str,
        default=None,
        help="源代码仓库中待迁移的 commit ID",
    )
    repo_group.add_argument(
        "-r", "--target-release",
        dest="target_release",
        type=str,
        default=None,
        help="目标仓库的待迁移分支名（如 OLK-6.6）",
    )
    repo_group.add_argument(
        "--cve-id",
        dest="cve_id",
        type=str,
        default=None,
        help="CVE 编号（可选，如 CVE-2026-23000），用于生成补丁文件名",
    )

    file_group = parser.add_argument_group("文件模式参数")
    file_group.add_argument("-a", "--pre", dest="pre", type=str, default=None, help="原始代码文件 (pre)")
    file_group.add_argument("-b", "--post", dest="post", type=str, default=None, help="补丁后代码文件 (post)")
    file_group.add_argument("-c", "--target", dest="target", type=str, default=None, help="目标代码文件 (target)")

    parser.add_argument(
        "-o", "--output",
        dest="output",
        type=str,
        default=None,
        help="可选：指定补丁结果输出路径（文件模式为文件路径，仓库模式为目录路径）",
    )
    parser.add_argument(
        "-s", "--signature",
        dest="signature",
        action="append",
        default=None,
        help=(
            "指定要迁移的方法签名，可重复传入或逗号分隔。"
            "C 语言格式: '文件名#函数名'，Java 格式: '包名.类名.方法名(参数类型)'"
        ),
    )
    parser.add_argument(
        "--skip-cherry-pick",
        dest="skip_cherry_pick",
        action="store_true",
        default=False,
        help="跳过 cherry-pick 快速路径，直接走 mystique LLM 逐文件迁移流程",
    )
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help="启用调试模式，输出详细的调试日志",
    )
    parser.add_argument(
        "--format-mode",
        choices=["full", "changed"],
        default=None,
        help=(
            "格式调整模式：full为整函数格式化；changed仅格式化变化区域"
        ),
    )
    args = parser.parse_args()
    config.configure_format_normalization(args.format_mode)

    is_repo_mode = all([args.project_dir, args.target_path, args.new_patch, args.target_release])
    is_file_mode = all([args.pre, args.post, args.target])

    if is_repo_mode and is_file_mode:
        parser.error("仓库模式参数和文件模式参数不能同时使用，请选择其中一种模式")

    if not is_repo_mode and not is_file_mode:
        repo_params = {"--project-dir": args.project_dir, "--target-path": args.target_path,
                       "--new-patch": args.new_patch, "--target-release": args.target_release}
        file_params = {"--pre": args.pre, "--post": args.post, "--target": args.target}
        missing_repo = [k for k, v in repo_params.items() if not v]
        missing_file = [k for k, v in file_params.items() if not v]
        parser.error(
            f"参数不足。仓库模式缺少: {', '.join(missing_repo)}；"
            f"文件模式缺少: {', '.join(missing_file)}。\n"
            f"请提供完整的仓库模式参数 (-p/-t/-n/-r) 或文件模式参数 (-a/-b/-c)"
        )

    if is_repo_mode:
        results = main_from_repo(
            project_dir=args.project_dir,
            target_path=args.target_path,
            new_patch=args.new_patch,
            target_release=args.target_release,
            signatures=args.signature,
            output=args.output,
            cve_id=args.cve_id,
            skip_cherry_pick=args.skip_cherry_pick,
            debug=args.debug,
        )
        if not results:
            logging.warning("没有文件被成功迁移")
        else:
            logging.info(f"共成功迁移 {len(results)} 个文件:")
            for r in results:
                logging.info(f"  {r['source_file']} -> {r['patched_file']}")
        return results
    else:
        _init_mystique_env(debug=args.debug, cve_id=args.cve_id)
        result = main(args.pre, args.post, args.target, args.signature)
        result_path = _write_result_file(result, args.target, args.output)
        logging.info(f"Patched code has been written to file: {result_path}")
        return result


if __name__ == "__main__":
    import sys

    cli()
