import re
import os
import logging
import time
import git

from .cache import (
    cached,
    _get_cache_key,
    COMMITS_CACHE,
)
from .patch import getUrlText, get_upstream_commit_from_url
from .tools.project import safe_git_reset_hard

logger = logging.getLogger(__name__)

def _ensure_clean_worktree(repo: git.Repo) -> None:
    """
    Ensure the worktree is clean before checkout.
    Only reset/clean when there are local changes or untracked files.
    """
    try:
        if repo.is_dirty(untracked_files=True):
            logger.info(
                "工作区非干净状态，执行 git reset --hard 和 git clean -fdx"
            )
            safe_git_reset_hard(repo)
            repo.git.clean("-fdx")
    except Exception as e:
        logger.warning(f"清理工作区失败: {str(e)}")


def get_upstream_commit_from_message(message):
    upstream_commit = ''
    if not message:
        return upstream_commit
    for line in message.split('\n'):
        line = line.strip().lower()
        if not line:
            continue
        if not upstream_commit:
            if re.match('\[ upstream commit [a-f0-9]{40} \]', line):
                upstream_commit = line.split()[-2]
            if re.match('commit [a-f0-9]{40} upstream.', line):
                upstream_commit = line.split()[-2]
    return upstream_commit


@cached(
    COMMITS_CACHE,
    # clone_dir / project_dir 仅用于本地 fallback，不影响缓存 key
    key_builder=lambda cve_id, use_cache=True, clone_dir=None, project_dir="": _get_cache_key(cve_id),
    use_cache_kw="use_cache",
    # 兼容旧版本缓存结构：{"introduced": "...", "fixed": "..."}
    load_transform=lambda v: (
        (v.get("introduced"), v.get("fixed"))
        if isinstance(v, dict) and "introduced" in v and "fixed" in v
        else v
    ),
)
def get_vulnerability_commits(
    cve_id: str,
    use_cache: bool = True,
    clone_dir: str | None = None,
    project_dir: str = "",
) -> tuple[str, str]:
    """
    获取漏洞相关的真实上游提交信息

    Args:
        cve_id: CVE ID
        use_cache: 是否使用缓存
        clone_dir: 可选，本地 clone 目录（回退使用）
        project_dir: 源仓库路径（优先用于确认 upstream commit，默认空则使用 clone_dir/linux）

    Returns:
        (introduced_commit, fixed_commit): 真实的上游引入提交和修复提交
    """
    logger.info(f"==========解析linux-cve-announce页面的两组commit id============")
    # 网络环境稳定情况下可使用 cve_announce_base_url = "https://lore.kernel.org/linux-cve-announce/"
    cve_announce_base_url = "http://localhost:8080/linux-cve-announce/"
    try:
        search_results_html = getUrlText(f"{cve_announce_base_url}?q={cve_id}")
    except Exception as e:
        logger.error(f"Failed to fetch vulnerability commits: {str(e)}")
        return None, None
    
    cve_detail_link_pattern = re.compile(f".*?<pre>1.*?<b><a.*?href=\"(?P<href>.*?)\">{cve_id}.*?", re.S)
    commit_section_pattern = re.compile(
        ".*?Affected and fixed versions.*?===========================(?P<href_text>.*?)Please see <a", re.S)
    commit_hash_pattern = re.compile(r'commit (\w+)', re.I)
    cve_detail_link_match = cve_detail_link_pattern.search(search_results_html)
    
    introduced_commit = None
    fixed_commit = None

    # 如果提供了 clone_dir 或 project_dir，则尝试构造本地 linux 仓库路径，
    # 优先使用 project_dir，否则使用 clone_dir/linux
    linux_repo_path = None
    linux_repo = None
    from os import path

    _linux_path = project_dir if (project_dir and path.exists(project_dir)) else (
        path.join(clone_dir, "linux") if clone_dir else None
    )
    if _linux_path and path.exists(_linux_path):
        try:
            import git  # 局部导入，避免循环依赖

            linux_repo = git.Repo(_linux_path)
            linux_repo_path = _linux_path
            logger.debug(
                "get_vulnerability_commits: 使用本地 linux 仓库做 upstream 解析: %s",
                linux_repo_path,
            )
        except Exception as e:
            logger.warning(
                "get_vulnerability_commits: 打开本地 linux 仓库失败，将跳过本地 upstream 解析: %s",
                e,
            )
            linux_repo = None
    
    if cve_detail_link_match:
        detail_url = cve_detail_link_match.group("href")
        commit_page_html = getUrlText(f"{cve_announce_base_url}{detail_url}")
        commit_section_match = commit_section_pattern.search(commit_page_html)
        if commit_section_match:
            commit_section_text = commit_section_match.group("href_text").strip()
            commit_lines = commit_section_text.split("\n")
            
            # 查找第一个引入提交和第一个修复提交
            for commit_line in commit_lines:
                if introduced_commit and fixed_commit:
                    break
                    
                line = commit_line.strip()
                if not line:
                    continue
                line = line.lower()
                    
                if 'introduced' in line and not introduced_commit:
                    intro_pos = line.find('introduced')
                    hash_match = commit_hash_pattern.search(line, pos=intro_pos)
                    if hash_match:
                        commit_hash = hash_match.group(1)
                        # 1) 先尝试在本地 linux 仓库中直接确认该 commit 是否存在，
                        #    若存在，则视为真实的 upstream commit，避免走网络请求。
                        if linux_repo is not None:
                            try:
                                commit = linux_repo.commit(commit_hash)
                                introduced_commit = commit_hash
                                temp_commit_id = get_upstream_commit_from_message(commit.message)
                                if temp_commit_id:
                                    introduced_commit = temp_commit_id
                                logger.debug(
                                    "get_vulnerability_commits: introduced commit 在本地 linux 仓库中存在，"
                                    "commit_hash: %s, temp_commit_id: %s, introduced_commit: %s",
                                    commit_hash,
                                    temp_commit_id,
                                    introduced_commit
                                )
                            except Exception:
                                # 本地不存在该 commit，稍后再通过网络尝试解析 upstream
                                pass

                        # 2) 如果本地找不到，再通过 URL + get_upstream_commit_from_url 解析 upstream
                        if not introduced_commit:
                            commit_url = (
                                "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/"
                                f"?id={commit_hash}"
                            )
                            introduced_commit = get_upstream_commit_from_url(
                                commit_url,
                                linux_repo_path=linux_repo_path,
                            )
            
                if 'fixed' in line and not fixed_commit:
                    fixed_pos = line.find('fixed')
                    hash_match = commit_hash_pattern.search(line, pos=fixed_pos)
                    if hash_match:
                        commit_hash = hash_match.group(1)
                        # 1) 先尝试在本地 linux 仓库中直接确认该 commit 是否存在，
                        #    若存在，则视为真实的 upstream commit，避免走网络请求。
                        upstream_commit = None
                        if linux_repo is not None:
                            try:
                                commit = linux_repo.commit(commit_hash)
                                upstream_commit = commit_hash
                                temp_commit_id = get_upstream_commit_from_message(commit.message)
                                if temp_commit_id:
                                    upstream_commit = temp_commit_id
                                logger.debug(
                                    "get_vulnerability_commits: fixed commit 在本地 linux 仓库中存在，"
                                    "commit_hash: %s, temp_commit_id: %s, upstream_commit: %s",
                                    commit_hash,
                                    temp_commit_id,
                                    upstream_commit
                                )
                            except Exception:
                                # 本地不存在该 commit，稍后再通过网络尝试解析 upstream
                                pass

                        # 2) 如果本地找不到，再通过 URL + get_upstream_commit_from_url 解析 upstream
                        if not upstream_commit:
                            commit_url = (
                                "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/"
                                f"?id={commit_hash}"
                            )
                            upstream_commit = get_upstream_commit_from_url(
                                commit_url,
                                linux_repo_path=linux_repo_path,
                            )

                        # 如果最终找不到 upstream commit，使用原始 commit 作为备选
                        if upstream_commit:
                            fixed_commit = upstream_commit
                        else:
                            logger.error(
                                "无法获取fixed commit的upstream版本，使用原始commit: %s",
                                commit_hash,
                            )
    
    logger.info(f"introduced_commit: {introduced_commit}, fixed_commit: {fixed_commit}")
    
    return introduced_commit, fixed_commit


def fetch_and_update_repo(repo: git.Repo, branch_name: str) -> bool:
    """
    切换分支并更新

    Args:
        repo: git repo
        branch_name: 切换分支名
    """
    try:
        remote = repo.remote("origin")
    except Exception as e:
        logger.warning("fetch_and_update_repo: 无法获取远程 origin: %s", str(e))
        return False

    try:
        remote.fetch()
    except Exception as e:
        logger.warning("fetch_and_update_repo: fetch origin 失败: %s", str(e))
        return False

    remote_branch = f"origin/{branch_name}"
    remote_refs = {ref.name for ref in remote.refs}
    if remote_branch not in remote_refs:
        logger.warning(
            "fetch_and_update_repo: 远程分支不存在: %s (origin refs: %s)",
            remote_branch,
            ", ".join(sorted(remote_refs)) if remote_refs else "EMPTY",
        )
        return False

    local_branches = {head.name for head in repo.heads}
    try:
        if branch_name in local_branches:
            logger.debug("fetch_and_update_repo: 本地分支 %s 已存在，执行 checkout", branch_name)
            _ensure_clean_worktree(repo)
            repo.git.checkout(branch_name)
        else:
            logger.debug("fetch_and_update_repo: 本地分支 %s 不存在，创建并跟踪 %s", branch_name, remote_branch)
            _ensure_clean_worktree(repo)
            repo.git.checkout("-b", branch_name, "--track", remote_branch)
    except Exception as e:
        logger.warning(
            "fetch_and_update_repo: 切换/创建分支失败: %s, error: %s",
            branch_name,
            str(e),
        )
        return False

    # 使用 --ff-only 避免 rebase 冲突导致流程中断
    try:
        repo.git.pull("origin", branch_name, "--ff-only")
        logger.info("fetch_and_update_repo: 成功 fetch+checkout+pull 分支 %s", branch_name)
    except Exception as e:
        logger.warning(
            "fetch_and_update_repo: pull --ff-only 失败，将继续使用本地分支状态: %s",
            str(e),
        )
    return True


def _checkout_local_branch(repo: git.Repo, branch_name: str) -> bool:
    """
    仅切换到本地已有分支（不触发 fetch/pull）
    """
    local_branches = {head.name for head in repo.heads}
    if branch_name not in local_branches:
        logger.warning(
            "_checkout_local_branch: 本地不存在分支 %s，可用分支: %s",
            branch_name,
            ", ".join(sorted(local_branches)) if local_branches else "EMPTY",
        )
        return False
    try:
        _ensure_clean_worktree(repo)
        repo.git.checkout(branch_name)
        logger.info("_checkout_local_branch: 成功切换到本地分支 %s", branch_name)
    except Exception as e:
        logger.warning(
            "_checkout_local_branch: 切换分支失败: %s, error: %s",
            branch_name,
            str(e),
        )
        return False
    return True


def branch_commit_from_upstream(fixed_commit: str, branch_name: str, clone_dir: str, project_dir: str = ""):
    """
    使用upstream版本的commit id找上游对应分支上的commit id

    Args:
        fixed_commit: git repo
        branch_name: branch name
        clone_dir: linux代码克隆目录（回退使用）
        project_dir: 源仓库路径（优先使用）

    Returns:
        commit_id: 分支适配commit id
    """
    linux_repo_path = project_dir if (project_dir and os.path.exists(project_dir)) else os.path.join(clone_dir, "linux")
    if not os.path.exists(linux_repo_path):
        logger.warning('branch_commit_from_upstream: path %s not exists', linux_repo_path)
        return ''
    logger.info(
        "branch_commit_from_upstream: start, fixed_commit=%s, branch_name=%s",
        fixed_commit, branch_name,
    )
    repo_linux = git.Repo(linux_repo_path)
    linux_branch = f"{branch_name.replace('OLK', 'linux')}.y"
    logger.debug("branch_commit_from_upstream: linux_branch=%s", linux_branch)
    use_cache_only = os.getenv("LINUX_REPO_USE_CACHE_ONLY", "").lower() in (
        "1",
        "true",
        "yes",
    )
    logger.debug("branch_commit_from_upstream: use_cache_only=%s", use_cache_only)
    ok = False
    if use_cache_only:
        ok = _checkout_local_branch(repo_linux, linux_branch)
    else:
        try:
            ok = fetch_and_update_repo(repo_linux, linux_branch)
        except Exception as e:
            logger.warning(f'branch_commit_from_upstream: {str(e)}')
            return ''
        if not ok:
            # fetch/pull 失败时，尝试使用本地缓存继续
            logger.info("branch_commit_from_upstream: fetch/pull failed, fallback to local branch")
            ok = _checkout_local_branch(repo_linux, linux_branch)
    if not ok:
        logger.warning("branch_commit_from_upstream: failed to checkout branch %s", linux_branch)
        return ''
    since_tag = branch_name.replace('OLK-', 'v')
    logger.debug("branch_commit_from_upstream: since_tag=%s", since_tag)
    # 使用 origin/<branch> 而非本地分支，因为 fetch 后远端 tracking ref 已是最新，
    # 即使本地分支 checkout/pull 失败落后，也不影响从远端 ref 搜索 commit
    remote_branch = f"origin/{linux_branch}"
    try:
        grep_output = repo_linux.git.log(
                        "--since", since_tag,
                        "--grep", fixed_commit,
                        remote_branch
                    )
        if not grep_output:
            logger.info(
                "branch_commit_from_upstream: git log --since returned empty, "
                "retrying without --since, branch_name=%s, fixed_commit=%s",
                branch_name, fixed_commit,
            )
            grep_output = repo_linux.git.log(
                            "--grep", fixed_commit,
                            remote_branch
                        )
    except Exception as e:
        logger.warning(f'branch_commit_from_upstream: git log failed: {str(e)}')
        return ''
    if not grep_output:
        logger.warning(
            "branch_commit_from_upstream: git log returned empty for fixed_commit=%s, branch=%s",
            fixed_commit, linux_branch,
        )
        return ''
    logger.debug(
        "branch_commit_from_upstream: grep_output length=%d, first 500 chars:\n%s",
        len(grep_output), grep_output[:500],
    )
    commit_id = ''
    upstream_commit = ''
    for line in grep_output.split('\n'):
        line_stripped = line.strip()
        line_lower = line_stripped.lower()
        if not line_lower:
            continue
        if not commit_id:
            if re.match('commit [a-f0-9]{40}', line_lower):
                commit_id = line_lower.split()[-1]
                logger.debug(
                    "branch_commit_from_upstream: found commit_id=%s, line=%s",
                    commit_id, line_stripped[:120],
                )
        if not upstream_commit:
            if re.match(r'\[ upstream commit [a-f0-9]{40} \]', line_lower):
                upstream_commit = line_lower.split()[-2]
                logger.debug(
                    "branch_commit_from_upstream: matched [upstream commit] pattern, "
                    "upstream_commit=%s, line=%s",
                    upstream_commit, line_stripped[:120],
                )
            if re.match(r'commit [a-f0-9]{40} upstream.', line_lower):
                upstream_commit = line_lower.split()[-2]
                logger.debug(
                    "branch_commit_from_upstream: matched 'commit ... upstream' pattern, "
                    "upstream_commit=%s, line=%s",
                    upstream_commit, line_stripped[:120],
                )
    if not upstream_commit:
        logger.warning(
            "branch_commit_from_upstream: upstream_commit is empty! "
            "fixed_commit=%s, branch_name=%s, commit_id=%s, grep_output first 1000 chars:\n%s",
            fixed_commit, branch_name, commit_id, grep_output[:1000],
        )
    logger.info(
        "branch_commit_from_upstream: upstream commit: %s, branch commit: %s, branch name: %s",
        upstream_commit,
        commit_id,
        branch_name
        )
    if upstream_commit == fixed_commit:
        return commit_id
    logger.info(
        "branch_commit_from_upstream: upstream_commit(%s) != fixed_commit(%s), return empty",
        upstream_commit, fixed_commit,
    )
    return ''
