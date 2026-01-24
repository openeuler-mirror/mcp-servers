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

logger = logging.getLogger(__name__)


@cached(
    COMMITS_CACHE,
    # clone_dir 仅用于本地 fallback，不影响缓存 key，这里忽略即可
    key_builder=lambda cve_id, use_cache=True, clone_dir=None: _get_cache_key(cve_id),
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
) -> tuple[str, str]:
    """
    获取漏洞相关的真实上游提交信息
    
    Args:
        cve_id: CVE ID
        use_cache: 是否使用缓存
        clone_dir: 可选，本地 clone 目录（用于在网络受限时，从 clone_dir/linux 本地仓库中确认 upstream commit）
    
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

    # 如果提供了 clone_dir，则尝试构造本地 linux 仓库路径，并提前加载仓库对象，
    # 这样可以在解析出 commit_hash 后先在本地仓库中确认是否存在该提交，避免不必要的网络请求。
    linux_repo_path = None
    linux_repo = None
    if clone_dir:
        from os import path

        linux_repo_path = path.join(clone_dir, "linux")
        if path.exists(linux_repo_path):
            try:
                import git  # 局部导入，避免循环依赖

                linux_repo = git.Repo(linux_repo_path)
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
                                linux_repo.commit(commit_hash)
                                introduced_commit = commit_hash
                                logger.debug(
                                    "get_vulnerability_commits: introduced commit 在本地 linux 仓库中存在，"
                                    "直接作为 upstream 使用: %s",
                                    commit_hash,
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
                                linux_repo.commit(commit_hash)
                                upstream_commit = commit_hash
                                logger.debug(
                                    "get_vulnerability_commits: fixed commit 在本地 linux 仓库中存在，"
                                    "直接作为 upstream 使用: %s",
                                    commit_hash,
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


def fetch_and_update_repo(repo: git.Repo, branch_name: str):
    """
    切换分支并更新

    Args:
        repo: git repo
        branch_name: 切换分支名
    """
    repo.git.fetch('origin')
    repo.remote('origin').fetch()
    current_branches = repo.git.branch().split()
    repo.git.checkout(branch_name)
    repo.git.pull('origin', branch_name, "--rebase")


def branch_commit_from_upstream(fixed_commit: str, branch_name: str, clone_dir: str):
    """
    使用upstream版本的commit id找上游对应分支上的commit id

    Args:
        fixed_commit: git repo
        branch_name: branch name
        clone_dir: linux代码克隆目录

    Returns:
        commit_id: 分支适配commit id
    """
    linux_repo_path = os.path.join(clone_dir, "linux")
    repo_linux = git.Repo(linux_repo_path)
    linux_branch = f"{branch_name.replace('OLK', 'linux')}.y"
    try:
        fetch_and_update_repo(repo_linux, linux_branch)
    except Exception as e:
        logger.warning(f'branch_commit_from_upstream: {str(e)}')
        return '' 
    since_tag = branch_name.replace('OLK-', 'v')
    try:
        grep_output = repo_linux.git.log(
                        "--since", since_tag,
                        "--grep", fixed_commit,
                        linux_branch
                    )
    except Exception as e:
        logger.warning(f'branch_commit_from_upstream: {str(e)}')
        return '' 
    commit_id = ''
    upstream_commit = ''
    for line in grep_output.split('\n'):
        line = line.strip().lower()
        if not line:
            continue
        if not commit_id:
            if re.match('commit [a-f0-9]{40}', line):
                commit_id = line.split()[-1]
        if not upstream_commit:
            if re.match('\[ upstream commit [a-f0-9]{40} \]', line):
                upstream_commit = line.split()[-2]
            if re.match('commit [a-f0-9]{40} upstream.', line):
                upstream_commit = line.spilt()[-2]
    logger.info(
        "branch_commit_from_upstream: upstream commit: %s, branch commit: %s, branch name: %s",
        upstream_commit,
        commit_id,
        branch_name
        )
    if upstream_commit == fixed_commit:
        return commit_id
    return ''
