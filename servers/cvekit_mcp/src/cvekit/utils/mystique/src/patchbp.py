import difflib
import json
import logging
import os
import sys
import time

import config
import format
import hunkmap
import joern
import llm
import log
import utils
from ast_parser import ASTParser
from codefile import CodeFile, create_code_tree
from common import ErrorCode, Language
from project import Method, Project

try:
    import cpu_heater
except ImportError:
    cpu_heater = None


def _safe_multiprocess(args_list, func, max_workers: int | None = None):
    if cpu_heater is None:
        logging.warning("cpu_heater 不可用，已自动降级为串行执行")
        return [func(*args) for args in args_list]
    if max_workers is None:
        return cpu_heater.multiprocess(args_list, func, show_progress=True)
    return cpu_heater.multiprocess(args_list, func, max_workers=max_workers, show_progress=True)


def print_section(title: str, char: str = "="):
    """打印节标题"""
    print(f"\n{char * 80}")
    print(f"{title:^80}")
    print(f"{char * 80}\n")


def print_step(step_num: int, total: int, description: str, status: str = ""):
    """打印步骤信息"""
    if status == "success":
        status_symbol = "✅"
    elif status == "warning":
        status_symbol = "⚠️"
    elif status == "error":
        status_symbol = "❌"
    else:
        status_symbol = "🔄"
    print(f"[{step_num}/{total}] {status_symbol} {description}")


def print_result_summary(result: dict):
    """打印结果摘要"""
    print_section("补丁迁移结果摘要")
    
    print(f"{'CVE ID:':<20} {result.get('cveid', 'N/A')}")
    print(f"{'文件路径:':<20} {result.get('file_path', 'N/A')}")
    print(f"{'方法名:':<20} {result.get('method_name', 'N/A')}")
    print(f"{'迁移类型:':<20} {result.get('bptype', 'N/A')}")
    print(f"{'切片类型:':<20} {result.get('slice_type', 'N/A')}")
    print(f"{'状态:':<20} {result.get('error', 'N/A')}")
    
    if 'ours_ag' in result:
        ours_status = result['ours_ag']
        status_icon = "✅" if ours_status == "SUCCESS" else "⚠️" if ours_status == "PLACEHOLDER_FAILED" else "❌"
        print(f"{'自动生成结果:':<20} {status_icon} {ours_status}")
    
    if 'time' in result:
        print(f"{'执行时间:':<20} {result.get('time', 'N/A')} 秒")
    
    print()


def print_code_section(title: str, code: str, max_lines: int = 20):
    """打印代码片段"""
    print(f"\n{'─' * 80}")
    print(f"{title}")
    print(f"{'─' * 80}")
    lines = code.split('\n')
    if len(lines) > max_lines:
        print('\n'.join(lines[:max_lines]))
        print(f"... (共 {len(lines)} 行，仅显示前 {max_lines} 行)")
    else:
        print(code)
    print(f"{'─' * 80}\n")


def sematic_enhance_patch(rel_pre_lines: set[int], rel_post_lines: set[int],
                          pre_method: Method, post_method: Method,
                          pre_post_line_map: dict[int, int], post_pre_line_map: dict[int, int],
                          pre_target_line_map: dict[int, int],
                          method_dir: str) -> tuple[str, str, str, set[int], set[int]]:
    file_suffix = pre_method.file_suffix

    # ── logging: 输入参数 ──
    logging.debug("=" * 70)
    logging.debug(f"[sematic_enhance_patch] method_dir = {method_dir}")
    logging.debug(f"[sematic_enhance_patch] pre_method  = {pre_method.signature} (lines {pre_method.start_line}-{pre_method.end_line})")
    logging.debug(f"[sematic_enhance_patch] post_method = {post_method.signature} (lines {post_method.start_line}-{post_method.end_line})")
    logging.debug(f"[sematic_enhance_patch] rel_pre_lines  (count={len(rel_pre_lines)}) sorted = {sorted(rel_pre_lines)}")
    logging.debug(f"[sematic_enhance_patch] rel_post_lines (count={len(rel_post_lines)}) sorted = {sorted(rel_post_lines)}")

    # ── logging: rel_diff_lines 是否正确 ──
    pre_diff = pre_method.rel_diff_lines
    post_diff = post_method.rel_diff_lines
    logging.debug(f"[sematic_enhance_patch] pre_method.rel_diff_lines  (count={len(pre_diff)}) sorted = {sorted(pre_diff)}")
    logging.debug(f"[sematic_enhance_patch] post_method.rel_diff_lines (count={len(post_diff)}) sorted = {sorted(post_diff)}")

    # ── logging: rel_lines 对应内容 ──
    def _log_line_content(label: str, lines: set[int], method: Method):
        logging.debug(f"  [{label}] content ({len(lines)} lines):")
        for ln in sorted(lines):
            code = method.rel_lines.get(ln, "<MISSING>")
            logging.debug(f"    rel_line {ln:4d}: {code}")

    _log_line_content("rel_pre_lines", rel_pre_lines, pre_method)
    _log_line_content("rel_post_lines", rel_post_lines, post_method)
    _log_line_content("pre_diff_lines", pre_diff, pre_method)
    _log_line_content("post_diff_lines", post_diff, post_method)

    # ── logging: rel_pre_lines和pre_method.rel_lines的差异 ──
    pre_all_rel = set(pre_method.rel_lines.keys())
    missing_from_slice = pre_all_rel - rel_pre_lines
    logging.debug(f"[sematic_enhance_patch] pre_all_rel_lines count = {len(pre_all_rel)} (sorted = {sorted(pre_all_rel)})")
    logging.debug(f"[sematic_enhance_patch] pre lines NOT in rel_pre_lines (count={len(missing_from_slice)}):")
    for ln in sorted(missing_from_slice):
        logging.debug(f"    rel_line {ln:4d}: {pre_method.rel_lines.get(ln, '<MISSING>')}")

    pre_context_lines = rel_pre_lines - pre_diff
    post_context_lines = rel_post_lines - post_diff
    logging.debug(f"[sematic_enhance_patch] pre_context_lines (rel_pre_lines - diff)  sorted = {sorted(pre_context_lines)}")
    logging.debug(f"[sematic_enhance_patch] post_context_lines (rel_post_lines - diff) sorted = {sorted(post_context_lines)}")

    for line in pre_context_lines:
        if line not in pre_post_line_map:
            continue
        post_context_lines.add(pre_post_line_map[line])
    for line in post_context_lines:
        if line not in post_pre_line_map:
            continue
        pre_context_lines.add(post_pre_line_map[line])

    logging.debug(f"[sematic_enhance_patch] pre_context_lines (after expansion)  sorted = {sorted(pre_context_lines)}")
    logging.debug(f"[sematic_enhance_patch] post_context_lines (after expansion) sorted = {sorted(post_context_lines)}")

    pre_patchbp_lines = pre_context_lines | pre_diff
    post_patchbp_lines = post_context_lines | post_diff
    logging.debug(f"[sematic_enhance_patch] pre_patchbp_lines  (count={len(pre_patchbp_lines)}) sorted = {sorted(pre_patchbp_lines)}")
    logging.debug(f"[sematic_enhance_patch] post_patchbp_lines (count={len(post_patchbp_lines)}) sorted = {sorted(post_patchbp_lines)}")
    _log_line_content("pre_patchbp_lines", pre_patchbp_lines, pre_method)
    _log_line_content("post_patchbp_lines", post_patchbp_lines, post_method)

    pre_sliced_code = pre_method.code_by_lines(pre_patchbp_lines)
    post_sliced_code = post_method.code_by_lines(post_patchbp_lines)

    logging.debug(f"[sematic_enhance_patch] pre_sliced_code ({len(pre_sliced_code)} chars):\n{pre_sliced_code}")
    logging.debug(f"[sematic_enhance_patch] post_sliced_code ({len(post_sliced_code)} chars):\n{post_sliced_code}")

    os.makedirs(method_dir, exist_ok=True)
    utils.write2file(os.path.join(method_dir, f"1.pre@s{file_suffix}"), pre_sliced_code)
    utils.write2file(os.path.join(method_dir, f"2.post@s{file_suffix}"), post_sliced_code)
    utils.write2file(os.path.join(method_dir, f"1.pre@sp{file_suffix}"),
                     pre_method.code_by_lines(pre_patchbp_lines, placeholder=config.PLACE_HOLDER,
                                             keep_lines=pre_diff))
    utils.write2file(os.path.join(method_dir, f"2.post@sp{file_suffix}"),
                     post_method.code_by_lines(post_patchbp_lines, placeholder=config.PLACE_HOLDER,
                                               keep_lines=post_diff))
    pre_patchbp_code_lines = [pre_method.rel_lines[line] for line in sorted(pre_patchbp_lines)]
    post_patchbp_codes_lines = [post_method.rel_lines[line] for line in sorted(post_patchbp_lines)]
    patch = '\n'.join(difflib.unified_diff(pre_patchbp_code_lines, post_patchbp_codes_lines,
                                           fromfile="pre@s", tofile="post@s", lineterm="", n=10000))
    # remove patch first 3 line
    patch = '\n'.join(patch.split('\n')[3:])
    logging.debug(f"[sematic_enhance_patch] final patch ({len(patch)} chars):\n{patch}")
    utils.write2file(os.path.join(method_dir, "patch.diff"), patch)
    return patch, pre_sliced_code, post_sliced_code, pre_patchbp_lines, post_patchbp_lines


def target_method_slice(target_method: Method,
                        pre_method: Method,
                        pre_patchbp_lines: set[int], pre_target_line_map: dict[int, int],
                        pre_target_hunk_map: dict[tuple[int, int], tuple[int, int]],
                        post_target_line_map: dict[int, int] | None = None,
                        post_target_hunk_map: dict[tuple[int, int], tuple[int, int]] | None = None,
                        post_diff_lines: set[int] | None = None,
                        method_dir: str = "") -> tuple[set[int], str, str]:
    logging.debug("=" * 70)
    logging.debug("[target_method_slice] method_dir = %s", method_dir)
    logging.debug("[target_method_slice] target_method = %s (lines %d-%d)",
                  target_method.signature, target_method.start_line, target_method.end_line)
    logging.debug("[target_method_slice] pre_patchbp_lines (count=%d) sorted=%s",
                  len(pre_patchbp_lines), sorted(pre_patchbp_lines))
    logging.debug("[target_method_slice] pre_target_line_map (count=%d):", len(pre_target_line_map))
    for pre_ln in sorted(pre_target_line_map):
        logging.debug("    pre %4d -> target %4d: %s", pre_ln, pre_target_line_map[pre_ln],
                      pre_method.rel_lines.get(pre_ln, "<MISSING>").strip())
    logging.debug("[target_method_slice] pre_target_hunk_map (count=%d):", len(pre_target_hunk_map))
    for (ph_s, ph_e), (th_s, th_e) in pre_target_hunk_map.items():
        logging.debug("    pre [%d-%d] -> target [%d-%d]", ph_s, ph_e, th_s, th_e)
    logging.debug("[target_method_slice] pre_method.rel_diff_lines = %s", sorted(pre_method.rel_diff_lines))
    logging.debug("[target_method_slice] post_target_hunk_map is %s",
                  "present" if post_target_hunk_map is not None else "None")

    # ── Step 1: 从 pre_patchbp_lines 映射到 target 相对行 ──
    logging.debug("── Step 1: mapping pre_patchbp_lines to target rel lines ──")
    target_slice_rel_lines = set()
    for line in sorted(pre_patchbp_lines):
        if line in pre_target_line_map:
            tgt_line = pre_target_line_map[line]
            target_slice_rel_lines.add(tgt_line)
            logging.debug("  pre line %4d -> (line_map) -> target line %4d: %s",
                          line, tgt_line,
                          target_method.rel_lines.get(tgt_line, "<MISSING>").strip())
        else:
            mapped = False
            for pre_hunk, target_hunk in pre_target_hunk_map.items():
                pre_hunk_start_line, pre_hunk_end_line = pre_hunk
                target_hunk_start_line, target_hunk_end_line = target_hunk
                if pre_hunk_start_line <= line <= pre_hunk_end_line:
                    added = list(range(target_hunk_start_line, target_hunk_end_line + 1))
                    target_slice_rel_lines.update(added)
                    logging.debug("  pre line %4d -> (hunk [%d-%d]->[%d-%d]) -> target lines %s: %s",
                                  line, pre_hunk_start_line, pre_hunk_end_line,
                                  target_hunk_start_line, target_hunk_end_line,
                                  added,
                                  pre_method.rel_lines.get(line, "<MISSING>").strip())
                    mapped = True
                    break
            if not mapped:
                logging.debug("  pre line %4d -> NOT MAPPED: %s",
                              line, pre_method.rel_lines.get(line, "<MISSING>").strip())

    # ── Step 2: post_target_hunk_map ──
    if post_target_hunk_map is not None:
        logging.debug("── Step 2: adding post_target_hunk_map lines ──")
        for post_hunk, target_hunk in post_target_hunk_map.items():
            target_hunk_start_line, target_hunk_end_line = target_hunk
            added = list(range(target_hunk_start_line, target_hunk_end_line + 1))
            target_slice_rel_lines.update(added)
            logging.debug("  post hunk %s -> target %s, added %s", post_hunk, target_hunk, added)

    logging.debug("[target_method_slice] BEFORE AST dive, target_slice_rel_lines (count=%d) sorted=%s",
                  len(target_slice_rel_lines), sorted(target_slice_rel_lines))

    # ── Step 3: AST 切片保证语法正确 ──
    if target_method.language == Language.JAVA:
        ast = ASTParser(target_method.code, target_method.language)
        body_node = ast.query_oneshot("(method_declaration body: (block)@body)")
        if body_node is not None:
            target_slice_rel_lines = target_method.ast_dive_java(body_node, target_slice_rel_lines)
    elif target_method.language == Language.C:
        ast = ASTParser(target_method.code, target_method.language)
        body_node = ast.query_oneshot("(function_definition body: (compound_statement)@body)")
        if body_node is not None:
            target_slice_rel_lines = target_method.ast_dive_c(body_node, target_slice_rel_lines)

    logging.debug("[target_method_slice] AFTER AST dive, target_slice_rel_lines (count=%d) sorted=%s",
                  len(target_slice_rel_lines), sorted(target_slice_rel_lines))
    # Log each target slice line content
    for tln in sorted(target_slice_rel_lines):
        logging.debug("    target rel_line %4d: %s", tln,
                      target_method.rel_lines.get(tln, "<MISSING>").strip())

    # ── Step 4: 计算 target_keep_lines ──
    pre_diff_lines_in_patchbp = pre_patchbp_lines & pre_method.rel_diff_lines
    logging.debug("[target_method_slice] pre_diff_lines_in_patchbp = %s", sorted(pre_diff_lines_in_patchbp))
    target_keep_lines = set()
    target_pre_diff_lines = set()
    for pre_line in sorted(pre_diff_lines_in_patchbp):
        if pre_line in pre_target_line_map:
            tgt_keep = pre_target_line_map[pre_line]
            target_keep_lines.add(tgt_keep)
            target_pre_diff_lines.add(tgt_keep)
            logging.debug("  keep: pre diff line %4d -> (line_map) -> target keep line %4d: %s",
                          pre_line, tgt_keep,
                          target_method.rel_lines.get(tgt_keep, "<MISSING>").strip())
        else:
            for pre_hunk, target_hunk in pre_target_hunk_map.items():
                pre_hunk_start, pre_hunk_end = pre_hunk
                if pre_hunk_start <= pre_line <= pre_hunk_end:
                    added = list(range(target_hunk[0], target_hunk[1] + 1))
                    target_keep_lines.update(added)
                    target_pre_diff_lines.update(added)
                    logging.debug("  keep: pre diff line %4d -> (hunk [%d-%d]->[%d-%d]) -> target keep lines %s: %s",
                                  pre_line, pre_hunk_start, pre_hunk_end, target_hunk[0], target_hunk[1],
                                  added,
                                  pre_method.rel_lines.get(pre_line, "<MISSING>").strip())
                    break
    logging.debug("[target_method_slice] target_keep_lines (count=%d) sorted=%s",
                  len(target_keep_lines), sorted(target_keep_lines))
    for tk in sorted(target_keep_lines):
        logging.debug("    keep line %4d: %s", tk,
                      target_method.rel_lines.get(tk, "<MISSING>").strip())

    # ── Step 4.5: 将 post diff 行映射到 target keep_lines，防止补丁新增行被 placeholder 替换 ──
    if post_diff_lines is not None and post_target_line_map is not None:
        for post_line in sorted(post_diff_lines):
            if post_line in post_target_line_map:
                tgt_keep = post_target_line_map[post_line]
                target_keep_lines.add(tgt_keep)
                logging.debug("  keep: post diff line %4d -> (line_map) -> target keep line %4d: %s",
                              post_line, tgt_keep,
                              target_method.rel_lines.get(tgt_keep, "<MISSING>").strip())
    logging.debug("[target_method_slice] target_keep_lines AFTER post-diff (count=%d) sorted=%s",
                  len(target_keep_lines), sorted(target_keep_lines))

    # ── Step 5: 分析 target_slice_rel_lines 中的 gap ──
    logging.debug("── Step 5: gap analysis in target_slice_rel_lines ──")
    sorted_lines = sorted(target_slice_rel_lines)
    gap_count = 0
    for i in range(1, len(sorted_lines)):
        prev_line = sorted_lines[i - 1]
        curr_line = sorted_lines[i]
        if curr_line - prev_line > 1:
            gap_count += 1
            gap_range = list(range(prev_line + 1, curr_line))
            gap_has_keep = any(g in target_keep_lines for g in gap_range)
            gap_has_pre_diff = any(g in target_pre_diff_lines for g in gap_range)
            logging.debug("  gap #%d: target lines %d -> %d (missing lines %s), keep=%s, pre_diff=%s",
                          gap_count, prev_line, curr_line, gap_range, gap_has_keep, gap_has_pre_diff)
            for g in gap_range:
                flag = ""
                if g in target_keep_lines:
                    flag += " [KEEP]"
                if g in target_pre_diff_lines:
                    flag += " [PRE_DIFF]"
                logging.debug("    gap line %4d:%s %s", g, flag,
                              target_method.rel_lines.get(g, "<MISSING>").strip())
    logging.debug("[target_method_slice] total gaps found: %d", gap_count)

    # ── Step 6: 调用 code_by_lines ──
    vulcode = target_method.code_by_lines(target_slice_rel_lines)
    vulcode_with_placeholder = target_method.code_by_lines(
        target_slice_rel_lines, placeholder=config.PLACE_HOLDER, keep_lines=target_keep_lines,
        pre_diff_lines=target_pre_diff_lines
    )

    logging.debug("[target_method_slice] vulcode (%d lines):\n%s", len(vulcode.splitlines()), vulcode)
    logging.debug("[target_method_slice] vulcode_with_placeholder (%d lines):\n%s",
                  len(vulcode_with_placeholder.splitlines()), vulcode_with_placeholder)

    file_suffix = target_method.file_suffix
    utils.write2file(os.path.join(method_dir, f"3.target@s{file_suffix}"), vulcode)
    utils.write2file(os.path.join(method_dir, f"3.target@sp{file_suffix}"), vulcode_with_placeholder)
    return target_slice_rel_lines, vulcode, vulcode_with_placeholder


def transplant_hunks(target_method: Method, target_slice_lines: set[int]) -> str:
    """
    迁移 post 方法的 hunk 到 target 方法
    """
    method_dir = target_method.method_dir
    assert method_dir is not None
    file_suffix = target_method.file_suffix

    with open(f"{method_dir}/2.post@sp{file_suffix}", "r") as f:
        post_sp = f.read()
        f.seek(0)
        post_sp_lines = f.readlines()
    with open(f"{method_dir}/3.target@sp{file_suffix}", "r") as f:
        target_sp = f.read()
        f.seek(0)
        target_sp_lines = f.readlines()
    post_target_line_map, post_target_hunk_map, diff_add_lines, diff_del_lines = hunkmap.code_map(post_sp, target_sp)
    target_post_line_map = {v: k for k, v in post_target_line_map.items()}
    for add_line in sorted(diff_add_lines, reverse=True):
        if target_sp_lines[add_line - 1].strip() == config.PLACE_HOLDER.strip():
            # add_line is a line in target_sp; skip if it has no corresponding post_sp line
            if add_line - 1 not in target_post_line_map:
                continue
            post_sp_lines.insert(target_post_line_map[add_line - 1], config.PLACE_HOLDER + "\n")

    post_target_line_map, post_target_hunk_map, _, _ = hunkmap.code_map("".join(post_sp_lines), target_sp)
    target_post_line_map = {v: k for k, v in post_target_line_map.items()}
    for post_hunk, target_hunk in post_target_hunk_map.items():
        post_hunk_start, post_hunk_end = post_hunk
        target_hunk_start, target_hunk_end = target_hunk
        if target_hunk_end - target_hunk_start == 0:
            if target_sp_lines[target_hunk_end - 1].strip() == config.PLACE_HOLDER.strip():
                post_sp_lines.insert(post_hunk_start - 1, config.PLACE_HOLDER + "\n")

    # 获取 target 方法被切掉的 hunk
    target_reduced_hunks = target_method.reduced_hunks(target_slice_lines)

    # 获取 post 方法的 PLACE_HOLDER 位置
    post_sp_placeholder_index = [i for i, line in enumerate(
        post_sp_lines) if line.strip() == config.PLACE_HOLDER.strip()]

    # post 方法被切掉的 hunk 数量应该等于 target 方法被切掉的 hunk 数量
    if len(post_sp_placeholder_index) != len(target_reduced_hunks):
        return ""

    # 用 target 方法被切掉的 hunk 替换到 post 方法的 PLACE_HOLDER
    ours_ag = post_sp_lines.copy()
    for i, hunk in enumerate(target_reduced_hunks):
        ours_ag[post_sp_placeholder_index[i]] = hunk

    ours_ag = "".join(ours_ag)
    utils.write2file(os.path.join(method_dir, f"5.ours@ag{file_suffix}"), ours_ag)
    return ours_ag


def bp(cveid: str, patch: dict[str, str], file_path: str, method_name: str, language: Language, overwrite: bool = False) -> dict[str, str | list[int]]:
    start_time = time.time()
    print_section(f"开始补丁迁移 - {cveid}")
    print(f"CVE ID: {cveid}")
    print(f"文件: {file_path}")
    print(f"方法: {method_name}")
    print(f"语言: {'Java' if language == Language.JAVA else 'C'}")
    
    logging.info(f"PatchBP 开始: {cveid} {file_path} {method_name}")
    origin_before_func_code = patch["origin_before_func_code"]
    origin_after_func_code = patch["origin_after_func_code"]
    target_before_func_code = patch["target_before_func_code"]
    target_after_func_code = patch["target_after_func_code"]
    bptype = "SAME" if format.normalize(origin_before_func_code) == format.normalize(
        target_before_func_code) else "DIFF"
    
    print_step(1, 10, f"初始化完成 (类型: {bptype})", "success")
    
    results: dict[str, str | list[int]] = {
        "cveid": cveid,
        "file_path": file_path,
        "method_name": method_name,
        "bptype": bptype
    }

    file_name = os.path.basename(file_path)
    cache_dir = f"cache/{cveid}/{file_name}#{method_name}"
    file_suffix = ".java" if language == Language.JAVA else ".c"
    os.makedirs(cache_dir, exist_ok=True)
    pre_dir = os.path.join(cache_dir, "pre")
    post_dir = os.path.join(cache_dir, "post")
    target_dir = os.path.join(cache_dir, "target")
    gt_dir = os.path.join(cache_dir, "gt")

    print_step(2, 10, "创建代码文件和目录结构")
    pre_codefile = CodeFile(file_path, origin_before_func_code)
    post_codefile = CodeFile(file_path, origin_after_func_code)
    target_codefile = CodeFile(file_path, target_before_func_code)
    gt_codefile = CodeFile(file_path, target_after_func_code)
    create_code_tree([pre_codefile], pre_dir, overwrite=overwrite)
    create_code_tree([post_codefile], post_dir, overwrite=overwrite)
    create_code_tree([target_codefile], target_dir, overwrite=overwrite)
    create_code_tree([gt_codefile], gt_dir, overwrite=overwrite)
    print_step(2, 10, "构建 patch 相关的目录树完成", "success")
    logging.debug("✅ 构建 patch 相关的目录树完成")

    print_step(3, 10, "导出 Joern 图 (CPG/PDG)")
    utils.export_joern_graph(pre_dir, post_dir, target_dir, need_cdg=False,
                             language=language, multiprocess=False, overwrite=overwrite)
    print_step(3, 10, "Joern 图导出完成", "success")

    print_step(4, 10, "构建项目对象")
    try:
        pre_project = Project("1.pre", [pre_codefile], language)
        post_project = Project("2.post", [post_codefile], language)
        target_project = Project("3.target", [target_codefile], language)
        gt_project = Project("4.gt", [gt_codefile], language)
        print_step(4, 10, "项目对象构建完成", "success")
    except AssertionError:
        print_step(4, 10, "AST 解析错误", "error")
        results["error"] = ErrorCode.AST_ERROR.value
        return results
    triple_projects = (pre_project, post_project, target_project)

    print_step(5, 10, "加载 CPG/PDG 图")
    pre_project.load_joern_graph(f"{pre_dir}/cpg", f"{pre_dir}/pdg")
    post_project.load_joern_graph(f"{post_dir}/cpg", f"{post_dir}/pdg")
    target_project.load_joern_graph(f"{target_dir}/cpg", f"{target_dir}/pdg")
    print_step(5, 10, "图加载完成", "success")
    logging.debug("✅ 加载 pre-patch, post-patch, target, fixed 的 CPG PDG 完成")

    print_step(6, 10, f"定位方法: {method_name}")
    file_name = file_path.split("/")[-1]
    method_signature = f"{file_name}#{method_name}"
    triple_methods = Project.get_triple_methods(triple_projects, method_signature)
    if triple_methods is None:
        print_step(6, 10, "方法未找到", "error")
        results["error"] = ErrorCode.METHOD_NOT_FOUND.value
        return results
    pre_method, post_method, target_method = triple_methods
    gt_method = gt_project.get_method(method_signature)
    assert gt_method is not None
    pre_method.counterpart = post_method
    post_method.counterpart = pre_method
    target_method.counterpart = gt_method
    gt_method.counterpart = target_method
    print_step(6, 10, "方法定位完成", "success")

    if pre_method.pdg is None or post_method.pdg is None or target_method.pdg is None:
        print_step(7, 10, "PDG 未找到", "error")
        results["error"] = ErrorCode.PDG_NOT_FOUND.value
        return results

    print_step(7, 10, "创建方法目录并进行 Hunk 映射")
    # 创建 Method 目录
    method_dir = Method.init_method_dir(triple_methods, cache_dir, gt_method)
    # Hunk 映射
    pre_post_line_map, pre_post_hunk_map, pre_post_add_lines, re_post_del_lines = hunkmap.method_map(
        pre_method, post_method)
    pre_target_line_map, pre_target_hunk_map, pre_target_add_lines, pre_target_del_lines = hunkmap.method_map(
        pre_method, target_method)
    post_target_line_map, post_target_hunk_map, post_target_add_lines, post_target_del_lines = hunkmap.method_map(
        post_method, target_method)
    post_pre_line_map = {v: k for k, v in pre_post_line_map.items()}
    print_step(7, 10, "Hunk 映射完成", "success")
    logging.debug("✅ Hunk 映射完成")

    print_step(8, 10, f"执行程序切片 (级别: {config.SLICE_LEVEL})")
    # Pre-Method 切片, Post-Method 切片
    backward_slice_level = config.SLICE_LEVEL
    forward_slice_level = config.SLICE_LEVEL
    pre_slice_results = pre_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
    post_slice_results = post_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
    if pre_slice_results is None or post_slice_results is None:
        print_step(8, 10, "切片失败", "error")
        results["error"] = ErrorCode.SLICE_FAILED.value
        return results
    rel_pre_lines = pre_slice_results[1]
    rel_post_lines = post_slice_results[1]
    print_step(8, 10, f"切片完成 (Pre: {len(rel_pre_lines)} 行, Post: {len(rel_post_lines)} 行)", "success")
    logging.debug("✅ Pre-Method, Post-Method 切片完成")

    print_step(9, 10, "增强语义 Patch 合成")
    # 增强语义 Patch 合成
    slice_results = sematic_enhance_patch(
        rel_pre_lines, rel_post_lines,
        pre_method, post_method,
        pre_post_line_map, post_pre_line_map,
        pre_target_line_map, method_dir)
    patch_code, pre_sliced_code, post_sliced_code, pre_sliced_lines, post_sliced_lines = slice_results
    print_step(9, 10, "Patch 合成完成", "success")
    logging.debug("✅ 增强语义 Patch 合成完成")
    results["patch"] = patch_code

    # Target-Method 切片
    target_slice_lines, target_sliced_code, target_sliced_code_placeholder = target_method_slice(
        target_method, pre_method, pre_sliced_lines, pre_target_line_map, pre_target_hunk_map,
        post_target_line_map=post_target_line_map, post_target_hunk_map=post_target_hunk_map,
        post_diff_lines=post_method.rel_diff_lines, method_dir=method_dir)
    print_step(9, 10, f"Target 切片完成 ({len(target_slice_lines)} 行)", "success")
    logging.debug("✅ Target-Method 切片完成")
    results["target"] = target_sliced_code_placeholder

    print_step(10, 10, "生成最终修复代码")
    if format.normalize(pre_sliced_code) == format.normalize(target_sliced_code):
        results["slice_type"] = "SAME"
        print(f"    → 切片类型: SAME (Pre 和 Target 切片代码相同)")
        # 如果 pre-sliced 和 target-sliced 代码一致，直接移植 target 方法的 reduced hunk 到 post-sliced 方法
        ours_ag = transplant_hunks(target_method, target_slice_lines)
        if ours_ag == "":
            results["ours_ag"] = "PLACEHOLDER_FAILED"
            print(f"    → 自动生成: PLACEHOLDER_FAILED (占位符匹配失败)")
        elif format.normalize(ours_ag) == format.normalize(gt_method.code):
            results["ours_ag"] = "SUCCESS"
            print(f"    → 自动生成: ✅ SUCCESS (与 GroundTruth 完全匹配)")
        else:
            results["ours_ag"] = "FAILED"
            print(f"    → 自动生成: ❌ FAILED (与 GroundTruth 不匹配)")
    else:
        results["slice_type"] = "DIFF"
        print(f"    → 切片类型: DIFF (Pre 和 Target 切片代码不同)")

    # GroundTruth 切片
    gt_code = gt_method.code
    for hunk in target_method.reduced_hunks(target_slice_lines):
        if hunk in gt_code:
            gt_code = gt_code.replace(hunk, config.PLACE_HOLDER + "\n", 1)
        else:
            print_step(10, 10, "GroundTruth 切片失败", "error")
            logging.error("❌ GroundTruth 切片失败: GroundTruth 存在多余修改")
            results["error"] = ErrorCode.GROUNDTRUTH_SLICE_FAILED.value
            return results
    utils.write2file(os.path.join(method_dir, f"4.gt@sp{file_suffix}"), gt_code)
    # utils.method_diff2html(method_dir, file_suffix)

    elapsed_time = time.time() - start_time
    results["error"] = ErrorCode.SUCCESS.value
    results["groundtruth"] = gt_code
    results["target_slice_lines"] = list(target_slice_lines)
    results["time"] = f"{elapsed_time:.2f}"
    print_step(10, 10, f"补丁迁移完成 (耗时: {elapsed_time:.2f} 秒)", "success")
    
    # LLM 修复（可选步骤）
    print_step(11, 11, "LLM 修复开始")
    logging.debug("🔄 LLM 修复开始")

    # If the target already has the patch applied, skip the LLM entirely.
    post_sp_path = os.path.join(method_dir, f"2.post@sp{file_suffix}")
    if os.path.exists(post_sp_path):
        with open(post_sp_path, "r") as _f:
            post_sp = _f.read()
        # Strip placeholders before comparing — placeholder positions may
        # differ between target and post due to unrelated target changes.
        placeholder_text = config.PLACE_HOLDER.strip()
        _strip = lambda s: "".join(
            [l for l in s.splitlines(keepends=True) if l.strip() != placeholder_text]
        )
        if format.normalize(_strip(target_sliced_code_placeholder)) == format.normalize(_strip(post_sp)):
            logging.info("⚡ 补丁已合入目标,跳过LLM (target@sp == post@sp)")
            utils.write2file(os.path.join(method_dir, f"5.ours@sp{file_suffix}"), target_sliced_code_placeholder)
            utils.write2file(os.path.join(method_dir, f"5.ours{file_suffix}"), target_method.code)
            print_step(11, 11, "补丁已合入目标,跳过LLM修复", "success")
            results["llm_fixed_code"] = target_method.code
            results["llm_fixed_code_placeholder"] = target_sliced_code_placeholder
            results["llm_fix"] = "ALREADY_APPLIED"
            return results

    fixed_code = llm.llm_fix(patch_code, target_sliced_code_placeholder, language)
    if fixed_code is None:
        print_step(11, 11, "LLM 返回 None，跳过修复", "warning")
        results["llm_fix"] = "SKIPPED"
        return results
    utils.write2file(os.path.join(method_dir, f"5.ours@sp{file_suffix}"), fixed_code)
    final_code = target_method.recover_placeholder(fixed_code, target_slice_lines, config.PLACE_HOLDER)
    if final_code is None:
        print_step(11, 11, "恢复占位符失败", "warning")
        logging.debug("❌ 修复失败")
        results["llm_fix"] = "PLACEHOLDER_FAILED"
        return results
    else:
        utils.write2file(os.path.join(method_dir, f"5.ours{file_suffix}"), final_code)
        print_step(11, 11, "LLM 修复完成", "success")
        logging.debug("✅ 修复完成")
        results["llm_fixed_code"] = final_code
        results["llm_fixed_code_placeholder"] = fixed_code
        results["llm_fix"] = "SUCCESS"
    
    return results


def bp_warper(cveid: str, patch: dict[str, str], file_path: str, method_name: str, language: Language, overwrite: bool = False) -> dict[str, str | list[int]]:
    try:
        return bp(cveid, patch, file_path, method_name, language, overwrite)
    except Exception as e:
        logging.error(f"❌ BP 异常: {cveid} {file_path} {method_name}")
        return {
            "cveid": cveid,
            "file_path": file_path,
            "method_name": method_name,
            "error": ErrorCode.EXCEPTION.value
        }


def load_info(cve_json_path: str):
    with open(cve_json_path, "r") as f:
        data = json.load(f)
    info = {}
    for cve in data:
        cveid = cve
        patch = data[cve]["patch"]
        for p in patch.keys():
            file_path = p.split("#")[0]
            method_name = p.split("#")[1]
            info[cveid + "#" + file_path + "#" + method_name] = {
                "origin_before": format.format(patch[p]["origin_before_func_code"], Language.C, True, True),
                "origin_after": format.format(patch[p]["origin_after_func_code"], Language.C, True, True),
                "target_before": format.format(patch[p]["target_before_func_code"], Language.C, True, True),
                "target_after": format.format(patch[p]["target_after_func_code"], Language.C, True, True)
            }
    return info


def generate_finetune_data(infos: dict):
    finetune = {}
    error_states: dict[str, int] = {error.value: 0 for error in ErrorCode}
    for key, val in infos.items():
        if "error" not in val:
            continue
        if val["error"] != ErrorCode.SUCCESS.value:
            error_states[val["error"]] += 1
            continue
        cveid = val["cveid"]
        file_path = val["file_path"]
        method_name = val["method_name"]
        bptype = val["bptype"]
        slice_type = val["slice_type"]
        patch = val["patch"]
        target = val["target"]
        groundtruth = val["groundtruth"]
        finetune[key] = {
            "cveid": cveid,
            "file_path": file_path,
            "method_name": method_name,
            "bptype": bptype,
            "slice_type": slice_type,
            "patch": patch,
            "target": target,
            "groundtruth": groundtruth
        }
    with open(f"finetune#{config.SLICE_LEVEL}.json", "w") as f:
        json.dump(finetune, f, indent=4)
    print(f"Total data: {len(infos)}")
    print(f"Finetune data generated: {len(finetune)}")
    print(f"Error states: {error_states}")


def batch_run_multiprocess(ground_truth_json_dir: str, max_workers: int):
    args_list = []
    info = {}
    load_info_args = []
    for cve_json in os.listdir(ground_truth_json_dir):
        if not cve_json.endswith(".json"):
            continue
        load_info_args.append((os.path.join(ground_truth_json_dir, cve_json),))
    infos = _safe_multiprocess(load_info_args, load_info)
    for i in infos:
        info.update(i)

    for cve_json in os.listdir(ground_truth_json_dir):
        if not cve_json.endswith(".json"):
            continue
        with open(os.path.join(ground_truth_json_dir, cve_json)) as f:
            data = json.load(f)
        for cve in data:
            cveid = cve
            patch = data[cve]["patch"]
            for p in patch.keys():
                file_path = p.split("#")[0]
                method_name = p.split("#")[1]
                args_list.append((cveid, patch[p], file_path, method_name, Language.C, False))
    results = _safe_multiprocess(args_list, bp_warper, max_workers=max_workers)
    for result in results:
        cveid = result["cveid"]
        file_path = result["file_path"]
        method_name = result["method_name"]
        key = cveid + "#" + file_path + "#" + method_name
        if key in info:
            info[key].update(result)
    with open(f"info#{config.SLICE_LEVEL}.json", "w") as f:
        json.dump(info, f, indent=4, sort_keys=True)
    generate_finetune_data(info)


def batch_run(ground_truth_json_dir: str):
    ground_truth_json_dir = "/home/dellr740/dfs/data/Workspace/cyh/PatchBP/GroundTruth/c/ground_truth_ctags_multi"
    info = {}
    load_info_args = []
    for cve_json in os.listdir(ground_truth_json_dir):
        if not cve_json.endswith(".json"):
            continue
        load_info_args.append((os.path.join(ground_truth_json_dir, cve_json),))
    infos = _safe_multiprocess(load_info_args, load_info)
    for i in infos:
        info.update(i)
    for cve_json in os.listdir(ground_truth_json_dir):
        if not cve_json.endswith(".json"):
            continue
        with open(os.path.join(ground_truth_json_dir, cve_json)) as f:
            data = json.load(f)
        for cve in data:
            cveid = cve
            patch = data[cve]["patch"]
            for p in patch.keys():
                file_path = p.split("#")[0]
                method_name = p.split("#")[1]
                key = cveid + "#" + file_path + "#" + method_name
                result = bp(cveid, patch[p], file_path, method_name, Language.C, overwrite=False)
                if key in info:
                    info[key].update(result)
    with open(f"info#{config.SLICE_LEVEL}.json", "w") as f:
        json.dump(info, f, indent=4, sort_keys=True)
    generate_finetune_data(info)


def single_cve_debug(ground_truth_json_dir: str, cveid: str):
    for cve_json in os.listdir(ground_truth_json_dir):
        if not cve_json.endswith(".json"):
            continue
        if not cve_json.startswith(cveid):
            continue
        with open(os.path.join(ground_truth_json_dir, cve_json)) as f:
            data = json.load(f)
        for cve in data:
            cveid = cve
            patch = data[cve]["patch"]
            for p in patch.keys():
                file_path = p.split("#")[0]
                method_name = p.split("#")[1]
                result = bp(cveid, patch[p], file_path, method_name, Language.C, overwrite=False)
                print(result["cveid"], result["file_path"], result["method_name"],
                      result["error"], result["bptype"])
                if "ours_ag" in result:
                    print("ours_ag", result["ours_ag"])


if __name__ == '__main__':
    joern.set_joern_env(config.JOERN_PATH)
    log.init_logger(logging.getLogger(), logging.INFO, "log")
    # ground_truth_json_dir = "/home/dellr740/dfs/data/Workspace/cyh/PatchBP/GroundTruth/c/ground_truth_ctags_multi"
    # # batch_run_multiprocess(ground_truth_json_dir, max_workers=25)
    # # batch_run(ground_truth_json_dir)
    # single_cve_debug(ground_truth_json_dir, "CVE-2016-4581")
    # 直接读取本仓库的最小示例并调用 bp
    simple_path = "/home/liping/mystique/tests/simple_c.json"
    
    print("\n" + "="*80)
    print("Mystique - 补丁迁移工具".center(80))
    print("="*80 + "\n")
    
    print(f"📂 读取输入文件: {simple_path}")
    with open(simple_path) as f:
        data = json.load(f)
    print(f"✅ 文件读取成功\n")
    
    cveid = "CVE-TEST-0001"
    patch_dict = data[cveid]["patch"]
    
    # 统计信息
    total_patches = len(patch_dict)
    print_section(f"发现 {total_patches} 个需要迁移的函数")
    
    results_summary = []
    success_count = 0
    failed_count = 0
    
    # 遍历所有补丁
    for idx, (key, patch) in enumerate(patch_dict.items(), 1):
        file_path = key.split("#")[0]
        method_name = key.split("#")[1]
        
        print_section(f"[{idx}/{total_patches}] 处理函数: {file_path}#{method_name}")
        
        result = bp(cveid, patch, file_path, method_name, Language.C, overwrite=False)
        results_summary.append((key, result))
        
        # 检查返回值是否为None
        if result is None:
            failed_count += 1
            print(f"❌ 处理失败: 函数返回 None")
            print("\n" + "-"*80 + "\n")
            continue
        
        if result.get("error") == ErrorCode.SUCCESS.value:
            success_count += 1
            print_result_summary(result)
            
            # 打印代码对比
            print_section("代码对比")
            
            if "target" in result:
                print_code_section("目标代码 (Target):", result["target"], max_lines=15)
            
            if "groundtruth" in result:
                print_code_section("预期修复 (GroundTruth):", result["groundtruth"], max_lines=15)
            
            if "patch" in result:
                print_code_section("提取的补丁 (Patch):", result["patch"], max_lines=15)
            
            if "ours_ag" in result and result["ours_ag"] == "SUCCESS":
                print("\n🎉 补丁迁移成功！生成的代码与 GroundTruth 完全匹配！")
            elif "ours_ag" in result:
                print(f"\n⚠️  自动生成状态: {result['ours_ag']}")
            
            # 显示LLM修复结果（如果有）
            if "llm_fix" in result:
                llm_status = result["llm_fix"]
                if llm_status == "SUCCESS":
                    print(f"\n🤖 LLM修复状态: ✅ SUCCESS")
                    if "llm_fixed_code" in result:
                        print_code_section("LLM生成的修复代码:", result["llm_fixed_code"], max_lines=15)
                elif llm_status == "SKIPPED":
                    print(f"\n🤖 LLM修复状态: ⚠️  SKIPPED (LLM返回None)")
                elif llm_status == "PLACEHOLDER_FAILED":
                    print(f"\n🤖 LLM修复状态: ❌ PLACEHOLDER_FAILED (恢复占位符失败)")
        else:
            failed_count += 1
            print(f"❌ 处理失败: {result.get('error', 'Unknown error')}")
        
        print("\n" + "-"*80 + "\n")
    
    # 打印总体统计
    print_section("处理完成 - 总体统计")
    print(f"{'总函数数:':<20} {total_patches}")
    print(f"{'成功:':<20} ✅ {success_count}")
    print(f"{'失败:':<20} ❌ {failed_count}")
    if total_patches > 0:
        success_rate = (success_count / total_patches) * 100
        print(f"{'成功率:':<20} {success_rate:.1f}%")
    
    # 输出文件位置
    print_section("输出文件位置")
    for key, result in results_summary:
        if result is not None and result.get("error") == ErrorCode.SUCCESS.value:
            file_path = key.split("#")[0]
            method_name = key.split("#")[1]
            cache_dir = f"cache/{cveid}/{file_path}#{method_name}"
            print(f"\n{key}:")
            print(f"  → {cache_dir}/")
            print(f"    - 1.pre@s: 原始补丁前的切片代码")
            print(f"    - 2.post@s: 原始补丁后的切片代码")
            print(f"    - 3.target@s: 目标代码切片")
            print(f"    - 4.gt@sp: 预期修复代码（带占位符）")
            print(f"    - patch.diff: 提取的补丁差异")
    
    print("\n" + "="*80)
    print("所有任务执行完成".center(80))
    print("="*80 + "\n")
