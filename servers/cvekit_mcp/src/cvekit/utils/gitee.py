import re
import os
import shutil
import subprocess
import git
import logging
from typing import Optional, Dict, Tuple

from .cache import cached, _get_cache_key, ISSUE_CACHE
from .http import get_with_retry
from .locales import i18n

logger = logging.getLogger(__name__)

# 缓存已设置的仓库，避免重复调用 setup_repository
_repo_cache: Dict[Tuple[str, str, Optional[str]], Tuple[git.Repo, str]] = {}


@cached(
    ISSUE_CACHE,
    key_builder=lambda issue_url, gitee_token=None, use_cache=True: _get_cache_key(
        issue_url
    ),
    use_cache_kw="use_cache",
)
def parse_gitee_issue_url(
    issue_url: str, gitee_token: Optional[str] = None, use_cache: bool = True
) -> Dict[str, str]:
    """
    解析gitee issue URL并获取基本信息
    
    Args:
        issue_url: Gitee issue URL
        gitee_token: Gitee访问令牌
        use_cache: 是否使用缓存
    
    Returns:
        dict: 包含issue信息的字典
    """
    try:
        pattern = r"https://gitee.com/([^/]+)/([^/]+)/issues/([^/]+)"
        match = re.match(pattern, issue_url)
        if not match:
            pattern = r"https://atomgit.com/([^/]+)/([^/]+)/issues/([^/]+)"
            match = re.match(pattern, issue_url)
        if not match:
            pattern = r"https://gitcode.com/([^/]+)/([^/]+)/issues/([^/]+)"
            match = re.match(pattern, issue_url)
        if not match:
            raise ValueError(i18n("无效的gitee issue URL格式"))
        org = match.group(1)
        repo = match.group(2)
        issue_id = match.group(3)
    except Exception as e:
        logger.error(f"解析issue URL失败: {str(e)}")
        raise ValueError(i18n("解析issue URL失败: %s") % (str(e)))
    
    # 从Gitee API获取issue描述
    try:
        if issue_url.startswith("https://gitee.com"):
            api_url = issue_url.replace("gitee.com", "gitee.com/api/v5/repos")
        elif issue_url.startswith("https://gitcode.com"):
            api_url = issue_url.replace("gitcode.com", "api.gitcode.com/api/v5/repos")
        elif issue_url.startswith("https://atomgit.com"):
            api_url = issue_url.replace("atomgit.com", "api.gitcode.com/api/v5/repos")
        else:
            raise RuntimeError(f"issue url not recognized: {issue_url}")
        issue_api_url = (
            api_url
            + "?access_token="
            + gitee_token
        )
        logger.info(f"issue_api_url: {issue_api_url}")
        response = get_with_retry(issue_api_url)
        response.raise_for_status()
        issue_data = response.json()
        cve_id = issue_data["title"]
        body_text = issue_data["body"]
        version_start = body_text.find("漏洞归属的版本：") + len("漏洞归属的版本：")
        version_end = body_text.find("\n", version_start)
        version_str = body_text[version_start:version_end].strip()
        logger.info(f"受影响版本信息: {version_str}")
    except Exception as e:
        logger.error(f"获取issue信息失败: {str(e)}")
        raise

    result_data: Dict[str, str] = {
        "issue_id": issue_id,
        "issue_url": issue_url,
        "cve_id": cve_id,
        "org_name": org,
        "repo_name": repo,
        "affected_versions": version_str,
    }
    return result_data

def _clone_repository(
        org_name: str,
        repo_name: str,
        clone_dir: str,
        fork_repo_url,
        gitee_token: str = None
) -> str:
    """克隆Gitee仓库到本地（使用浅克隆）"""
    logger.info(f"克隆仓库: org={org_name}, repo={repo_name}, dir={clone_dir}")
    
    # 使用用户主目录下的Image目录
    local_path = os.path.join(clone_dir, repo_name)
    
    try:
        os.makedirs(clone_dir, exist_ok=True)
        
        # 检查目录是否已存在且是有效的git仓库
        if os.path.exists(local_path):
            if os.path.exists(os.path.join(local_path, '.git')):
                try:
                    git.Repo(local_path)
                    logger.info(f"有效的Git仓库已存在: {local_path}")
                    return local_path
                except git.InvalidGitRepositoryError:
                    logger.info(f"目录存在但不是有效的Git仓库，删除后重新克隆: {local_path}")
                    shutil.rmtree(local_path)
            else:
                logger.info(f"目录已存在但不是Git仓库，删除后重新克隆: {local_path}")
                shutil.rmtree(local_path)
        
        logger.info(f"使用浅克隆方式克隆仓库到 {local_path}")
        if fork_repo_url.startswith("https://gitee.om"):
            if gitee_token:
                clone_url = f"https://oauth2:{gitee_token}@gitee.com/{org_name}/{repo_name}.git"
            else:
                clone_url = f"https://gitee.com/{org_name}/{repo_name}.git"
        else:
            if gitee_token:
                clone_url = f"https://oauth2:{gitee_token}@gitcode.com/{org_name}/{repo_name}.git"
            else:
                clone_url = f"https://gitcode.com/{org_name}/{repo_name}.git"

        result = subprocess.run(
            ["git", "clone", clone_url, local_path],
            check=True,
            cwd=clone_dir,
            capture_output=True,
            text=True
        )
        
        if not os.path.exists(os.path.join(local_path, '.git')):
            raise RuntimeError(i18n("仓库克隆失败: %s") % (local_path))
        
        return local_path
    
    except subprocess.CalledProcessError as e:
        logger.error(f"克隆命令执行失败: {str(e)}")
        raise RuntimeError(i18n("无法克隆仓库: %s") % (str(e)))
    except Exception as e:
        logger.error(f"克隆操作失败: {str(e)}")
        raise RuntimeError(i18n("无法克隆仓库: %s") % (str(e)))


def setup_repository(fork_repo_url=None, gitee_token=None, clone_dir=None, branch_name=None, force_refresh=False):
    """
    设置仓库环境，克隆官方仓库，添加fork远程（可选），如果明确说明要检出某个分支的情况下，检出分支
    
    Args:
        fork_repo_url: fork仓库URL（可选，如果不提供则只克隆官方仓库）
        gitee_token: Gitee访问令牌（可选，用于私有仓库认证）
        clone_dir: 本地克隆目录
        branch_name: 要检出的分支名,默认可以不执行检出分支
        force_refresh: 是否强制刷新（忽略缓存）
        
    Returns:
        repo: git.Repo对象
        repo_path: 仓库本地路径
    """
    # 默认使用 openEuler kernel 仓库
    if not fork_repo_url:
        fork_repo_url = "https://gitee.com/openeuler/kernel"
        logger.info(f"未提供 fork_repo_url，使用默认值: {fork_repo_url}")
    
    # 使用缓存 key: (fork_repo_url, clone_dir, branch_name)
    cache_key = (fork_repo_url, clone_dir, branch_name)
    
    # 检查缓存
    if not force_refresh and cache_key in _repo_cache:
        cached_repo, cached_repo_path = _repo_cache[cache_key]
        # 验证缓存的 repo 是否仍然有效
        try:
            if cached_repo_path == os.path.join(clone_dir, "kernel") and os.path.exists(cached_repo_path):
                logger.debug(f"使用缓存的仓库设置: {cache_key}")
                return cached_repo, cached_repo_path
        except Exception:
            # 如果缓存无效，继续执行设置流程
            logger.debug(f"缓存无效，重新设置仓库: {cache_key}")
            del _repo_cache[cache_key]
    
    parts = fork_repo_url.strip().rstrip('/').split('/')
    fork_org = parts[-2]
    repo_name = parts[-1].replace('.git', '')
    repo_is_kernel = repo_name == "kernel"
    repo_path = os.path.join(clone_dir, "kernel" if repo_is_kernel else repo_name)
    official_org = "openeuler"
    
    # 确保主仓库（官方仓库）已克隆
    if not os.path.exists(repo_path) or not os.path.exists(os.path.join(repo_path, '.git')):
        _clone_repository(
            org_name=official_org if repo_is_kernel else fork_org,
            repo_name="kernel" if repo_is_kernel else repo_name,
            clone_dir=clone_dir,
            fork_repo_url=fork_repo_url,
            gitee_token=gitee_token
        )
    
    repo = git.Repo(repo_path)
    
    # 添加 fork 远程仓库（仅当提供了 fork_repo_url 时）
    fork_remote_name = f"fork-{fork_org}"
    if fork_remote_name not in [remote.name for remote in repo.remotes]:
        logger.debug(f"添加远程仓库: {fork_remote_name}")
        if gitee_token:
            if fork_repo_url.startswith("https://gitee.com"):
                auth_url = f"https://oauth2:{gitee_token}@gitee.com/{fork_org}/{repo_name}.git"
            else:
                auth_url = f"https://oauth2:{gitee_token}@gitcode.com/{fork_org}/{repo_name}.git"
        else:
            auth_url = fork_repo_url
        repo.create_remote(fork_remote_name, auth_url)
        # fetch 操作添加容错，失败时继续使用本地缓存
        try:
            repo.git.fetch('origin')
            repo.remote(fork_remote_name).fetch()
        except Exception as e:
            logger.warning(f"fetch 远程分支失败，继续使用本地缓存: {str(e)}")
    elif force_refresh:
        # 强制刷新时才执行 fetch
        logger.debug(f"强制刷新，执行 fetch 操作")
        try:
            repo.git.fetch('origin')
            repo.remote(fork_remote_name).fetch()
        except Exception as e:
            logger.warning(f"fetch 远程分支失败，继续使用本地缓存: {str(e)}")
    else:
        # 如果远程已存在且不强制刷新，跳过 fetch 操作
        logger.debug(f"远程仓库已存在，跳过 fetch 操作以节省时间")
    
    # 创建或切换到本地分支
    if branch_name:
        remote_branch_ref = f"{fork_remote_name}/{branch_name}"
        current_branches = repo.git.branch().split()
        if branch_name not in current_branches:
            logger.info(f"设置仓库，切换分支：{branch_name}， 同步远程分支：{remote_branch_ref}")
            try:
                repo.git.checkout('-b', branch_name, remote_branch_ref)
            except Exception as e:
                # 远程分支引用不存在，尝试从 origin 创建
                logger.warning(f"从 {remote_branch_ref} 创建分支失败: {str(e)}")
                origin_ref = f"origin/{branch_name}"
                logger.info(f"尝试从 {origin_ref} 创建分支")
                try:
                    repo.git.checkout('-b', branch_name, origin_ref)
                except Exception as e2:
                    raise RuntimeError(i18n("无法创建分支 %s：远程分支引用不存在") % branch_name) from e2
        else:
            # 只在强制刷新时才执行 pull
            if force_refresh:
                logger.info(f"设置仓库，切换本地分支：{branch_name}，同步{fork_remote_name}代码")
                repo.git.checkout(branch_name)
                try:
                    repo.git.pull(fork_remote_name, branch_name, "--rebase")
                except Exception as e:
                    logger.warning(f"pull 远程分支失败，继续使用本地分支: {str(e)}")
            else:
                logger.debug(f"切换到已存在的分支：{branch_name}（跳过 pull 以节省时间）")
                repo.git.checkout(branch_name)
    
    # 缓存结果
    _repo_cache[cache_key] = (repo, repo_path)
    
    return repo, repo_path


def get_issue_url_by_search(search_url, cve_id):
    html_url = ''
    try:
        response = get_with_retry(search_url)
        response.raise_for_status()
        issue_data = response.json()
    except Exception as e:
        logger.error(f"搜索issues失败: {str(e)}")
        return html_url
    if not issue_data:
        return html_url 
    for data in issue_data: 
        title = data.get('title', '').strip() 
        if cve_id == title: 
            html_url = data.get('html_url') 
            break 
    return html_url


@cached(
    ISSUE_CACHE,
    key_builder=lambda cve_id, get_issue_url_from_cve_id=None, use_cache=True, package_name=None: _get_cache_key(
        f"search_{cve_id}" if not package_name else f"search_{cve_id}_{package_name}"
    ),
    use_cache_kw="use_cache",
)
def get_issue_url_from_cve_id(cve_id: str, gitee_token: str = None, use_cache: bool = True, package_name: str = None) -> str:
    """
    通过CVE ID获取对应的issue URL
    
    Args:
        cve_id: CVE ID
        gitee_token: Gitee访问令牌（也用于gitcode.com）
        use_cache: 是否使用缓存
        package_name: 软件包名称（可选），如果提供则搜索该软件包仓库
    """
    issue_url = None
    
    if package_name:
        token_param = f"&access_token={gitee_token}" if gitee_token else ""
        request_url = f"https://api.gitcode.com/api/v5/repos/src-openeuler/{package_name}/issues?state=all&q={cve_id}{token_param}"            
        issue_url = get_issue_url_by_search(search_url=request_url, cve_id=cve_id)
    else:
        if gitee_token:
            request_url = f"https://api.atomgit.com/api/v5/repos/src-openeuler/kernel/issues?access_token={gitee_token}&search={cve_id}"
            issue_url = get_issue_url_by_search(request_url, cve_id)
        
        if not issue_url:
            logger.info(f"get_issue_url_from_cve_id: gitee_token not found, use gitee.com")
            request_url = f"https://gitee.com/api/v5/search/issues?q={cve_id}&page=1&per_page=20&repo=src-openeuler%2Fkernel&order=desc"
            issue_url = get_issue_url_by_search(request_url, cve_id)
    
    if not issue_url:
        target = f"软件包 {package_name}" if package_name else "内核仓库"
        raise RuntimeError(i18n("获取html_url失败， cve id: %s (目标: %s)") % (cve_id, target))
    
    logger.info(f"找到CVE {cve_id} 的issue URL: {issue_url}")
    return issue_url
