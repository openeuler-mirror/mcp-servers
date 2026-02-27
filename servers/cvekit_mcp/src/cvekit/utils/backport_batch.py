from __future__ import annotations

import logging
import os

import git
import yaml
from dataclasses import dataclass

from .backporting import run_backport_from_config
from .locales import i18n
from tabulate import tabulate

logger = logging.getLogger(__name__)

@dataclass
class BackportBatchContext:
    config: dict
    is_report_config: bool
    base_config: dict
    base_project_dir: str
    base_target_path: str
    sorted_items: list
    sort_errors: list


def handle_backport_batch(args):
    """处理批量补丁回移植逻辑（从 cli 入口拆分到 utils 模块）"""
    logger.info("[backport-batch] 开始处理: config=%s", args.backport_config)
    context = _prepare_backport_batch_context(args)
    is_report_config = context.is_report_config
    base_config = context.base_config
    base_project_dir = context.base_project_dir
    base_target_path = context.base_target_path
    sorted_items = context.sorted_items
    sort_errors = context.sort_errors

    default_target_branch = args.branch
    results, report_items = _execute_backport_batch_items(
        sorted_items=sorted_items,
        sort_errors=sort_errors,
        is_report_config=is_report_config,
        base_config=base_config,
        base_project_dir=base_project_dir,
        base_target_path=base_target_path,
        default_target_branch=default_target_branch,
        args=args,
    )

    report = _build_backport_batch_report(
        base_config=base_config,
        base_project_dir=base_project_dir,
        base_target_path=base_target_path,
        default_target_branch=default_target_branch,
        llm_provider=args.llm_provider,
        report_items=report_items,
    )
    _write_backport_batch_report(args.backport_config, is_report_config, report)
    return results


def _load_backport_batch_config(config_path: str):
    logger.info("[backport-batch] 读取配置: path=%s", config_path)
    if not config_path:
        raise ValueError("backport-batch 需要提供 --backport-config")
    if not os.path.exists(config_path):
        raise ValueError(f"配置文件不存在: {config_path}")
    with open(config_path, "r") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("配置文件内容必须是对象/字典结构")
    commit_items = _normalize_backport_batch_commits(config.get("commits", []))
    if not isinstance(commit_items, list) or not commit_items:
        raise ValueError("配置文件必须包含非空的 commits 列表/字典")
    logger.info(
        "[backport-batch] 配置读取完成: commits=%d, keys=%s",
        len(commit_items),
        list(config.keys()),
    )
    return config, commit_items


def _normalize_backport_batch_commits(commit_items):
    if not isinstance(commit_items, dict):
        return commit_items

    normalized_items = []
    for commit_key, commit_value in commit_items.items():
        if isinstance(commit_value, dict):
            normalized = dict(commit_value)
            normalized.setdefault("commit", commit_key)
        else:
            normalized = {"commit": commit_key, "commit_title": commit_value}
        normalized_items.append(normalized)
    return normalized_items

def _is_report_config(config_path: str, commit_items):
    if isinstance(config_path, str) and config_path.endswith(".report.yml"):
        return True
    if not isinstance(commit_items, list):
        return False
    for item in commit_items:
        if not isinstance(item, dict):
            continue
        if "has_conflict" in item or "conflict_check_method" in item or "merged_in_target" in item:
            return True
    return False

def _extract_commit_item(item):
    commit_id = None
    commit_title = None
    item_config = {}
    if isinstance(item, str):
        commit_id = item
    elif isinstance(item, (list, tuple)) and len(item) >= 2:
        commit_id = item[0]
        commit_title = item[1]
    elif isinstance(item, dict):
        commit_id = (
            item.get("commit")
            or item.get("commit_id")
            or item.get("sha")
            or item.get("new_patch")
        )
        commit_title = item.get("commit_title") or item.get("title") or item.get("subject")
        item_config = item
    return commit_id, commit_title, item_config


def _normalize_commit_title(commit_title: str) -> str:
    return commit_title.strip() if isinstance(commit_title, str) else ""


def _parse_merged_in_target_value(value: str):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    if text in {"none", "null", "na", "n/a", "-"}:
        return None
    return "invalid"


def _interactive_adjust_merged_in_target(config_path: str, config: dict, commit_items: list):
    if not isinstance(commit_items, list) or not commit_items:
        return
    print("")
    print("进入交互模式：可修改 merged_in_target（true/false/none）。")
    print("输入格式：<索引> <值>，例如：0 true")
    print("输入 q 退出，输入 l 重新列表。")
    while True:
        rows = []
        for idx, item in enumerate(commit_items):
            if not isinstance(item, dict):
                item = {"commit": item}
                commit_items[idx] = item
            rows.append([
                idx,
                item.get("commit") or item.get("input_commit") or "",
                (item.get("commit_title") or "")[:60],
                item.get("target_branch") or item.get("target_release") or "",
                item.get("merged_in_target"),
            ])
        print("")
        print(tabulate(rows, headers=["idx", "commit", "title", "target", "merged_in_target"], tablefmt="github"))
        cmd = input("merged_in_target> ").strip()
        if not cmd or cmd.lower() in {"l", "list", "ls"}:
            continue
        if cmd.lower() in {"q", "quit", "exit"}:
            break
        parts = cmd.split(None, 1)
        if len(parts) != 2:
            print("输入格式错误：请使用 <索引> <值>（true/false/none）")
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            print("索引必须是数字")
            continue
        if idx < 0 or idx >= len(commit_items):
            print("索引超出范围")
            continue
        merged_value = _parse_merged_in_target_value(parts[1])
        if merged_value == "invalid":
            print("值无效：可用 true/false/none")
            continue
        item = commit_items[idx]
        if not isinstance(item, dict):
            item = {"commit": item}
            commit_items[idx] = item
        item["merged_in_target"] = merged_value
        item["merged_check_error"] = None
        print(f"已更新 idx={idx} merged_in_target={merged_value}")

def _looks_like_commit_sha(value: str) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip().lower()
    if len(candidate) < 7 or len(candidate) > 40:
        return False
    return all(ch in "0123456789abcdef" for ch in candidate)


def _build_commit_subject_index(repo: git.Repo):
    try:
        log_output = repo.git.log("--all", "--format=%H%x00%s")
    except Exception as e:
        return None, f"读取提交日志失败: {e}"
    index = []
    for line in log_output.splitlines():
        if "\x00" not in line:
            continue
        sha, subject = line.split("\x00", 1)
        subject_stripped = subject.strip()
        index.append((sha, subject_stripped, subject_stripped.lower()))
    return index, None


def _filter_candidates_by_ref(repo: git.Repo, candidates, preferred_ref: str):
    if not preferred_ref:
        return candidates
    filtered = []
    for sha in candidates:
        try:
            repo.git.merge_base("--is-ancestor", sha, preferred_ref)
            filtered.append(sha)
        except git.exc.GitCommandError:
            continue
    return filtered or candidates


def _prefer_non_merge(repo: git.Repo, candidates):
    non_merge = []
    for sha in candidates:
        try:
            commit_obj = repo.commit(sha)
            if len(commit_obj.parents) <= 1:
                non_merge.append(sha)
        except Exception:
            continue
    return non_merge or candidates


def _resolve_commit_id_by_title(
    repo: git.Repo,
    commit_title: str,
    commit_index=None,
    preferred_ref: str = "",
):
    normalized_title = _normalize_commit_title(commit_title)
    if not normalized_title:
        return None, "commit title 为空，无法解析"
    if commit_index is None:
        commit_index, index_error = _build_commit_subject_index(repo)
        if index_error:
            return None, index_error
    matches = [sha for sha, subject, _ in commit_index if subject == normalized_title]
    if not matches:
        normalized_lower = normalized_title.lower()
        matches = [sha for sha, _, subject_lower in commit_index if subject_lower == normalized_lower]
    if not matches:
        normalized_lower = normalized_title.lower()
        contains_matches = [
            (sha, subject)
            for sha, subject, subject_lower in commit_index
            if normalized_lower and normalized_lower in subject_lower
        ]
        if not contains_matches:
            return None, f"无法根据 commit title 找到提交(包含匹配未命中): {normalized_title}"
        if len(contains_matches) > 1:
            hint = [f"{sha}:{subject}" for sha, subject in contains_matches[:5]]
            return None, f"commit title 包含匹配到多个候选: {normalized_title}, candidates={hint}"
        return contains_matches[0][0], None
    if len(matches) > 1:
        matches = _filter_candidates_by_ref(repo, matches, preferred_ref)
        matches = _prefer_non_merge(repo, matches)
        if len(matches) > 1:
            hint = []
            for sha in matches[:5]:
                try:
                    subject = repo.commit(sha).summary.strip()
                except Exception:
                    subject = ""
                hint.append(f"{sha}:{subject}")
            return None, f"commit title 匹配到多个提交: {normalized_title}, candidates={hint}"
    return matches[0], None

def _try_get_commit(repo: git.Repo, commit_id: str):
    if not commit_id:
        return None, None
    try:
        return repo.commit(commit_id), None
    except Exception as e:
        return None, str(e)

def _sort_commit_items_by_time(commit_items, project_dir, preferred_ref: str = ""):
    if not project_dir or not os.path.isdir(project_dir):
        raise ValueError("backport-batch 需要提供有效的 project_dir 以按时间排序")
    repo = git.Repo(project_dir)
    commit_index, index_error = _build_commit_subject_index(repo)
    if index_error:
        raise ValueError(index_error)

    sortable = []
    errors = []
    for idx, item in enumerate(commit_items):
        commit_id, commit_title, item_config = _extract_commit_item(item)
        normalized_title = _normalize_commit_title(commit_title)
        input_commit = commit_id
        logger.info(
            "[backport-batch] 解析提交项: index=%d, commit_id=%s, commit_title=%s",
            idx,
            commit_id,
            normalized_title,
        )
        if commit_id and not normalized_title and not _looks_like_commit_sha(commit_id):
            normalized_title = _normalize_commit_title(commit_id)
            if normalized_title:
                commit_id = None
        if not commit_id and not normalized_title:
            errors.append((idx, item, "commits 列表中的元素必须是字符串、二元组或包含 commit/commit_id/commit_title"))
            continue
        try:
            commit_obj, commit_error = _try_get_commit(repo, commit_id)
            if commit_obj:
                actual_title = commit_obj.summary.strip()
                if normalized_title and actual_title != normalized_title:
                    logger.info(
                        "[backport-batch] commit 与 title 不匹配，使用 commit 实际标题: index=%d, commit=%s, input_title=%s, actual_title=%s",
                        idx,
                        commit_id,
                        normalized_title,
                        actual_title,
                    )
                normalized_title = actual_title
            elif not commit_obj and normalized_title:
                resolved_sha, resolve_error = _resolve_commit_id_by_title(
                    repo, normalized_title, commit_index, preferred_ref
                )
                if resolved_sha:
                    logger.info(
                        "[backport-batch] commit 无法解析，已由 title 修正: index=%d, new_commit=%s",
                        idx,
                        resolved_sha,
                    )
                    commit_id = resolved_sha
                    commit_obj = repo.commit(commit_id)
                else:
                    errors.append((idx, item, f"无法根据 commit title 找到提交: {resolve_error}"))
                    continue
            elif not commit_obj and commit_id:
                errors.append((idx, item, f"无法在源代码仓中解析 commit: {commit_id}, error={commit_error}"))
                continue

            if commit_obj and not normalized_title:
                normalized_title = commit_obj.summary.strip()

            commit_time = commit_obj.committed_datetime
            logger.info(
                "[backport-batch] 提交解析成功: index=%d, commit=%s, time=%s",
                idx,
                commit_id,
                commit_time.isoformat(),
            )
            sortable.append((commit_time, idx, commit_id, input_commit, normalized_title, item_config))
        except Exception as e:
            errors.append((idx, item, f"无法在源代码仓中解析 commit: {commit_id}, error={e}"))

    sortable.sort(key=lambda x: (x[0], x[1]))
    sorted_items = []
    for commit_time, _, commit_id, input_commit, commit_title, item_config in sortable:
        sorted_items.append({
            "commit": commit_id,
            "input_commit": input_commit,
            "commit_title": commit_title,
            "item_config": item_config,
            "committed_datetime": commit_time.isoformat()
        })
    return sorted_items, errors

def _write_commit_patch_file(commit_id: str, project_dir: str):
    repo = git.Repo(project_dir)
    full_sha = repo.git.rev_parse(commit_id)
    clone_dir = os.path.dirname(project_dir.rstrip("/"))
    patch_path = os.path.join(clone_dir, f"commit_patch_{full_sha}.patch")
    try:
        commit_obj = repo.commit(full_sha)
        if len(commit_obj.parents) > 1:
            parent_sha = commit_obj.parents[0].hexsha
            patch_content = repo.git.diff(parent_sha, full_sha, "--patch", "--no-color")
        else:
            patch_content = repo.git.show(full_sha, "--patch", "--no-color")
        if patch_content and not patch_content.endswith("\n"):
            # Ensure the patch ends with a newline to avoid "corrupt patch" errors.
            patch_content += "\n"
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(patch_content)
    except Exception as e:
        raise ValueError(f"生成原始补丁文件失败: {e}")
    return full_sha, patch_path

def _ensure_clean_and_checkout(repo: git.Repo, branch_name: str):
    if repo.is_dirty(untracked_files=True):
        repo.git.reset("--hard")
        repo.git.clean("-fdx")
    try:
        current_branch = repo.active_branch.name if not repo.head.is_detached else None
        if current_branch != branch_name:
            repo.git.checkout(branch_name)
    except Exception as e:
        try:
            if "origin" in [r.name for r in repo.remotes]:
                repo.remotes.origin.fetch()
                origin_ref = f"origin/{branch_name}"
                if origin_ref in [r.name for r in repo.remotes.origin.refs]:
                    repo.git.checkout("-b", branch_name, origin_ref)
                    return
        except Exception as fetch_error:
            raise ValueError(f"同步远程分支失败: {fetch_error}")
        raise ValueError(f"切换目标分支失败: {e}")

def _abort_cherry_pick(repo: git.Repo) -> None:
    try:
        repo.git.cherry_pick("--abort")
    except Exception:
        pass


def _reset_hard_and_clean(repo: git.Repo, head_sha: str | None = None) -> None:
    try:
        if head_sha:
            repo.git.reset("--hard", head_sha)
        else:
            repo.git.reset("--hard")
        repo.git.clean("-fdx")
    except Exception:
        pass


def _is_commit_merged_in_target(target_path: str, target_branch: str, commit_sha: str):
    try:
        target_repo = git.Repo(target_path)
        _ensure_clean_and_checkout(target_repo, target_branch)
        target_repo.git.merge_base("--is-ancestor", commit_sha, target_branch)
        return True, None
    except git.exc.GitCommandError as e:
        # 非祖先或分支不存在都会抛错，按未合入处理
        return False, str(e)
    except Exception as e:
        return False, str(e)

def _is_patch_applied_in_target(target_path: str, target_branch: str, patch_path: str):
    if not patch_path or not os.path.exists(patch_path):
        return False, "patch_path missing"
    try:
        target_repo = git.Repo(target_path)
        _ensure_clean_and_checkout(target_repo, target_branch)
        target_repo.git.apply("--check", "--reverse", patch_path)
        return True, None
    except git.exc.GitCommandError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)

def _check_conflict_with_apply_or_cherrypick(
    target_path: str,
    target_branch: str,
    commit_sha: str,
    patch_path: str,
    project_dir: str,
):
    target_repo = git.Repo(target_path)
    _ensure_clean_and_checkout(target_repo, target_branch)
    upstream_repo = git.Repo(project_dir)
    commit_obj = upstream_repo.commit(commit_sha)
    is_merge_commit = len(commit_obj.parents) > 1
    apply_error = None
    if not is_merge_commit:
        # 优先用 git apply --check（merge commit 不适用）
        try:
            target_repo.git.apply("--check", patch_path)
            return False, "apply", None
        except git.exc.GitCommandError as e:
            apply_error = str(e)

    # 再尝试 cherry-pick
    original_head = target_repo.head.commit.hexsha
    try:
        if os.path.abspath(target_repo.working_dir.rstrip("/")) != os.path.abspath(project_dir.rstrip("/")):
            upstream_url = os.path.abspath(project_dir.rstrip("/"))
            remote_name = "upstream"
            if remote_name not in [r.name for r in target_repo.remotes]:
                target_repo.create_remote(remote_name, upstream_url)
            target_repo.remotes[remote_name].fetch()

        if is_merge_commit:
            target_repo.git.cherry_pick("-m", "1", commit_sha)
        else:
            target_repo.git.cherry_pick(commit_sha)
        _reset_hard_and_clean(target_repo, original_head)
        return False, "cherry-pick", None
    except git.exc.GitCommandError as e:
        _abort_cherry_pick(target_repo)
        _reset_hard_and_clean(target_repo, original_head)
        if apply_error:
            return True, "cherry-pick", f"{apply_error}; cherry-pick error: {e}"
        return True, "cherry-pick", f"cherry-pick error: {e}"
    except Exception as e:
        _abort_cherry_pick(target_repo)
        _reset_hard_and_clean(target_repo, original_head)
        if apply_error:
            return True, "cherry-pick", f"{apply_error}; cherry-pick error: {e}"
        return True, "cherry-pick", f"cherry-pick error: {e}"

def _apply_patch_to_target_repo(
    target_path: str,
    target_branch: str,
    commit_sha: str,
    project_dir: str,
):
    target_repo = git.Repo(target_path)
    _ensure_clean_and_checkout(target_repo, target_branch)
    original_head = target_repo.head.commit.hexsha
    try:
        upstream_repo = git.Repo(project_dir)
        commit_obj = upstream_repo.commit(commit_sha)
        is_merge_commit = len(commit_obj.parents) > 1
        if os.path.abspath(target_repo.working_dir.rstrip("/")) != os.path.abspath(project_dir.rstrip("/")):
            upstream_url = os.path.abspath(project_dir.rstrip("/"))
            remote_name = "upstream"
            if remote_name not in [r.name for r in target_repo.remotes]:
                target_repo.create_remote(remote_name, upstream_url)
            target_repo.remotes[remote_name].fetch()
        if is_merge_commit:
            target_repo.git.cherry_pick("-m", "1", commit_sha)
        else:
            target_repo.git.cherry_pick(commit_sha)
        return {"status": "success"}
    except Exception as e:
        _abort_cherry_pick(target_repo)
        _reset_hard_and_clean(target_repo, original_head)
        return {"status": "failed", "error": str(e)}

def _resolve_sorted_backport_items(commit_items, is_report_config, base_project_dir, base_config):
    if is_report_config:
        logger.info("[backport-batch] report 配置跳过排序: items=%d", len(commit_items))
        return commit_items, []

    try:
        logger.info("[backport-batch] 开始按时间排序: project_dir=%s", base_project_dir)
        preferred_ref = base_config.get("source_branch") or base_config.get("source_ref") or ""
        if preferred_ref:
            logger.info("[backport-batch] 使用源仓优先分支: %s", preferred_ref)
        sorted_items, sort_errors = _sort_commit_items_by_time(
            commit_items, base_project_dir, preferred_ref
        )
        logger.info(
            "[backport-batch] 排序完成: ok=%d, errors=%d",
            len(sorted_items),
            len(sort_errors),
        )
        return sorted_items, sort_errors
    except ValueError as e:
        raise ValueError(f"{e}（请先克隆源代码仓到 project_dir）")


def _append_sort_error_report_item(report_items, item, error_message):
    commit_id, commit_title, item_config = _extract_commit_item(item)
    tag = item_config.get("tag") or commit_id or commit_title or ""
    logger.info("[backport-batch] 排序错误: tag=%s, error=%s", tag, error_message)
    report_items.append({
        "commit": None,
        "input_commit": commit_id,
        "commit_title": commit_title,
        "committed_datetime": None,
        "target_branch": item_config.get("target_branch") or item_config.get("target_release"),
        "status": "failed",
        "has_conflict": None,
        "conflict_check_method": None,
        "conflict_check_error": error_message,
        "original_patch_path": None,
        "backported_patch_path": None,
        "patch_path": None,
        "error": error_message,
    })


def _resolve_target_branch(item_config, base_config, default_target_branch):
    return (
        item_config.get("target_branch")
        or item_config.get("target_release")
        or base_config.get("target_branch")
        or base_config.get("target_release")
        or default_target_branch
    )


def _append_remaining_pending_items(
    report_items,
    remaining_items,
    is_report_config,
    base_config,
    default_target_branch,
):
    for remaining in remaining_items:
        remaining_commit_id = remaining.get("commit")
        remaining_input_commit = remaining.get("input_commit")
        remaining_commit_title = remaining.get("commit_title")
        remaining_item_config = (
            remaining if is_report_config else remaining.get("item_config", {})
        )
        remaining_committed_datetime = remaining.get("committed_datetime")
        remaining_target_branch = _resolve_target_branch(
            remaining_item_config, base_config, default_target_branch
        )
        remaining_original_patch_path = (
            remaining_item_config.get("original_patch_path")
            or remaining_item_config.get("patch_path")
            or ""
        )
        report_items.append({
            "commit": remaining_commit_id,
            "input_commit": remaining_input_commit,
            "commit_title": remaining_commit_title,
            "committed_datetime": remaining_committed_datetime,
            "target_branch": remaining_target_branch,
            "status": "pending",
            "merged_in_target": None,
            "merged_check_error": None,
            "is_merge_commit": remaining_item_config.get("is_merge_commit"),
            "has_conflict": None,
            "conflict_check_method": None,
            "conflict_check_error": None,
            "original_patch_path": remaining_original_patch_path,
            "backported_patch_path": None,
            "patch_path": remaining_original_patch_path,
            "error": "未处理",
        })


def _build_batch_summary_result(
    tag,
    commit_id,
    target_branch,
    fixed_commit,
    merged_in_target,
    merged_check_error,
    has_conflict,
    conflict_check_method,
    conflict_check_error,
    backport_result,
):
    result = {
        i18n("补丁ID"): tag or commit_id,
        i18n("目标分支"): target_branch,
        i18n("适配状态"): i18n("成功") if backport_result.get("status") == "success" else i18n("需要调整"),
        i18n("冲突点"): backport_result.get("backported_patch_path", backport_result.get("original_patch_path", "")),
        i18n("建议调整文件"): "N/A" if backport_result.get("status") == "success" else "",
    }
    result["details"] = {
        "action": "backport-batch",
        "tag": tag or commit_id,
        "target_branch": target_branch,
        "fixed_commit": fixed_commit,
        "merged_in_target": merged_in_target,
        "merged_check_error": merged_check_error,
        "conflict_check": {
            "has_conflict": has_conflict,
            "method": conflict_check_method,
            "error": conflict_check_error,
        },
        "original_patch_path": backport_result.get("original_patch_path"),
        "backported_patch_path": backport_result.get("backported_patch_path"),
        "diff_path": backport_result.get("diff_path"),
        "logfile": backport_result.get("logfile"),
        "time_cost": backport_result.get("time_cost"),
        "status": backport_result.get("status"),
    }
    if "cost" in backport_result:
        result["details"]["cost"] = backport_result["cost"]
    if "tokens" in backport_result:
        result["details"]["tokens"] = backport_result["tokens"]
    if "error" in backport_result:
        result["details"]["error"] = backport_result["error"]
    return result


def _extract_backport_batch_item_fields(item, is_report_config):
    commit_id = item.get("commit")
    input_commit = item.get("input_commit")
    commit_title = item.get("commit_title")
    item_config = item if is_report_config else item.get("item_config", {})
    committed_datetime = item.get("committed_datetime")
    is_merge_commit = item_config.get("is_merge_commit")
    tag = item_config.get("tag") or commit_id or input_commit or commit_title
    return {
        "commit_id": commit_id,
        "input_commit": input_commit,
        "commit_title": commit_title,
        "item_config": item_config,
        "committed_datetime": committed_datetime,
        "is_merge_commit": is_merge_commit,
        "tag": tag,
    }


def _resolve_is_merge_commit(base_project_dir, fixed_commit):
    try:
        upstream_repo = git.Repo(base_project_dir)
        commit_obj = upstream_repo.commit(fixed_commit)
        return len(commit_obj.parents) > 1
    except Exception:
        return None


def _prepare_backport_patch_and_commit(
    *,
    is_report_config,
    fixed_commit,
    patch_path,
    is_merge_commit,
    base_project_dir,
):
    if not is_report_config:
        try:
            logger.info("[backport-batch] 生成补丁: commit=%s", fixed_commit)
            full_sha, patch_path = _write_commit_patch_file(fixed_commit, base_project_dir)
            fixed_commit = full_sha
            if is_merge_commit is None:
                is_merge_commit = _resolve_is_merge_commit(base_project_dir, fixed_commit)
            logger.info("[backport-batch] 补丁生成成功: commit=%s, patch=%s", fixed_commit, patch_path)
            return fixed_commit, patch_path, is_merge_commit, False
        except Exception as e:
            logger.info("[backport-batch] 补丁生成失败: commit=%s, error=%s", fixed_commit, e)
            return fixed_commit, patch_path, is_merge_commit, True
    if is_merge_commit is None and fixed_commit:
        is_merge_commit = _resolve_is_merge_commit(base_project_dir, fixed_commit)
    return fixed_commit, patch_path, is_merge_commit, False


def _resolve_merge_and_conflict_status(
    *,
    is_report_config,
    base_target_path,
    target_branch,
    fixed_commit,
    patch_path,
    base_project_dir,
    tag,
    commit_id,
    merged_in_target,
    merged_check_error,
    has_conflict,
    conflict_check_method,
    conflict_check_error,
):
    if not fixed_commit:
        return (
            merged_in_target,
            merged_check_error,
            has_conflict,
            conflict_check_method,
            conflict_check_error,
        )

    use_config_merged = is_report_config and merged_in_target is not None
    if use_config_merged:
        logger.info(
            "[backport-batch] 使用 report 配置中的 merged_in_target: tag=%s, merged_in_target=%s",
            tag or commit_id,
            merged_in_target,
        )
        if merged_in_target:
            has_conflict, conflict_check_method, conflict_check_error = False, "merged", None
        return (
            merged_in_target,
            merged_check_error,
            has_conflict,
            conflict_check_method,
            conflict_check_error,
        )

    merged_in_target, merged_check_error = _is_commit_merged_in_target(
        base_target_path, target_branch, fixed_commit
    )
    if merged_in_target:
        logger.info(
            "[backport-batch] 目标分支已包含该提交，跳过冲突检测: tag=%s, commit=%s, branch=%s",
            tag or commit_id,
            fixed_commit,
            target_branch,
        )
        has_conflict, conflict_check_method, conflict_check_error = False, "merged", None
    else:
        patch_applied = False
        patch_check_error = None
        if patch_path:
            patch_applied, patch_check_error = _is_patch_applied_in_target(
                base_target_path, target_branch, patch_path
            )
        if patch_applied:
            merged_in_target = True
            merged_check_error = None
            has_conflict, conflict_check_method, conflict_check_error = False, "patch-reverse", None
            logger.info(
                "[backport-batch] 目标分支已包含该补丁内容，跳过冲突检测: tag=%s, commit=%s, branch=%s",
                tag or commit_id,
                fixed_commit,
                target_branch,
            )
        else:
            if patch_check_error:
                if merged_check_error:
                    merged_check_error = f"{merged_check_error}; patch-reverse-check: {patch_check_error}"
                else:
                    merged_check_error = f"patch-reverse-check: {patch_check_error}"
            logger.info(
                "[backport-batch] 目标分支合入检查未命中: tag=%s, commit=%s, branch=%s, error=%s",
                tag or commit_id,
                fixed_commit,
                target_branch,
                merged_check_error,
            )

    if not is_report_config:
        has_conflict, conflict_check_method, conflict_check_error = _check_conflict_with_apply_or_cherrypick(
            base_target_path,
            target_branch,
            fixed_commit,
            patch_path,
            base_project_dir,
        )
        logger.info(
            "[backport-batch] 冲突检测: tag=%s, has_conflict=%s, method=%s, error=%s",
            tag or commit_id,
            has_conflict,
            conflict_check_method,
            conflict_check_error,
        )

    return (
        merged_in_target,
        merged_check_error,
        has_conflict,
        conflict_check_method,
        conflict_check_error,
    )


def _build_backport_runtime_config(
    *,
    item_config,
    base_config,
    base_project_dir,
    base_target_path,
    fixed_commit,
    target_branch,
    tag,
    commit_id,
    args,
):
    base_dataset_dir = (
        item_config.get("patch_dataset_dir")
        or base_config.get("patch_dataset_dir")
        or args.patch_dataset_dir
        or os.path.join(os.path.expanduser("~"), "backports/patch_dataset")
    )
    dataset_dir = os.path.join(base_dataset_dir, str(tag or commit_id))
    logger.info("[backport-batch] 数据集目录: %s", dataset_dir)

    config_dict = {
        "project": base_config.get("project", "linux"),
        "project_url": base_config.get("project_url", ""),
        "project_dir": base_project_dir,
        "target_path": base_target_path,
        "new_patch": fixed_commit,
        "target_release": target_branch,
        "openai_key": (
            item_config.get("openai_key")
            or item_config.get("api_key")
            or base_config.get("openai_key")
            or base_config.get("api_key")
            or args.api_key
        ),
        "llm_provider": item_config.get("llm_provider") or base_config.get("llm_provider") or args.llm_provider,
        "tag": tag or commit_id,
        "patch_dataset_dir": dataset_dir,
        "skip_cherry_pick": True,
    }
    if item_config.get("error_message") or base_config.get("error_message") or args.error_message:
        config_dict["error_message"] = (
            item_config.get("error_message") or base_config.get("error_message") or args.error_message
        )
    if item_config.get("sanitizer") or base_config.get("sanitizer") or args.sanitizer:
        config_dict["sanitizer"] = item_config.get("sanitizer") or base_config.get("sanitizer") or args.sanitizer
    return config_dict


def _execute_backport_batch_action(
    *,
    is_report_config,
    merged_in_target,
    has_conflict,
    item_config,
    tag,
    commit_id,
    target_branch,
    fixed_commit,
    patch_path,
    config_dict,
    base_target_path,
    base_project_dir,
    args,
):
    did_backport = False
    if is_report_config:
        if merged_in_target:
            logger.info(
                "[backport-batch] 目标分支已包含该提交，跳过应用补丁: tag=%s, branch=%s",
                tag or commit_id,
                target_branch,
            )
            return {
                "status": "skipped",
                "original_patch_path": item_config.get("original_patch_path", ""),
                "backported_patch_path": item_config.get("backported_patch_path", ""),
                "diff_path": item_config.get("diff_path", ""),
                "logfile": item_config.get("logfile", ""),
                "time_cost": 0,
                "error": "目标分支已包含该提交",
            }, did_backport

        if has_conflict:
            logger.info(
                "[backport-batch] 冲突存在，执行回移植：tag=%s, commit=%s, target_branch=%s",
                tag or commit_id,
                fixed_commit,
                target_branch,
            )
            logger.info("[backport-batch] 回移植配置: %s", config_dict)
            did_backport = True
            return run_backport_from_config(config_dict, debug_mode=args.debug), did_backport

        logger.info(
            "[backport-batch] 无冲突，直接应用补丁: tag=%s, commit=%s, target_branch=%s",
            tag or commit_id,
            fixed_commit,
            target_branch,
        )
        logger.info("[backport-batch] 应用补丁路径: %s", patch_path)
        if not patch_path:
            return {
                "status": "failed",
                "original_patch_path": item_config.get("original_patch_path", ""),
                "backported_patch_path": item_config.get("backported_patch_path", ""),
                "diff_path": item_config.get("diff_path", ""),
                "logfile": item_config.get("logfile", ""),
                "time_cost": 0,
                "error": "缺少 patch_path，无法应用补丁",
            }, did_backport
        apply_result = _apply_patch_to_target_repo(
            base_target_path,
            target_branch,
            fixed_commit,
            base_project_dir,
        )
        result = {
            "status": apply_result.get("status"),
            "original_patch_path": item_config.get("original_patch_path", "") or patch_path,
            "backported_patch_path": item_config.get("backported_patch_path", ""),
            "diff_path": item_config.get("diff_path", ""),
            "logfile": item_config.get("logfile", ""),
            "time_cost": 0,
        }
        if apply_result.get("error"):
            result["error"] = apply_result["error"]
        return result, did_backport

    logger.info(
        "[backport-batch] 原始配置仅记录结果，不应用补丁: tag=%s, branch=%s",
        tag or commit_id,
        target_branch,
    )
    return {
        "status": "success",
        "original_patch_path": item_config.get("original_patch_path", "") or patch_path,
        "backported_patch_path": "",
        "diff_path": "",
        "logfile": "",
        "time_cost": 0,
    }, did_backport


def _build_backport_batch_report_item(
    *,
    commit_id,
    input_commit,
    commit_title,
    committed_datetime,
    target_branch,
    backport_result,
    item_config,
    patch_path,
    merged_in_target,
    merged_check_error,
    is_merge_commit,
    has_conflict,
    conflict_check_method,
    conflict_check_error,
):
    resolved_original_patch = (
        backport_result.get("original_patch_path") or item_config.get("original_patch_path") or patch_path
    )
    resolved_backported_patch = backport_result.get("backported_patch_path")
    return {
        "commit": commit_id,
        "input_commit": input_commit,
        "commit_title": commit_title,
        "committed_datetime": committed_datetime,
        "target_branch": target_branch,
        "status": backport_result.get("status"),
        "merged_in_target": merged_in_target,
        "merged_check_error": merged_check_error,
        "is_merge_commit": is_merge_commit,
        "has_conflict": has_conflict,
        "conflict_check_method": conflict_check_method,
        "conflict_check_error": conflict_check_error,
        "original_patch_path": resolved_original_patch,
        "backported_patch_path": resolved_backported_patch,
        "patch_path": resolved_backported_patch if has_conflict else resolved_original_patch,
    }


def _build_backport_batch_failed_result(
    *,
    did_backport,
    tag,
    commit_id,
    target_branch,
    fixed_commit,
    has_conflict,
    conflict_check_method,
    conflict_check_error,
    error,
):
    if not did_backport:
        return None
    return {
        i18n("补丁ID"): tag or commit_id,
        i18n("目标分支"): target_branch,
        i18n("适配状态"): i18n("需要调整"),
        i18n("冲突点"): "",
        i18n("建议调整文件"): "",
        "details": {
            "action": "backport-batch",
            "tag": tag or commit_id,
            "target_branch": target_branch,
            "fixed_commit": fixed_commit,
            "conflict_check": {
                "has_conflict": has_conflict,
                "method": conflict_check_method,
                "error": conflict_check_error,
            },
            "status": "failed",
            "error": str(error),
        },
    }


def _process_backport_batch_item(
    item,
    is_report_config,
    base_config,
    base_project_dir,
    base_target_path,
    default_target_branch,
    args,
):
    fields = _extract_backport_batch_item_fields(item, is_report_config)
    commit_id = fields["commit_id"]
    input_commit = fields["input_commit"]
    commit_title = fields["commit_title"]
    item_config = fields["item_config"]
    committed_datetime = fields["committed_datetime"]
    is_merge_commit = fields["is_merge_commit"]
    tag = fields["tag"]

    logger.info(
        "[backport-batch] 处理条目: tag=%s, commit=%s, input_commit=%s, title=%s, time=%s",
        tag,
        commit_id,
        input_commit,
        commit_title,
        committed_datetime,
    )
    target_branch = _resolve_target_branch(item_config, base_config, default_target_branch)
    if not target_branch:
        logger.info("[backport-batch] 目标分支缺失: tag=%s", tag or commit_id)
        return {"skip": True, "did_backport": False}

    fixed_commit = commit_id
    patch_path = item_config.get("patch_path") or item_config.get("original_patch_path") or ""
    fixed_commit, patch_path, is_merge_commit, should_skip = _prepare_backport_patch_and_commit(
        is_report_config=is_report_config,
        fixed_commit=fixed_commit,
        patch_path=patch_path,
        is_merge_commit=is_merge_commit,
        base_project_dir=base_project_dir,
    )
    if should_skip:
        return {"skip": True, "did_backport": False}

    merged_in_target = item_config.get("merged_in_target")
    merged_check_error = item_config.get("merged_check_error")
    has_conflict = item_config.get("has_conflict")
    conflict_check_method = item_config.get("conflict_check_method")
    conflict_check_error = item_config.get("conflict_check_error")
    (
        merged_in_target,
        merged_check_error,
        has_conflict,
        conflict_check_method,
        conflict_check_error,
    ) = _resolve_merge_and_conflict_status(
        is_report_config=is_report_config,
        base_target_path=base_target_path,
        target_branch=target_branch,
        fixed_commit=fixed_commit,
        patch_path=patch_path,
        base_project_dir=base_project_dir,
        tag=tag,
        commit_id=commit_id,
        merged_in_target=merged_in_target,
        merged_check_error=merged_check_error,
        has_conflict=has_conflict,
        conflict_check_method=conflict_check_method,
        conflict_check_error=conflict_check_error,
    )

    config_dict = _build_backport_runtime_config(
        item_config=item_config,
        base_config=base_config,
        base_project_dir=base_project_dir,
        base_target_path=base_target_path,
        fixed_commit=fixed_commit,
        target_branch=target_branch,
        tag=tag,
        commit_id=commit_id,
        args=args,
    )

    did_backport = False
    try:
        patch_path = item_config.get("patch_path") or item_config.get("original_patch_path") or patch_path
        backport_result, did_backport = _execute_backport_batch_action(
            is_report_config=is_report_config,
            merged_in_target=merged_in_target,
            has_conflict=has_conflict,
            item_config=item_config,
            tag=tag,
            commit_id=commit_id,
            target_branch=target_branch,
            fixed_commit=fixed_commit,
            patch_path=patch_path,
            config_dict=config_dict,
            base_target_path=base_target_path,
            base_project_dir=base_project_dir,
            args=args,
        )

        result = None
        if did_backport:
            result = _build_batch_summary_result(
                tag=tag,
                commit_id=commit_id,
                target_branch=target_branch,
                fixed_commit=fixed_commit,
                merged_in_target=merged_in_target,
                merged_check_error=merged_check_error,
                has_conflict=has_conflict,
                conflict_check_method=conflict_check_method,
                conflict_check_error=conflict_check_error,
                backport_result=backport_result,
            )
        report_item = _build_backport_batch_report_item(
            commit_id=commit_id,
            input_commit=input_commit,
            commit_title=commit_title,
            committed_datetime=committed_datetime,
            target_branch=target_branch,
            backport_result=backport_result,
            item_config=item_config,
            patch_path=patch_path,
            merged_in_target=merged_in_target,
            merged_check_error=merged_check_error,
            is_merge_commit=is_merge_commit,
            has_conflict=has_conflict,
            conflict_check_method=conflict_check_method,
            conflict_check_error=conflict_check_error,
        )
        return {
            "skip": False,
            "result": result,
            "report_item": report_item,
            "did_backport": did_backport,
        }
    except Exception as e:
        result = _build_backport_batch_failed_result(
            did_backport=did_backport,
            tag=tag,
            commit_id=commit_id,
            target_branch=target_branch,
            fixed_commit=fixed_commit,
            has_conflict=has_conflict,
            conflict_check_method=conflict_check_method,
            conflict_check_error=conflict_check_error,
            error=e,
        )
        report_item = {
            "commit": commit_id,
            "input_commit": input_commit,
            "commit_title": commit_title,
            "committed_datetime": committed_datetime,
            "target_branch": target_branch,
            "status": "failed",
            "merged_in_target": merged_in_target,
            "merged_check_error": merged_check_error,
            "is_merge_commit": is_merge_commit,
            "has_conflict": has_conflict,
            "conflict_check_method": conflict_check_method,
            "conflict_check_error": conflict_check_error,
            "original_patch_path": None,
            "backported_patch_path": None,
            "patch_path": None,
            "error": str(e),
        }
        return {
            "skip": False,
            "result": result,
            "report_item": report_item,
            "did_backport": did_backport,
        }


def _build_backport_batch_report(
    base_config,
    base_project_dir,
    base_target_path,
    default_target_branch,
    llm_provider,
    report_items,
):
    return {
        "project": base_config.get("project", "linux"),
        "project_url": base_config.get("project_url", ""),
        "project_dir": base_project_dir,
        "target_path": base_target_path,
        "target_release": (
            base_config.get("target_branch")
            or base_config.get("target_release")
            or default_target_branch
        ),
        "patch_dataset_dir": base_config.get("patch_dataset_dir"),
        "llm_provider": base_config.get("llm_provider") or llm_provider,
        "commits": report_items,
    }


def _write_backport_batch_report(config_path, is_report_config, report):
    report_path = config_path if is_report_config else config_path + ".report.yml"
    with open(report_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(report, f, allow_unicode=True, sort_keys=False)


def _prepare_backport_batch_context(args):
    config, commit_items = _load_backport_batch_config(args.backport_config)
    is_report_config = _is_report_config(args.backport_config, commit_items)
    logger.info("[backport-batch] 配置类型: %s", "report" if is_report_config else "raw")

    if args.interactive:
        if not is_report_config:
            logger.info("[backport-batch] 交互模式仅支持 report 配置，已跳过")
        else:
            _interactive_adjust_merged_in_target(args.backport_config, config, commit_items)

    base_config = {k: v for k, v in config.items() if k != "commits"}
    base_project_dir = base_config.get("project_dir")
    if not base_project_dir:
        raise ValueError("backport-batch 必须提供源代码仓路径 project_dir")
    base_target_path = base_config.get("target_path")
    if not base_target_path:
        raise ValueError("backport-batch 必须提供目标仓路径 target_path")

    sorted_items, sort_errors = _resolve_sorted_backport_items(
        commit_items,
        is_report_config,
        base_project_dir,
        base_config,
    )
    return BackportBatchContext(
        config=config,
        is_report_config=is_report_config,
        base_config=base_config,
        base_project_dir=base_project_dir,
        base_target_path=base_target_path,
        sorted_items=sorted_items,
        sort_errors=sort_errors,
    )


def _execute_backport_batch_items(
    sorted_items,
    sort_errors,
    is_report_config,
    base_config,
    base_project_dir,
    base_target_path,
    default_target_branch,
    args,
):
    results = []
    report_items = []

    for _, item, error_message in sort_errors:
        _append_sort_error_report_item(report_items, item, error_message)

    for idx, item in enumerate(sorted_items):
        processed = _process_backport_batch_item(
            item=item,
            is_report_config=is_report_config,
            base_config=base_config,
            base_project_dir=base_project_dir,
            base_target_path=base_target_path,
            default_target_branch=default_target_branch,
            args=args,
        )
        if processed.get("skip"):
            continue
        if processed.get("result"):
            results.append(processed["result"])
        report_items.append(processed["report_item"])
        if processed.get("did_backport"):
            logger.info("[backport-batch] 已执行回移植，停止后续处理以便检查 report.yml")
            _append_remaining_pending_items(
                report_items=report_items,
                remaining_items=sorted_items[idx + 1 :],
                is_report_config=is_report_config,
                base_config=base_config,
                default_target_branch=default_target_branch,
            )
            break
    return results, report_items
