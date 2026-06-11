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


import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable

import ast_parser
import config
import format
import hunkmap
import llm
import utils
from common import Language
from patchbp import sematic_enhance_patch, target_method_slice, transplant_hunks
from project import Method, Project


def extract_new_defines(pre_code: str, post_code: str, language: Language) -> list[str]:
    if language == Language.JAVA:
        return []
    pre_defines = set(re.findall(r"^\s*#\s*define\s+\w+.*$", pre_code, re.MULTILINE))
    post_defines = set(re.findall(r"^\s*#\s*define\s+\w+.*$", post_code, re.MULTILINE))
    new_defines = post_defines - pre_defines
    return sorted(d.strip() for d in new_defines)


@dataclass
class MethodPatchArtifacts:
    signature: str
    method_dir: str
    file_suffix: str
    target_start_line: int
    target_end_line: int
    target_method: Method
    target_slice_lines: set[int]
    patch_code: str
    pre_sliced_code: str
    target_sliced_code: str
    target_sliced_code_placeholder: str
    called_names: set[str]
    identifiers: set[str]


C_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "case", "do"}
JAVA_KEYWORDS = {"if", "for", "while", "switch", "return", "new", "throw", "catch", "super", "this"}


def _build_fallback_patch(pre_code: str, post_code: str) -> str:
    import difflib
    pre_lines = pre_code.splitlines(keepends=True)
    post_lines = post_code.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(pre_lines, post_lines, lineterm=""))
    return "\n".join(diff_lines)


def _find_func_decl_lines(parser, func_name: str) -> tuple[int | None, int | None]:
    for node in parser.query_all(ast_parser.TS_C_FUNC_DECL):
        declarator = node.child_by_field_name("declarator")
        name_node = declarator
        while name_node is not None and name_node.type != "identifier":
            next_decl = name_node.child_by_field_name("declarator")
            if next_decl is not None:
                name_node = next_decl
            else:
                for child in name_node.named_children:
                    if child.type == "identifier":
                        name_node = child
                        break
                else:
                    break
        if name_node is not None and name_node.type == "identifier" and name_node.text.decode() == func_name:
            return node.start_point[0] + 1, node.end_point[0] + 1
    return None, None


def _build_added_method_artifact(
    signature: str,
    post_method: Method,
    target_project: Project,
    language: Language,
) -> MethodPatchArtifacts | None:
    post_raw_code = post_method.file.raw_code
    post_raw_parser = ast_parser.ASTParser(post_raw_code, language)
    if post_method.body_node is not None:
        func_start, func_end = None, None
        for method_node in post_raw_parser.query_all(ast_parser.TS_C_METHOD):
            name_node = method_node.child_by_field_name("declarator")
            while name_node is not None and name_node.type != "identifier":
                next_decl = name_node.child_by_field_name("declarator")
                if next_decl is not None:
                    name_node = next_decl
                else:
                    for child in name_node.named_children:
                        if child.type == "identifier":
                            name_node = child
                            break
                    else:
                        break
            if name_node is not None and name_node.type == "identifier" and name_node.text.decode() == post_method.name:
                func_start = method_node.start_point[0] + 1
                func_end = method_node.end_point[0] + 1
                break
        if func_start is None:
            logging.warning(f"❌ 新增函数行号解析失败: {signature}")
            return None
        post_raw_lines = post_raw_code.splitlines()
        added_code = "\n".join(post_raw_lines[func_start - 1:func_end])
    else:
        post_decl_start, post_decl_end = _find_func_decl_lines(post_raw_parser, post_method.name)
        if post_decl_start is None:
            logging.warning(f"❌ 新增函数声明行号解析失败: {signature}")
            return None
        post_raw_lines = post_raw_code.splitlines()
        added_code = "\n".join(post_raw_lines[post_decl_start - 1:post_decl_end])

    target_file = target_project.files[0] if target_project.files else None
    if target_file is None:
        return None
    target_raw_code = target_file.raw_code
    target_raw_lines = target_raw_code.splitlines()

    func_name = post_method.name
    insert_line = len(target_raw_lines) + 1

    post_methods = post_method.file.methods
    post_method_idx = None
    for i, m in enumerate(post_methods):
        if m.name == func_name:
            post_method_idx = i
            break

    target_raw_parser = ast_parser.ASTParser(target_raw_code, language)
    target_method_nodes = list(target_raw_parser.query_all(ast_parser.TS_C_METHOD))

    def _find_method_end_line_in_target(method_name: str) -> int | None:
        for method_node in target_method_nodes:
            name_node = method_node.child_by_field_name("declarator")
            while name_node is not None and name_node.type != "identifier":
                next_decl = name_node.child_by_field_name("declarator")
                if next_decl is not None:
                    name_node = next_decl
                else:
                    for child in name_node.named_children:
                        if child.type == "identifier":
                            name_node = child
                            break
                    else:
                        break
            if name_node is not None and name_node.type == "identifier" and name_node.text.decode() == method_name:
                return method_node.end_point[0] + 1
        return None

    def _find_method_start_line_in_target(method_name: str) -> int | None:
        for method_node in target_method_nodes:
            name_node = method_node.child_by_field_name("declarator")
            while name_node is not None and name_node.type != "identifier":
                next_decl = name_node.child_by_field_name("declarator")
                if next_decl is not None:
                    name_node = next_decl
                else:
                    for child in name_node.named_children:
                        if child.type == "identifier":
                            name_node = child
                            break
                    else:
                        break
            if name_node is not None and name_node.type == "identifier" and name_node.text.decode() == method_name:
                return method_node.start_point[0] + 1
        return None

    if post_method_idx is not None and post_method_idx > 0:
        prev_method_name = post_methods[post_method_idx - 1].name
        prev_end = _find_method_end_line_in_target(prev_method_name)
        if prev_end is not None:
            insert_line = prev_end + 1
            logging.info(f"🆕 新增函数 {func_name} 将插入到 {prev_method_name} 之后 (行 {insert_line})")
        else:
            logging.warning(f"⚠️ 在 target 中未找到前驱函数 {prev_method_name}，尝试后继函数定位")

    if insert_line == len(target_raw_lines) + 1 and post_method_idx is not None:
        for next_idx in range(post_method_idx + 1, len(post_methods)):
            next_method_name = post_methods[next_idx].name
            next_start = _find_method_start_line_in_target(next_method_name)
            if next_start is not None:
                insert_line = next_start
                logging.info(f"🆕 新增函数 {func_name} 将插入到 {next_method_name} 之前 (行 {insert_line})")
                break
            else:
                logging.warning(f"⚠️ 在 target 中未找到后继函数 {next_method_name}，继续尝试")

    if insert_line == len(target_raw_lines) + 1:
        logging.warning(f"⚠️ 新增函数 {func_name} 无法在 target 中定位前后函数，将插入到文件末尾")

    return MethodPatchArtifacts(
        signature=signature,
        method_dir="",
        file_suffix=post_method.file_suffix,
        target_start_line=insert_line,
        target_end_line=insert_line - 1,
        target_method=post_method,
        target_slice_lines=set(),
        patch_code=added_code + "\n\n",
        pre_sliced_code="",
        target_sliced_code="",
        target_sliced_code_placeholder="",
        called_names=_extract_called_names(added_code, language),
        identifiers=_extract_identifiers(added_code, language),
    )


def _method_keywords(language: Language) -> set[str]:
    if language == Language.JAVA:
        return JAVA_KEYWORDS
    return C_KEYWORDS


def _extract_identifiers(code: str, language: Language) -> set[str]:
    import re

    keywords = _method_keywords(language)
    pattern = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
    identifiers = set(pattern.findall(code))
    return {token for token in identifiers if token not in keywords and len(token) > 1}


def _extract_called_names(code: str, language: Language) -> set[str]:
    import re

    keywords = _method_keywords(language)
    pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    called = set(pattern.findall(code))
    return {name for name in called if name not in keywords}


def _extract_changed_line_numbers(pre_code: str, post_code: str) -> tuple[set[int], set[int]]:
    """Return (pre_changed_lines, post_changed_lines) from unified diff."""
    import difflib

    pre_lines = pre_code.splitlines(keepends=True)
    post_lines = post_code.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(pre_lines, post_lines, lineterm=""))

    pre_changed: set[int] = set()
    post_changed: set[int] = set()
    pre_line = 0
    post_line = 0

    for line in diff_lines:
        if line.startswith("@@"):
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

    return pre_changed, post_changed


def _find_functions_containing_lines(code: str, lines: set[int], language: Language) -> set[str]:
    """Find which function definitions contain the given line numbers.

    For C code, uses both regex parser (func_parser) and tree-sitter to find
    function definitions and declarations. The func_parser handles kernel macros
    that tree-sitter misparses, while tree-sitter catches function declarations
    in header files that func_parser misses.
    """
    if not lines:
        return set()

    func_names: set[str] = set()

    if language == Language.C:
        from func_parser import parse_functions

        # First try func_parser for function definitions
        confirmed_ranges: list[tuple[int, int]] = []
        for func in parse_functions(code):
            confirmed_ranges.append((func.start_line, func.end_line))
            for ln in lines:
                if func.start_line <= ln <= func.end_line:
                    func_names.add(func.name)
                    break

        # Also use tree-sitter to find function declarations (for header files)
        # and any function definitions that func_parser might have missed
        parser = ast_parser.ASTParser(code, language)

        # Find function definitions
        func_nodes = sorted(
            parser.query_all(ast_parser.TS_C_METHOD),
            key=lambda node: (node.start_point[0], -node.end_point[0]),
        )
        for func_node in func_nodes:
            name_node = func_node.child_by_field_name("declarator")
            while name_node is not None and name_node.type != "identifier":
                next_decl = name_node.child_by_field_name("declarator")
                if next_decl is not None:
                    name_node = next_decl
                else:
                    for child in name_node.named_children:
                        if child.type == "identifier":
                            name_node = child
                            break
                    else:
                        break
            if name_node is not None and name_node.type == "identifier":
                func_start = func_node.start_point[0] + 1
                func_end = func_node.end_point[0] + 1
                # Skip struct designated initializers (tree-sitter misparses them)
                func_text = func_node.text.decode()
                if func_text.lstrip().startswith(".") and "=" in func_text.split("{")[0]:
                    continue
                if any(
                    confirmed_start <= func_start
                    and func_end <= confirmed_end
                    and (confirmed_start < func_start or func_end < confirmed_end)
                    for confirmed_start, confirmed_end in confirmed_ranges
                ):
                    continue
                confirmed_ranges.append((func_start, func_end))
                # Check if any changed line falls within this function
                for ln in lines:
                    if func_start <= ln <= func_end:
                        func_names.add(name_node.text.decode())
                        break

        # Also check function declarations (for header files)
        for decl_node in parser.query_all(ast_parser.TS_C_FUNC_DECL):
            # Skip abnormally large declarations (tree-sitter parse error on kernel code)
            span = decl_node.end_point[0] - decl_node.start_point[0]
            if span > 300:
                continue
            declarator = decl_node.child_by_field_name("declarator")
            name_node = declarator
            while name_node is not None and name_node.type != "identifier":
                next_decl = name_node.child_by_field_name("declarator")
                if next_decl is not None:
                    name_node = next_decl
                else:
                    for child in name_node.named_children:
                        if child.type == "identifier":
                            name_node = child
                            break
                    else:
                        break
            if name_node is not None and name_node.type == "identifier":
                decl_start = decl_node.start_point[0] + 1
                decl_end = decl_node.end_point[0] + 1
                for ln in lines:
                    if decl_start <= ln <= decl_end:
                        func_names.add(name_node.text.decode())
                        break

        return func_names

    # For non-C languages (Java, etc.), use tree-sitter directly
    parser = ast_parser.ASTParser(code, language)
    func_names: set[str] = set()

    for func_node in parser.query_all(ast_parser.TS_C_METHOD):
        name_node = func_node.child_by_field_name("declarator")
        while name_node is not None and name_node.type != "identifier":
            next_decl = name_node.child_by_field_name("declarator")
            if next_decl is not None:
                name_node = next_decl
            else:
                for child in name_node.named_children:
                    if child.type == "identifier":
                        name_node = child
                        break
                else:
                    break
        if name_node is not None and name_node.type == "identifier":
            func_start = func_node.start_point[0] + 1
            func_end = func_node.end_point[0] + 1
            # Skip struct designated initializers (tree-sitter misparses them)
            func_text = func_node.text.decode()
            if func_text.lstrip().startswith(".") and "=" in func_text.split("{")[0]:
                continue
            # Check if any changed line falls within this function
            for ln in lines:
                if func_start <= ln <= func_end:
                    func_names.add(name_node.text.decode())
                    break

    return func_names


def detect_modified_methods(pre_project: Project, post_project: Project,
                            pre_file: str = None, post_file: str = None) -> list[str]:
    """Find modified methods by mapping diff-changed lines to tree-sitter functions.

    Instead of comparing all method signatures (which produces false positives
    from tree-sitter misparsing struct designated initializers), we:
    1. Compute diff line numbers between pre and post code (using difft if available)
    2. Use tree-sitter to find which functions contain those lines
    3. Map function names to project signatures
    """
    import os
    import logging

    pre_raw = pre_project.files[0].raw_code if pre_project.files else ""
    post_raw = post_project.files[0].raw_code if post_project.files else ""

    # Try git diff + @@-based parsing first for accurate change detection
    if pre_file and post_file and os.path.exists(pre_file) and os.path.exists(post_file):
        try:
            from main import _get_changed_lines_from_diff
            ch_pre, ch_post = _get_changed_lines_from_diff(pre_file, post_file)
            if ch_pre or ch_post:
                logging.debug(f"detect_modified_methods: diff detected changes: pre={ch_pre}, post={ch_post}")
                modified_func_names = (
                    _find_functions_containing_lines(pre_raw, ch_pre, Language.C)
                    | _find_functions_containing_lines(post_raw, ch_post, Language.C)
                )
                if modified_func_names:
                    logging.debug(f"detect_modified_methods: diff found modified funcs: {modified_func_names}")
                else:
                    # Fallback if diff found no functions
                    logging.debug("detect_modified_methods: diff found no functions, falling back")
                    pre_changed, post_changed = _extract_changed_line_numbers(pre_raw, post_raw)
                    modified_func_names = (
                        _find_functions_containing_lines(pre_raw, pre_changed, Language.C)
                        | _find_functions_containing_lines(post_raw, post_changed, Language.C)
                    )
            else:
                # diff found no changes, fallback
                logging.debug("detect_modified_methods: diff found no changes, falling back")
                pre_changed, post_changed = _extract_changed_line_numbers(pre_raw, post_raw)
                modified_func_names = (
                    _find_functions_containing_lines(pre_raw, pre_changed, Language.C)
                    | _find_functions_containing_lines(post_raw, post_changed, Language.C)
                )
        except Exception as e:
            logging.debug(f"detect_modified_methods: diff failed ({e}), falling back")
            pre_changed, post_changed = _extract_changed_line_numbers(pre_raw, post_raw)
            modified_func_names = (
                _find_functions_containing_lines(pre_raw, pre_changed, Language.C)
                | _find_functions_containing_lines(post_raw, post_changed, Language.C)
            )
    else:
        pre_changed, post_changed = _extract_changed_line_numbers(pre_raw, post_raw)
        modified_func_names = (
            _find_functions_containing_lines(pre_raw, pre_changed, Language.C)
            | _find_functions_containing_lines(post_raw, post_changed, Language.C)
        )

    modified_signatures: list[str] = []

    # Map modified function names to signatures across both projects
    all_sigs = sorted(
        pre_project.methods_signature_set | post_project.methods_signature_set
    )

    # First, match modified function names to existing signatures
    for sig in all_sigs:
        if "(*" in sig:
            continue
        func_name = sig.rsplit("#", 1)[-1] if "#" in sig else sig
        if func_name in modified_func_names:
            # Verify it's a real function, not a struct field initializer
            method = pre_project.get_method(sig) or post_project.get_method(sig)
            if method is not None:
                code_stripped = method.code.lstrip()
                if code_stripped.startswith(".") and "=" in code_stripped.split("{")[0]:
                    continue
            modified_signatures.append(sig)

    # Track which modified function names were not matched to any signature
    matched_func_names = {sig.rsplit("#", 1)[-1] if "#" in sig else sig for sig in modified_signatures}
    unmatched_funcs = modified_func_names - matched_func_names

    # If there are unmatched function names (typically function declarations in headers),
    # construct signatures for them and add to the list
    if unmatched_funcs:
        # Get the filename from the first signature or use a default
        if all_sigs:
            filename = all_sigs[0].rsplit("#", 1)[0] if "#" in all_sigs[0] else "unknown"
        else:
            filename = pre_project.files[0].path if pre_project.files else "unknown"

        for func_name in sorted(unmatched_funcs):
            new_sig = f"{filename}#{func_name}"
            if new_sig not in modified_signatures:
                modified_signatures.append(new_sig)
                logging.debug(f"detect_modified_methods: added declaration signature: {new_sig}")

    # Log warning if there are unmatched modified functions
    if unmatched_funcs:
        logging.warning(
            "  ⚠️ 检测到函数声明被修改 (已添加签名): %s",
            unmatched_funcs
        )
        logging.warning(
            "  ⚠️ 这些函数可能是header文件中的声明，patchbp将尝试处理"
        )

    return modified_signatures


def build_method_dependency_clusters(
    signatures: list[str],
    pre_project: Project,
    post_project: Project,
    target_project: Project,
    language: Language,
) -> list[list[str]]:
    if len(signatures) <= 1:
        return [signatures] if signatures else []

    method_name_to_signatures: dict[str, set[str]] = {}
    signature_identifiers: dict[str, set[str]] = {}
    signature_called_names: dict[str, set[str]] = {}

    for signature in signatures:
        method = pre_project.get_method(signature) or post_project.get_method(signature) or target_project.get_method(signature)
        if method is None:
            continue
        method_name_to_signatures.setdefault(method.name, set()).add(signature)
        signature_identifiers[signature] = _extract_identifiers(method.code, language)
        signature_called_names[signature] = _extract_called_names(method.code, language)

    adjacency: dict[str, set[str]] = {sig: set() for sig in signatures}

    for sig in signatures:
        for called_name in signature_called_names.get(sig, set()):
            for dep_sig in method_name_to_signatures.get(called_name, set()):
                if dep_sig != sig:
                    adjacency[sig].add(dep_sig)
                    adjacency[dep_sig].add(sig)

    sig_list = list(signatures)
    for i, left_sig in enumerate(sig_list):
        left_ids = signature_identifiers.get(left_sig, set())
        if not left_ids:
            continue
        for right_sig in sig_list[i + 1:]:
            right_ids = signature_identifiers.get(right_sig, set())
            if not right_ids:
                continue
            if len(left_ids & right_ids) >= 3:
                adjacency[left_sig].add(right_sig)
                adjacency[right_sig].add(left_sig)

    visited: set[str] = set()
    clusters: list[list[str]] = []
    for sig in signatures:
        if sig in visited:
            continue
        stack = [sig]
        component: list[str] = []
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            stack.extend(sorted(adjacency.get(cur, set()) - visited))
        clusters.append(sorted(component))

    clusters.sort(key=lambda c: (-len(c), c[0] if c else ""))
    return clusters


def build_method_artifacts_for_signatures(
    signatures: list[str],
    triple_projects: tuple[Project, Project, Project],
    cache_dir: str,
    language: Language,
) -> tuple[dict[str, MethodPatchArtifacts], list[str]]:
    artifacts_by_signature: dict[str, MethodPatchArtifacts] = {}
    failed_signatures: list[str] = []
    for signature in signatures:
        artifact = _build_method_artifact(signature, triple_projects, cache_dir, language)
        if artifact is None:
            failed_signatures.append(signature)
            continue
        artifacts_by_signature[signature] = artifact
    return artifacts_by_signature, failed_signatures


def _build_method_artifact(
    signature: str,
    triple_projects: tuple[Project, Project, Project],
    cache_dir: str,
    language: Language,
) -> MethodPatchArtifacts | None:
    pre_project, post_project, target_project = triple_projects
    triple_methods = Project.get_triple_methods(triple_projects, signature)

    if triple_methods is None:
        post_method = post_project.get_method(signature)
        if post_method is not None and signature not in pre_project.methods_signature_set:
            logging.info(f"🆕 新增函数，使用插入模式: {signature}")
            return _build_added_method_artifact(signature, post_method, target_project, language)
        logging.warning(f"❌ 跳过方法，无法获取 triple methods: {signature}")
        return None

    pre_method, post_method, target_method = triple_methods
    pre_method.counterpart = post_method
    post_method.counterpart = pre_method

    if target_method.is_func_decl:
        logging.info(f"📋 函数声明变更，使用直接替换模式: {signature}")
        target_raw_code = target_method.file.raw_code
        post_raw_code = post_method.file.raw_code
        target_raw_parser = ast_parser.ASTParser(target_raw_code, language)
        post_raw_parser = ast_parser.ASTParser(post_raw_code, language)
        target_decl_start, target_decl_end = _find_func_decl_lines(target_raw_parser, target_method.name)
        post_decl_start, post_decl_end = _find_func_decl_lines(post_raw_parser, post_method.name)
        if target_decl_start is None or post_decl_start is None:
            logging.warning(f"❌ 函数声明行号解析失败: {signature}")
            return None
        target_raw_lines = target_raw_code.splitlines()
        post_raw_lines = post_raw_code.splitlines()
        target_decl_text = "\n".join(target_raw_lines[target_decl_start - 1:target_decl_end])
        post_decl_text = "\n".join(post_raw_lines[post_decl_start - 1:post_decl_end])
        return MethodPatchArtifacts(
            signature=signature,
            method_dir="",
            file_suffix=target_method.file_suffix,
            target_start_line=target_decl_start,
            target_end_line=target_decl_end,
            target_method=target_method,
            target_slice_lines=set(),
            patch_code=post_decl_text,
            pre_sliced_code=pre_method.code,
            target_sliced_code=target_decl_text,
            target_sliced_code_placeholder=target_decl_text,
            called_names=set(),
            identifiers=set(),
        )

    if pre_method.pdg is None or post_method.pdg is None or target_method.pdg is None:
        logging.warning(f"⚠️ 方法 PDG 缺失，使用 LLM 回退模式: {signature}")
        return MethodPatchArtifacts(
            signature=signature,
            method_dir="",
            file_suffix=target_method.file_suffix,
            target_start_line=target_method.start_line,
            target_end_line=target_method.end_line,
            target_method=target_method,
            target_slice_lines=set(),
            patch_code=_build_fallback_patch(pre_method.code, post_method.code),
            pre_sliced_code=pre_method.code,
            target_sliced_code=target_method.code,
            target_sliced_code_placeholder=target_method.code,
            called_names=_extract_called_names(target_method.code, language),
            identifiers=_extract_identifiers(target_method.code, language),
        )

    method_dir = Method.init_method_dir(triple_methods, cache_dir)
    pre_post_line_map, _, _, _ = hunkmap.method_map(pre_method, post_method)
    pre_target_line_map, pre_target_hunk_map, _, _ = hunkmap.method_map(pre_method, target_method)
    post_target_line_map, post_target_hunk_map, _, _ = hunkmap.method_map(post_method, target_method)
    post_pre_line_map = {v: k for k, v in pre_post_line_map.items()}

    backward_slice_level = config.SLICE_LEVEL
    forward_slice_level = config.SLICE_LEVEL
    pre_slice_results = pre_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
    post_slice_results = post_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
    if pre_slice_results is None or post_slice_results is None:
        logging.warning(f"❌ 跳过方法，切片失败: {signature}")
        return None

    rel_pre_lines = pre_slice_results[1]
    rel_post_lines = post_slice_results[1]
    patch_code, pre_sliced_code, _, pre_sliced_lines, _ = sematic_enhance_patch(
        rel_pre_lines,
        rel_post_lines,
        pre_method,
        post_method,
        pre_post_line_map,
        post_pre_line_map,
        pre_target_line_map,
        method_dir,
    )
    logging.info(f"📋 语义增强补丁 ({signature}):")
    logging.info(patch_code)
    target_slice_lines, target_sliced_code, target_sliced_code_placeholder = target_method_slice(
        target_method,
        pre_method,
        pre_sliced_lines,
        pre_target_line_map,
        pre_target_hunk_map,
        post_target_line_map,
        post_target_hunk_map,
        post_diff_lines=post_method.rel_diff_lines,
        method_dir=method_dir,
    )
    logging.info(f"📋 Target切片带占位符 ({signature}):")
    logging.info(target_sliced_code_placeholder)

    return MethodPatchArtifacts(
        signature=signature,
        method_dir=method_dir,
        file_suffix=target_method.file_suffix,
        target_start_line=target_method.start_line,
        target_end_line=target_method.end_line,
        target_method=target_method,
        target_slice_lines=target_slice_lines,
        patch_code=patch_code,
        pre_sliced_code=pre_sliced_code,
        target_sliced_code=target_sliced_code,
        target_sliced_code_placeholder=target_sliced_code_placeholder,
        called_names=_extract_called_names(target_method.code, language),
        identifiers=_extract_identifiers(target_method.code, language),
    )


def solve_cluster_jointly(
    cluster: list[str],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
    new_defines: list[str] | None = None,
) -> tuple[list[tuple[str, int, int, str]], list[str]]:
    solved: dict[str, tuple[int, int, str]] = {}
    failed: list[str] = []
    llm_pending: list[str] = []

    for signature in cluster:
        artifact = artifacts_by_signature.get(signature)
        if artifact is None:
            failed.append(signature)
            continue
        if artifact.target_method.is_func_decl:
            solved[signature] = (artifact.target_start_line, artifact.target_end_line, artifact.patch_code)
            continue
        if not artifact.pre_sliced_code and not artifact.target_sliced_code:
            solved[signature] = (artifact.target_start_line, artifact.target_end_line, artifact.patch_code)
            continue
        if (
            artifact.method_dir
            and artifact.target_slice_lines
            and format.normalize(artifact.pre_sliced_code) == format.normalize(artifact.target_sliced_code)
        ):
            ours_ag = transplant_hunks(artifact.target_method, artifact.target_slice_lines)
            if ours_ag:
                solved[signature] = (artifact.target_start_line, artifact.target_end_line, ours_ag)
                continue
        # Check whether the patch has already been applied to the target
        # (e.g. a prior backport).  When target@sp == post@sp the semantic
        # intent of the patch is already present — skip the LLM entirely.
        if artifact.method_dir and artifact.target_slice_lines:
            if _is_patch_already_applied(
                artifact.target_sliced_code_placeholder,
                artifact.method_dir,
                artifact.file_suffix,
            ):
                logging.info(
                    "⚡ 补丁已合入目标,跳过LLM: %s (target@sp == post@sp)",
                    signature,
                )
                solved[signature] = (
                    artifact.target_start_line,
                    artifact.target_end_line,
                    artifact.target_method.code,
                )
                continue
        llm_pending.append(signature)

    if llm_pending:
        llm_result = _joint_llm_fix_with_fallback(
            llm_pending, artifacts_by_signature, language, new_defines
        )
        logging.info(f"📋 LLM联合修复解析结果: keys={list(llm_result.keys())}, expected={llm_pending}")
        for signature in llm_pending:
            artifact = artifacts_by_signature.get(signature)
            if artifact is None:
                failed.append(signature)
                continue
            fixed_code = llm_result.get(signature)
            if fixed_code is None:
                logging.warning(f"⚠️ 签名 {signature} 未在LLM结果中找到, llm_result keys={list(llm_result.keys())}")
                failed.append(signature)
                continue
            if artifact.method_dir:
                utils.write2file(f"{artifact.method_dir}/5.ours@sp{artifact.file_suffix}", fixed_code)
            if not artifact.target_slice_lines:
                final_code = fixed_code
            else:
                final_code = artifact.target_method.recover_placeholder(fixed_code, artifact.target_slice_lines, config.PLACE_HOLDER)
            if final_code is None:
                # Strip placeholder lines from fixed_code as a last-resort fallback
                placeholder_text = config.PLACE_HOLDER.strip()
                stripped_lines = [line for line in fixed_code.splitlines(keepends=True)
                                  if line.strip() != placeholder_text]
                final_code = "".join(stripped_lines)
                logging.warning(
                    f"⚠️ 签名 {signature} recover_placeholder返回None, "
                    f"回退为移除占位符后的fixed_code(长度={len(final_code)})"
                )
            if artifact.method_dir:
                utils.write2file(f"{artifact.method_dir}/5.ours{artifact.file_suffix}", final_code)
            solved[signature] = (artifact.target_start_line, artifact.target_end_line, final_code)

    if len(solved) >= 2:
        solved = _cluster_consistency_backfill(cluster, solved, artifacts_by_signature, language)

    replacements = [(sig, *solved[sig]) for sig in cluster if sig in solved]
    unresolved = [sig for sig in cluster if sig not in solved]
    failed.extend(unresolved)
    failed = sorted(set(failed))
    return replacements, failed


def _joint_llm_fix_with_fallback(
    signatures: list[str],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
    new_defines: list[str] | None = None,
) -> dict[str, str]:
    # First try one-shot clustered repair to keep cross-method consistency.
    result = _joint_llm_fix(signatures, artifacts_by_signature, language, new_defines)
    if len(result) == len(signatures):
        return result

    missing = [sig for sig in signatures if sig not in result]
    if missing:
        logging.warning(
            "⚠️ 联合LLM结果缺失签名，降级为逐函数修复: missing=%s",
            missing,
        )

    # Fallback: request each missing signature independently so timeout in one
    # large request won't drop all methods in the cluster.
    merged = dict(result)
    for sig in missing:
        single = _joint_llm_fix([sig], artifacts_by_signature, language, new_defines)
        if sig in single:
            merged[sig] = single[sig]
    return merged


def _joint_llm_fix(
    signatures: list[str],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
    new_defines: list[str] | None = None,
) -> dict[str, str]:
    prompt = _build_joint_fix_prompt(signatures, artifacts_by_signature, language, new_defines)
    logging.info("📋 LLM联合修复提示词:")
    logging.info(prompt)

    # For large prompts that require generating lots of code, increase
    # max_tokens to avoid truncation mid-stream.
    # Estimate: the expected output size is roughly the combined length of
    # all target_sliced_code_placeholder values.  If total exceeds ~2000
    # chars, bump max_tokens to 32768.
    expected_output_size = sum(
        len(artifacts_by_signature[sig].target_sliced_code_placeholder)
        for sig in signatures
        if sig in artifacts_by_signature
    )
    max_tokens = 32768 if expected_output_size > 2000 else 16384

    # Pass compile_check tool so LLM can verify its output compiles
    compile_tool = [llm.compile_check] if language == Language.C else None
    raw = llm.llm_generate(prompt, temperature=0, tools=compile_tool, max_tokens=max_tokens)
    if raw is None:
        logging.error("❌ LLM联合修复请求失败")
        return {}
    logging.info(f"✅ LLM联合修复原始返回 (长度={len(raw)}):")
    logging.info(raw)
    result = _parse_joint_llm_output(raw, signatures)
    result = _repair_placeholder_mismatch(
        signatures, result, artifacts_by_signature, language, new_defines
    )
    return result


def _strip_placeholders(code: str) -> str:
    """Remove all placeholder lines from *code* so only real code remains."""
    placeholder_text = config.PLACE_HOLDER.strip()
    if not placeholder_text:
        return code
    lines = code.splitlines(keepends=True)
    kept = [line for line in lines if line.strip() != placeholder_text]
    return "".join(kept)


def _is_patch_already_applied(target_sp: str, method_dir: str, file_suffix: str) -> bool:
    """Check if the semantic intent of the patch is already present in the target.

    Strips placeholder lines from both the target and post-patch sliced code
    (``target@sp`` / ``2.post@sp``) before normalising and comparing.  When
    the remaining real code is equivalent, the patch changes have already
    been applied to the target and no LLM fix is needed.
    """
    import os

    if not method_dir:
        return False

    post_sp_path = os.path.join(method_dir, f"2.post@sp{file_suffix}")
    if not os.path.exists(post_sp_path):
        return False

    try:
        with open(post_sp_path, "r") as f:
            post_sp = f.read()
    except Exception:
        return False

    # Focus on *real code* — ignore placeholder lines whose positions may
    # differ between target and post due to unrelated changes.
    target_real = _strip_placeholders(target_sp)
    post_real = _strip_placeholders(post_sp)
    return format.normalize(target_real) == format.normalize(post_real)


def _placeholder_count(code: str) -> int:
    # Count lines containing the placeholder text, ignoring leading whitespace.
    # LLM may re-indent placeholder lines with tabs or different spacing.
    placeholder_text = config.PLACE_HOLDER.strip()
    if not placeholder_text:
        return 0
    count = 0
    for line in code.splitlines():
        if line.strip() == placeholder_text:
            count += 1
    return count


def _repair_placeholder_mismatch(
    signatures: list[str],
    llm_result: dict[str, str],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
    new_defines: list[str] | None = None,
) -> dict[str, str]:
    mismatch_sigs: list[str] = []
    for signature in signatures:
        artifact = artifacts_by_signature.get(signature)
        fixed_code = llm_result.get(signature)
        if artifact is None or fixed_code is None:
            continue
        if not artifact.target_slice_lines:
            continue
        expected = _placeholder_count(artifact.target_sliced_code_placeholder)
        got = _placeholder_count(fixed_code)
        if expected != got:
            mismatch_sigs.append(signature)
            logging.warning(
                "⚠️ LLM输出占位符数量不匹配: %s expected=%s got=%s",
                signature,
                expected,
                got,
            )

    if not mismatch_sigs:
        return llm_result

    retry_prompt = _build_placeholder_fix_prompt(
        mismatch_sigs, llm_result, artifacts_by_signature, language, new_defines
    )
    logging.info("📋 占位符修复重试提示词:")
    logging.info(retry_prompt)
    retry_raw = llm.llm_generate(retry_prompt, temperature=0)
    if retry_raw is None:
        logging.warning("⚠️ 占位符修复重试第1次失败(超时)，尝试第2次...")
        retry_raw = llm.llm_generate(retry_prompt, temperature=0.1)
    if retry_raw is None:
        logging.warning("⚠️ 占位符修复重试2次均失败，保留原结果")
        return llm_result
    logging.info(f"✅ 占位符修复重试原始返回 (长度={len(retry_raw)}):")
    logging.info(retry_raw)
    retry_result = _parse_joint_llm_output(retry_raw, mismatch_sigs, allow_partial=True)
    if not retry_result:
        logging.warning("⚠️ 占位符修复重试解析失败，保留原结果")
        return llm_result

    merged = dict(llm_result)
    for signature, fixed_code in retry_result.items():
        artifact = artifacts_by_signature.get(signature)
        if artifact is None:
            continue
        expected = _placeholder_count(artifact.target_sliced_code_placeholder)
        got = _placeholder_count(fixed_code)
        if expected != got:
            logging.warning(
                "⚠️ 占位符修复重试后仍不匹配: %s expected=%s got=%s，忽略该重试结果",
                signature,
                expected,
                got,
            )
            continue
        merged[signature] = fixed_code
    return merged


def _cluster_consistency_backfill(
    cluster: list[str],
    solved: dict[str, tuple[int, int, str]],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
) -> dict[str, tuple[int, int, str]]:
    prompt = _build_consistency_prompt(cluster, solved, artifacts_by_signature, language)
    raw = llm.llm_generate(prompt, temperature=0)
    if raw is None:
        return solved

    updates = _parse_joint_llm_output(raw, cluster, allow_partial=True)
    for signature, fixed_code in updates.items():
        if signature not in solved:
            continue
        start_line, end_line, _ = solved[signature]
        solved[signature] = (start_line, end_line, fixed_code)
        artifact = artifacts_by_signature.get(signature)
        if artifact is not None:
            utils.write2file(f"{artifact.method_dir}/6.ours@consistency{artifact.file_suffix}", fixed_code)
    return solved


def _build_joint_fix_prompt(
    signatures: list[str],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
    new_defines: list[str] | None = None,
) -> str:
    lang = "Java" if language == Language.JAVA else "C"
    sections: list[str] = []
    has_placeholder = any(artifact.target_slice_lines for artifact in artifacts_by_signature.values() if artifact.signature in signatures)
    for signature in signatures:
        artifact = artifacts_by_signature[signature]
        if not artifact.target_slice_lines:
            sections.append(
                (
                    f"## METHOD {signature}\n"
                    f"[PRE_CODE]\n{artifact.pre_sliced_code}\n\n"
                    f"[PATCH]\n{artifact.patch_code}\n\n"
                    f"[TARGET_CODE]\n{artifact.target_sliced_code_placeholder}\n"
                )
            )
        else:
            sections.append(
                (
                    f"## METHOD {signature}\n"
                    f"[PRE_SLICED]\n{artifact.pre_sliced_code}\n\n"
                    f"[PATCH]\n{artifact.patch_code}\n\n"
                    f"[TARGET_WITH_PLACEHOLDER]\n{artifact.target_sliced_code_placeholder}\n"
                )
            )
    defines_section = ""
    if new_defines:
        defines_text = "\n".join(new_defines)
        defines_section = f"[NEW_DEFINES]\n{defines_text}\nThese are new macro definitions introduced by the patch. Use them when replacing identifiers in the target code.\n\n"
    sig_list_str = ", ".join(signatures)
    placeholder_instruction = ""
    if has_placeholder:
        placeholder_instruction = (
            f"Placeholder token is: {config.PLACE_HOLDER}\n"
            "In [TARGET_WITH_PLACEHOLDER], some lines that are not part of the patch slice have been replaced by the "
            "placeholder token shown above. CRITICAL: Placeholders are opaque markers, NOT \"holes to fill\" or \"TODO items\". "
            "They will be automatically restored from the original target code after you produce the fixed output. "
            "Do NOT write code in place of a placeholder — leave it exactly as-is. "
            "If a code block (if/for/while) contains ONLY a placeholder and no other statements, leave the block "
            "exactly as-is with just the placeholder inside — do NOT add code to it, even if the block looks empty.\n"
            "ONLY lines that exactly match this placeholder token are placeholders — "
            "all other lines are real code that you CAN and SHOULD modify as needed.\n"
            "HARD RULES (violating these will cause output rejection):\n"
            "  - NEVER modify, move, remove, or replace any placeholder line.\n"
            "  - NEVER add new placeholder lines that don't already exist in [TARGET_WITH_PLACEHOLDER].\n"
            "  - NEVER insert a placeholder into new code you're adding from the patch.\n"
            "  - Your output MUST contain EXACTLY the same number of placeholder lines as [TARGET_WITH_PLACEHOLDER].\n\n"
        )
    return (
        f"You are fixing multiple related {lang} methods in one shot.\n"
        "Goal: apply each patch to its corresponding target while preserving behavior consistency across calls.\n\n"
        + placeholder_instruction +
        "For each method, you are given:\n"
        "- [PRE_SLICED] or [PRE_CODE]: the pre-patch code (original version before the patch was applied).\n"
        "- [PATCH]: a unified diff between pre-patch and post-patch code.\n"
        "- [TARGET_WITH_PLACEHOLDER] or [TARGET_CODE]: the target code to apply the patch to.\n\n"
        "PRIORITY CHECK — EQUIVALENT CHANGE DETECTION (do this FIRST for every method):\n"
        "Before applying any changes, determine whether the semantic intent of [PATCH] is ALREADY\n"
        "present in the target code. The target kernel branch may already contain the patch's fixes\n"
        "through prior backports or equivalent implementations — modifying the code in that case\n"
        "would introduce duplicate logic, comments, or formatting errors.\n\n"
        "The patch is ALREADY APPLIED when ALL of these hold:\n"
        "  1. Code ADDED by the patch (+ lines) already exists in the target, even with different\n"
        "     variable names, indentation, or minor restructuring.\n"
        "  2. Code REMOVED by the patch (- lines) is already absent from the target.\n"
        "  3. The target's code structure follows the POST-PATCH pattern, not the pre-patch pattern.\n"
        "  Example: if the patch replaces a list_for_each_entry_safe loop + encrypt/decrypt if-else\n"
        "  block with a direct af_alg_pull_tsgl call + memcpy_sglist, and the target already uses\n"
        "  af_alg_pull_tsgl + memcpy_sglist WITHOUT the old loop or if-else block, it's applied.\n\n"
        "RULE: If the patch IS already applied for a method, output the target code EXACTLY as\n"
        "  given — ZERO changes. Do NOT reformat, re-indent, or add any comments/code. The target\n"
        "  already has the fix; any modification would be wrong.\n\n"
        "If the patch is NOT yet applied, proceed with the fix instructions below.\n\n"
        "CORE PRINCIPLE: Your task is to apply the SEMANTIC INTENT of the patch to the target. "
        "The patch shows what changed between pre and post; you must transfer that same semantic change to the target, "
        "even when the target's code structure or identifiers differ from pre.\n\n"
        "CRITICAL RULE — FUNCTION SIGNATURE PARAMETER PROPAGATION:\n"
        "Before modifying any method body, you MUST compare the function signature in [PATCH] against the one in [TARGET_WITH_PLACEHOLDER]/[TARGET_CODE].\n"
        "If the patch adds, removes, or reorders parameters in the pre-patch function, you MUST apply the exact same change to the target's signature.\n"
        "This is a hard requirement: the patched target's function signature must be structurally consistent with the post-patch version in [PATCH],\n"
        "even when the target uses different identifiers or has a different baseline signature.\n"
        "NEVER leave the target's signature unchanged when the patch modifies it — doing so causes caller/callee mismatches and compilation errors.\n"
        "If a new parameter identifier appears in added code, you MUST ensure that identifier is declared either as a function parameter or a local variable.\n"
        "If a new parameter is added and the target already has a caller that passes an argument for it, the signature MUST be updated to accept it.\n\n"
        "To produce the fixed code:\n"
        "1. Compare [PRE_SLICED]/[PRE_CODE] with [TARGET_WITH_PLACEHOLDER]/[TARGET_CODE] to identify lines that differ between pre and target.\n"
        "2. Apply the patch changes (additions/deletions from [PATCH]) to the target.\n"
        "3. For context lines in the patch (no +/- prefix), if the target has a different version than pre, align the target line with the post version.\n"
        "4. When the patch adds new code (lines with + prefix) and the target already has structurally similar code at the same position "
        "(e.g., same control-flow pattern but different identifiers), apply the patch's semantic change to that existing target code "
        "instead of inserting a duplicate. For example, if the patch adds `if (x > NEW_MACRO)` and the target already has "
        "`if (x > OLD_MACRO)` at the corresponding position, replace OLD_MACRO with NEW_MACRO — do NOT add a second if-block.\n"
        "5. If [NEW_DEFINES] provides new macros, replace identifiers in the target code (except on placeholder lines) with the new macro names.\n"
        "6. Keep every placeholder line exactly as it appears in [TARGET_WITH_PLACEHOLDER].\n"
        "7. CRITICAL SEMANTIC RULES — violating these causes compilation errors or bugs:\n"
        "   a. Execution order: NEVER move `return` statements earlier in the function. If the\n"
        "      target has checks in order A → B → C → return, the patched version must maintain\n"
        "      that exact order. New checks from the patch should be inserted at the same logical\n"
        "      position as in the patch, NOT before existing checks that come after them.\n"
        "      Example: if target has `check_A(); check_B(); return 0;` and the patch adds\n"
        "      `check_new();` between check_A and check_B, the result must be\n"
        "      `check_A(); check_new(); check_B(); return 0;` — NOT `check_A(); check_new();\n"
        "      return 0; check_B();`\n"
        "   b. Control flow preservation: all existing `if`/`for`/`while` blocks and their\n"
        "      contents must remain in place. Do NOT remove or skip existing code paths.\n"
        "   c. BRACKET BALANCE — CRITICAL: Every opening brace `{` MUST have exactly one matching\n"
        "      closing brace `}`. Before producing your final output, count your braces:\n"
        "      the total number of `{` must equal the total number of `}` in every method.\n"
        "      An unbalanced brace (extra or missing `}`) causes the code to fail to compile.\n"
        "      Double-check: scan your output line by line and verify `{` count == `}` count.\n"
        "8. PRESERVE FORMATTING: Match the coding style of [TARGET_WITH_PLACEHOLDER] EXACTLY. "
        "This is critical — format mismatches will cause your output to be rejected:\n"
        "   - Indentation: use EXACTLY 1 tab per indent level (NOT spaces). "
        "Spaces are ONLY used for fine alignment within multi-line function signatures "
        "(e.g., `\\t\\t\\t     param_name,`).\n"
        "   - Function brace style: '{' MUST be on the NEXT line after the closing ')' "
        "of a function signature. Example:\n"
        "     GOOD: `static int foo(int x)\\n{`\n"
        "     BAD:  `static int foo(int x) {`\n"
        "   - Control flow brace style: '{' MUST be on the SAME line as 'if'/'for'/'while'/'switch'. "
        "Example:\n"
        "     GOOD: `if (error) {`\n"
        "     BAD:  `if (error)\\n{`\n"
        "   - Continuation lines: when a function signature spans multiple lines, continuation "
        "lines use 3 tabs followed by spaces to align with the opening '(' of the parameters.\n"
        "   - Blank lines: keep the exact same blank lines as the target. Do NOT add or "
        "remove blank lines between statements.\n"
        "   - Comment indentation: block comment body lines (lines starting with ' *') must "
        "use the same leading whitespace pattern as the target's comments.\n"
        "   - Do NOT change multi-line function signatures into single lines.\n\n"
        "You have access to a `compile_check` tool that verifies C code syntax using tree-sitter.\n"
        "BEFORE outputting your final answer, you MUST call `compile_check` on each method's code\n"
        "to verify there are no syntax errors (unbalanced braces, missing semicolons, etc.).\n"
        "If compile_check returns errors, fix them and check again.\n"
        "Only output code that passes compile_check.\n\n"
        + defines_section
        + "\n".join(sections)
        + f"\n\nCRITICAL — PLACEHOLDER COUNT VERIFICATION (perform BEFORE producing final output):\n"
        f"1. For each method, count how many placeholder lines appear in [TARGET_WITH_PLACEHOLDER] → N\n"
        f"2. Count how many placeholder lines appear in your output for that method → M\n"
        f"3. If N != M for ANY method, your output is WRONG — go back and fix it.\n"
        f"4. Each placeholder line must match the token text EXACTLY: {config.PLACE_HOLDER}\n"
        f"5. Each placeholder must appear at the correct position relative to the code structure.\n\n"
        f"Output each method wrapped in <<<method_SIG_START>>>/<<<method_SIG_END>>> markers.\n"
        f"For each method, the SIG is the part after '#' in the signature (e.g., ns_mkdir_op).\n"
        f"Example for signature '3.target.c#ns_mkdir_op':\n"
        f"<<<method_ns_mkdir_op_START>>>\n"
        f"static int ns_mkdir_op(...) {{\n"
        f"    ...\n"
        f"}}\n"
        f"<<<method_ns_mkdir_op_END>>>\n"
        f"Keys MUST be exactly these signatures: [{sig_list_str}].\n"
        f"No markdown, no explanation."
    )


def _build_placeholder_fix_prompt(
    signatures: list[str],
    current_result: dict[str, str],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
    new_defines: list[str] | None = None,
) -> str:
    lang = "Java" if language == Language.JAVA else "C"
    sections: list[str] = []
    for signature in signatures:
        artifact = artifacts_by_signature[signature]
        current_code = current_result.get(signature, "")
        expected = _placeholder_count(artifact.target_sliced_code_placeholder)
        got = _placeholder_count(current_code)

        # Build line-by-line placeholder position mapping to help LLM
        target_lines = artifact.target_sliced_code_placeholder.splitlines()
        current_lines = current_code.splitlines() if current_code else []

        target_placeholder_lines = []
        for i, line in enumerate(target_lines):
            if line.strip() == config.PLACE_HOLDER.strip():
                target_placeholder_lines.append(i + 1)

        current_placeholder_lines = []
        for i, line in enumerate(current_lines):
            if line.strip() == config.PLACE_HOLDER.strip():
                current_placeholder_lines.append(i + 1)

        sections.append(
            (
                f"## METHOD {signature}\n"
                f"[TARGET_WITH_PLACEHOLDER]\n{artifact.target_sliced_code_placeholder}\n\n"
                f"[CURRENT_BAD_OUTPUT]\n{current_code}\n\n"
                f"[EXPECTED_PLACEHOLDER_COUNT] {expected}\n"
                f"[CURRENT_PLACEHOLDER_COUNT] {got}\n"
                f"[TARGET_PLACEHOLDER_LINE_NUMBERS] {target_placeholder_lines}\n"
                f"[CURRENT_PLACEHOLDER_LINE_NUMBERS] {current_placeholder_lines}\n"
            )
        )
    defines_section = ""
    if new_defines:
        defines_text = "\n".join(new_defines)
        defines_section = f"[NEW_DEFINES]\n{defines_text}\n\n"
    sig_list_str = ", ".join(signatures)
    return (
        f"You are fixing placeholder-count violations in {lang} methods.\n"
        f"Placeholder token is: {config.PLACE_HOLDER}\n"
        "TASK: Restore missing placeholder lines to [CURRENT_BAD_OUTPUT] so it has EXACTLY [EXPECTED_PLACEHOLDER_COUNT] placeholders.\n"
        "A placeholder was LOST when you previously replaced it with real code. You must add it BACK.\n"
        "How to find where: compare [TARGET_PLACEHOLDER_LINE_NUMBERS] with [CURRENT_PLACEHOLDER_LINE_NUMBERS].\n"
        "Each number in [TARGET_PLACEHOLDER_LINE_NUMBERS] that is MISSING from [CURRENT_PLACEHOLDER_LINE_NUMBERS]\n"
        "indicates a placeholder that was removed and must be re-inserted at that relative position.\n"
        "Rules:\n"
        "1) Keep code semantics of [CURRENT_BAD_OUTPUT] as much as possible.\n"
        "2) Do NOT remove, alter, or merge existing placeholder lines.\n"
        "3) Do NOT add new placeholder lines beyond [EXPECTED_PLACEHOLDER_COUNT].\n"
        "4) NEVER insert a placeholder into new code you're adding from the patch.\n"
        "5) Output must contain EXACTLY [EXPECTED_PLACEHOLDER_COUNT] placeholder lines.\n"
        "6) Placeholder text must match token exactly.\n"
        "7) The placeholder must be on its OWN line, with the SAME indentation as in [TARGET_WITH_PLACEHOLDER].\n"
        "8) BRACKET BALANCE: re-verify that `{` count equals `}` count after insertion.\n"
        "9) Use the `compile_check` tool to verify C syntax before outputting your final answer.\n\n"
        + defines_section
        + "\n".join(sections)
        + f"\n\nOutput each method wrapped in <<<method_SIG_START>>>/<<<method_SIG_END>>> markers.\n"
          f"For each method, the SIG is the part after '#' in the signature.\n"
          f"Keys MUST be exactly these signatures: [{sig_list_str}].\n"
          f"No markdown, no explanation."
    )


def _build_consistency_prompt(
    cluster: list[str],
    solved: dict[str, tuple[int, int, str]],
    artifacts_by_signature: dict[str, MethodPatchArtifacts],
    language: Language,
) -> str:
    lang = "Java" if language == Language.JAVA else "C"
    sections: list[str] = []
    for signature in cluster:
        if signature not in solved:
            continue
        _, _, code = solved[signature]
        artifact = artifacts_by_signature.get(signature)
        called_names = sorted(artifact.called_names) if artifact else []
        sections.append(
            (
                f"## METHOD {signature}\n"
                f"[CALLED_NAMES] {called_names}\n"
                f"[CURRENT_CODE]\n{code}\n"
            )
        )
    return (
        f"You are reviewing a cluster of related {lang} methods.\n"
        "Task: enforce call-chain consistency only where necessary.\n"
        "Check argument usage and return-value semantics across caller-callee interactions.\n"
        "If no update needed for a method, do not include it in output.\n\n"
        + "\n".join(sections)
        + "\n\nOutput each method wrapped in <<<method_SIG_START>>>/<<<method_SIG_END>>> markers."
    )


def _decode_escaped_newlines(text: str) -> str:
    """Decode literal \\n, \\t sequences to real newlines/tabs.

    LLM APIs return JSON-encoded strings where newlines appear as
    two-character escape sequences (\\n). LangChain's agent output
    sometimes preserves these literally rather than decoding them.
    """
    # Only decode if the text appears to contain escaped sequences
    if "\\n" in text or "\\t" in text:
        return text.encode("utf-8").decode("unicode_escape")
    return text


# Known truncation markers that must never appear in LLM output.
_TRUNCATION_MARKERS = (
    "...<truncated>...",
    "/* ... prompt truncated for length ... */",
)


def _contains_truncated_marker(text: str) -> bool:
    """Check if text contains any known prompt truncation marker."""
    return any(marker in text for marker in _TRUNCATION_MARKERS)


def _parse_joint_llm_output(raw_text: str, signatures: Iterable[str], allow_partial: bool = False) -> dict[str, str]:
    """Parse LLM output using <<<method_XXX_START/END>>> markers instead of JSON."""
    signatures_set = set(signatures)
    result: dict[str, str] = {}
    # Match: <<<method_SIGNATURE_START>>>\ncode\n<<<method_XXX_END>>>
    pattern = r"<<<method_([^>]+)_START>>>(.*?)<<<method_\1_END>>>"
    for match in re.finditer(pattern, raw_text, re.DOTALL):
        sig = f"3.target.c#{match.group(1)}" if "#" not in match.group(1) else match.group(1)
        if sig not in signatures_set:
            # Try extracting just the last part after # as fallback
            parts = sig.split("#", 1)
            if len(parts) == 2 and parts[1] in signatures_set:
                sig = parts[1]
            else:
                continue
        code = _decode_escaped_newlines(match.group(2)).strip("\n")
        if _contains_truncated_marker(code):
            logging.warning(
                f"⚠️ LLM output for {sig} contains truncation marker, rejecting"
            )
            continue
        result[sig] = code

    if not result:
        # Fallback: try old JSON-based parsing for backwards compatibility
        logging.warning("⚠️ No marker-delimited methods found, falling back to JSON parsing")
        return _parse_joint_llm_json_fallback(raw_text, signatures, allow_partial)

    if not allow_partial and len(result) != len(signatures_set):
        missing = signatures_set - set(result.keys())
        logging.warning(f"⚠️ Marker parsing missing signatures: {missing}, keeping partial result")
        # Keep partial results rather than returning empty — losing matched methods
        # is worse than having a few missing from this call.
    return result


def _parse_joint_llm_json_fallback(raw_text: str, signatures: Iterable[str], allow_partial: bool = False) -> dict[str, str]:
    """Fallback: old JSON-based parser (only used when marker parsing fails)."""
    signatures_set = set(signatures)
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]

    # Strip <think> tags that break { } matching
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _try_parse(payload: str) -> dict | None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            try:
                data = json.loads(payload, strict=False)
            except Exception:
                return None
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    result_data: dict | None = None
    start = 0
    while True:
        pos = text.find("{", start)
        if pos == -1:
            break
        end = text.rfind("}")
        if end == -1 or end < pos:
            start = pos + 1
            continue
        candidate = text[pos:end + 1]
        parsed = _try_parse(candidate)
        if parsed is not None:
            result_data = parsed
            break
        start = pos + 1

    if result_data is None:
        logging.warning("⚠️ No valid JSON object found in LLM output")
        return {}

    result: dict[str, str] = {}
    for key, value in result_data.items():
        if key not in signatures_set:
            continue
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        if _contains_truncated_marker(cleaned):
            logging.warning(
                f"⚠️ LLM JSON output for {key} contains truncation marker, rejecting"
            )
            continue
        result[key] = cleaned
    if not allow_partial and len(result) != len(signatures_set):
        return {}
    return result

