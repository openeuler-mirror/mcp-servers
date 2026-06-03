from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from typing import Any

import git

logger = logging.getLogger(__name__)

DEFAULT_COMMIT_SORT = "describe"
VALID_COMMIT_SORTS = {"describe", "time"}


def normalize_commit_sort(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return DEFAULT_COMMIT_SORT
    normalized = str(value).strip().lower()
    if normalized not in VALID_COMMIT_SORTS:
        raise ValueError(
            "commit_sort 只支持 describe/commit time，"
            f"当前值: {value}"
        )
    return normalized


def sort_commit_items(
    commit_items,
    project_dir: str,
    upstream_ref: str = "master",
    commit_sort: str | None = None,
    upstream_repo_path: str | None = None,
):
    mode = normalize_commit_sort(commit_sort)
    if mode == "describe":
        return sort_commit_items_by_describe(commit_items, project_dir, upstream_ref, upstream_repo_path)
    return sort_commit_items_by_gitlog(commit_items, project_dir, upstream_ref, upstream_repo_path)


def resolve_commit_sort(config_sort: str | None = None, cli_sort: str | None = None) -> str:
    return normalize_commit_sort(cli_sort or config_sort)


def resolve_sorted_backport_items(
    commit_items,
    is_report_config: bool,
    base_project_dir: str,
    base_config: dict,
    args,
):
    if is_report_config:
        logger.info("[backport-batch] report 配置跳过排序: items=%d", len(commit_items))
        return commit_items, []

    config_sort = base_config.get("commit_sort") if isinstance(base_config, dict) else None
    cli_sort = getattr(args, "commit_sort", None)
    commit_sort = resolve_commit_sort(config_sort, cli_sort)
    logger.info(
        "[backport-batch] 开始排序: mode=%s, project_dir=%s",
        commit_sort,
        base_project_dir,
    )
    logger.info("[backport-batch] describe/gitlog 排序仅使用源仓库 project_dir")
    sorted_items, sort_errors = sort_commit_items(
        commit_items,
        base_project_dir,
        "master",
        commit_sort,
        None,
    )
    logger.info(
        "[backport-batch] 排序完成: mode=%s, ok=%d, errors=%d",
        commit_sort,
        len(sorted_items),
        len(sort_errors),
    )
    return sorted_items, sort_errors


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
    except Exception as exc:
        return None, f"读取提交日志失败: {exc}"
    index = []
    for line in log_output.splitlines():
        if "\x00" not in line:
            continue
        sha, subject = line.split("\x00", 1)
        subject_stripped = subject.strip()
        index.append((sha, subject_stripped, subject_stripped.lower()))
    return index, None


def _resolve_commit_id_by_title(repo: git.Repo, commit_title: str, commit_index=None):
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
        non_merge = []
        for sha in matches:
            try:
                commit_obj = repo.commit(sha)
                if len(commit_obj.parents) <= 1:
                    non_merge.append(sha)
            except Exception:
                continue
        matches = non_merge or matches
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


def _parse_commit_items(
    commit_items,
    project_dir: str,
    upstream_ref: str = "master",
    upstream_repo_path: str | None = None,
):
    if not project_dir or not os.path.isdir(project_dir):
        raise ValueError("backport-batch 需要提供有效的 project_dir 以按 commit 排序")
    repo = git.Repo(project_dir)
    commit_index = None

    parsed_items = []
    errors = []
    for idx, item in enumerate(commit_items):
        commit_id, commit_title, item_config = _extract_commit_item(item)
        normalized_title = _normalize_commit_title(commit_title)
        input_commit = commit_id

        if commit_id and not normalized_title and not _looks_like_commit_sha(commit_id):
            normalized_title = _normalize_commit_title(commit_id)
            if normalized_title:
                commit_id = None

        if not commit_id and not normalized_title:
            errors.append((idx, item, "commits 列表中的元素必须是字符串、二元组或包含 commit/commit_id/commit_title"))
            continue

        try:
            commit_obj = None
            commit_error = None
            if commit_id:
                try:
                    commit_obj = repo.commit(commit_id)
                except Exception as exc:
                    commit_error = str(exc)
            if commit_obj:
                actual_title = commit_obj.summary.strip()
                if normalized_title and actual_title != normalized_title:
                    logger.debug(
                        "[backport-batch] commit 与 title 不匹配: index=%d, commit=%s, input=%s, actual=%s",
                        idx,
                        commit_id,
                        normalized_title,
                        actual_title,
                    )
                normalized_title = actual_title
            elif normalized_title:
                if commit_index is None:
                    commit_index, index_error = _build_commit_subject_index(repo)
                    if index_error:
                        raise ValueError(index_error)
                resolved_sha, resolve_error = _resolve_commit_id_by_title(repo, normalized_title, commit_index)
                if not resolved_sha:
                    errors.append((idx, item, f"无法根据 commit title 找到提交: {resolve_error}"))
                    continue
                commit_obj = repo.commit(resolved_sha)
                commit_id = commit_obj.hexsha
                normalized_title = commit_obj.summary.strip()
            elif commit_id:
                errors.append((idx, item, f"无法解析 commit: {commit_id}, error={commit_error}"))
                continue

            parsed_items.append((
                idx,
                commit_obj.hexsha,
                input_commit,
                normalized_title,
                item_config,
                commit_obj,
            ))
        except Exception as e:
            errors.append((idx, item, f"无法解析 commit: {commit_id}, error={e}"))

    return repo, parsed_items, errors


def _build_sorted_item(item, **extra_fields):
    result = {
        "commit": item[5].hexsha,
        "input_commit": item[2],
        "commit_title": item[3],
        "item_config": item[4],
        "committed_datetime": item[5].committed_datetime.isoformat(),
    }
    result.update(extra_fields)
    return result


def _natural_sort_key(text: str) -> tuple[tuple[int, Any], ...]:
    key = []
    for part in re.split(r"(\d+)", text.lower()):
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def parse_describe_order(describe: str):
    if not describe:
        return None

    desc = describe.strip()
    match = re.match(r"^(.+)-(\d+)-g[0-9a-f]+(?:-.+)?$", desc.lower())
    if match:
        tag = match.group(1)
        distance = int(match.group(2))
        return _natural_sort_key(tag), distance

    if re.fullmatch(r"[0-9a-f]{7,40}", desc.lower()):
        return None

    return _natural_sort_key(desc), 0


def _batch_describe_commits(repo: git.Repo, parsed_items):
    if not parsed_items:
        return {}
    describe_map = {}
    for item in parsed_items:
        sha = item[5].hexsha
        try:
            describe_map[sha] = repo.git.describe("--tags", "--always", sha).strip()
        except Exception as e:
            logger.warning("[backport-batch] git describe 查询失败，回退时间排序: commit=%s, error=%s", sha, e)
    return describe_map


def sort_commit_items_by_describe(
    commit_items,
    project_dir: str,
    upstream_ref: str = "master",
    upstream_repo_path: str | None = None,
):
    repo, parsed_items, errors = _parse_commit_items(commit_items, project_dir, upstream_ref, upstream_repo_path)
    if not parsed_items:
        return [], errors

    describe_map = _batch_describe_commits(repo, parsed_items)

    sortable = []
    for item in parsed_items:
        describe_text = describe_map.get(item[5].hexsha, "")
        parsed_describe = parse_describe_order(describe_text)
        commit_timestamp = int(item[5].committed_date)
        if parsed_describe is not None:
            tag_key, distance = parsed_describe
            sort_key = (0, tag_key, distance, commit_timestamp, item[0])
        else:
            sort_key = (1, (), 0, commit_timestamp, item[0])
        sortable.append((sort_key, item, describe_text, parsed_describe))

    sortable.sort(key=lambda entry: entry[0])
    sorted_items = [
        _build_sorted_item(
            item,
            git_describe=describe_text,
            describe_order=(
                {"tag_key": parsed[0], "distance": parsed[1]}
                if parsed is not None
                else None
            ),
            git_log_position=None,
        )
        for _, item, describe_text, parsed in sortable
    ]
    logger.info("[backport-batch] 已按 git describe 顺序排序: items=%d", len(sorted_items))
    return sorted_items, errors


def sort_commit_items_by_gitlog(
    commit_items,
    project_dir: str,
    upstream_ref: str = "master",
    upstream_repo_path: str | None = None,
):
    """
    根据 commit 在 git log 中的位置进行排序（两阶段优化版本）

    排序策略（按优先级）：
      1. git log 中的拓扑位置（主键）：反映 commit 在分支上的真实先后顺序
      2. committed_datetime（次键）：时间戳不同时的排序依据
      3. 原始输入顺序（三键）：保证排序稳定性
    """
    _, parsed_items, errors = _parse_commit_items(commit_items, project_dir, upstream_ref, upstream_repo_path)
    if not parsed_items:
        return [], errors

    parsed_items.sort(key=lambda x: (x[5].committed_datetime, x[0]))

    time_groups = defaultdict(list)
    for item in parsed_items:
        time_key = int(item[5].committed_date)
        time_groups[time_key].append(item)

    conflict_groups = [group for group in time_groups.values() if len(group) > 1]

    if not conflict_groups:
        logger.info("[backport-batch] 所有提交时间戳不同，直接按时间排序返回")
        sorted_items = [
            _build_sorted_item(item, git_log_position=None)
            for item in parsed_items
        ]
        return sorted_items, errors

    logger.info("[backport-batch] 发现 %d 组时间戳冲突，执行组内拓扑排序", len(conflict_groups))

    repo = git.Repo(project_dir)
    commit_position = {}

    for group in conflict_groups:
        group_shas = [item[5].hexsha for item in group]
        if len(group_shas) < 2:
            continue

        try:
            try:
                merge_base = repo.git.merge_base("--octopus", *group_shas).strip()
            except Exception:
                merge_base = None

            if merge_base:
                rev_list_args = [f"{merge_base}..{group_shas[0]}"] + group_shas[1:]
            else:
                rev_list_args = group_shas

            rev_list = repo.git.rev_list("--topo-order", *rev_list_args).splitlines()

            group_shas_set = set(group_shas)
            for i, sha in enumerate(rev_list):
                if sha in group_shas_set:
                    commit_position[sha] = len(rev_list) - 1 - i

            if merge_base and merge_base in group_shas_set and merge_base not in commit_position:
                commit_position[merge_base] = 0

        except Exception as e:
            logger.warning("[backport-batch] 拓扑排序失败，使用原始顺序兜底: %s", e)

    sortable = [
        (
            int(item[5].committed_date),
            commit_position.get(item[5].hexsha, item[0]),
            item[0],
            item,
        )
        for item in parsed_items
    ]
    sortable.sort(key=lambda x: (x[0], x[1], x[2]))

    sorted_items = [
        _build_sorted_item(item, git_log_position=commit_position.get(item[5].hexsha))
        for _, _, _, item in sortable
    ]

    return sorted_items, errors
