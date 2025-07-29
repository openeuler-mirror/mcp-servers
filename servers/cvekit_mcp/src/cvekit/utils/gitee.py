import re
import os
import shutil
import subprocess
import git
import requests
import logging
from .cache import get_cached_data, save_cache
from typing import Optional, Dict

logger = logging.getLogger(__name__)

def parse_gitee_issue_url(issue_url: str, gitee_token: Optional[str] = None, use_cache=True) -> Dict[str, str]:
    """
    解析gitee issue URL并获取基本信息
    
    Args:
        issue_url: Gitee issue URL
        gitee_token: Gitee访问令牌
        use_cache: 是否使用缓存
    
    Returns:
        dict: 包含issue信息的字典
    """
    from .cache import _get_cache_key, ISSUE_CACHE
    cache_key = _get_cache_key(issue_url)
    if use_cache:
        cached = get_cached_data(ISSUE_CACHE, cache_key)
        if cached:
            return cached
    try:
        pattern = r"https://gitee.com/([^/]+)/([^/]+)/issues/([^/]+)"
        match = re.match(pattern, issue_url)
        if not match:
            raise ValueError("无效的gitee issue URL格式")
        org = match.group(1)
        repo = match.group(2)
        issue_id = match.group(3)
    except Exception as e:
        logger.error(f"解析issue URL失败: {str(e)}")
        raise ValueError(f"无法解析issue URL: {str(e)}")
    
    # 从Gitee API获取issue描述
    try:
        issue_api_url = issue_url.replace("gitee.com", "gitee.com/api/v5/repos") + "?access_token=" + gitee_token
        logger.info(f"issue_api_url: {issue_api_url}")
        response = requests.get(issue_api_url)
        response.raise_for_status()
        issue_data = response.json()
        cve_id = issue_data['title']
        body_text = issue_data['body']
        version_start = body_text.find("漏洞归属的版本：") + len("漏洞归属的版本：")
        version_end = body_text.find("\n", version_start)
        version_str = body_text[version_start:version_end].strip()
        logger.info(f"受影响版本信息: {version_str}")
    except Exception as e:
        logger.error(f"获取issue信息失败: {str(e)}")
        raise
    
    result_data = {
        "issue_id": issue_id,
        "cve_id": cve_id,
        "org_name": org,
        "repo_name": repo,
        "affected_versions": version_str
    }
    if use_cache:
        save_cache(ISSUE_CACHE, cache_key, result_data)

    return result_data

def _clone_repository(
        org_name: str,
        repo_name: str,
        clone_dir: str,
        gitee_token: str = None
) -> str:
    """克隆Gitee仓库到本地（使用浅克隆）"""
    logger.info(f"克隆仓库: org={org_name}, repo={repo_name}, dir={clone_dir}")
    
    # 使用用户主目录下的Image目录
    home_dir = os.path.expanduser("~")
    safe_clone_dir = os.path.join(home_dir, "Image")
    local_path = os.path.join(safe_clone_dir, repo_name)
    
    try:
        os.makedirs(safe_clone_dir, exist_ok=True)
        
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
        
        if gitee_token:
            clone_url = f"https://oauth2:{gitee_token}@gitee.com/{org_name}/{repo_name}.git"
        else:
            clone_url = f"https://gitee.com/{org_name}/{repo_name}.git"
        
        result = subprocess.run(
            ["git", "clone", clone_url, local_path],
            check=True,
            cwd=safe_clone_dir,
            capture_output=True,
            text=True
        )
        
        if not os.path.exists(os.path.join(local_path, '.git')):
            raise RuntimeError(f"仓库克隆失败: {local_path}")
        
        return local_path
    
    except subprocess.CalledProcessError as e:
        logger.error(f"克隆命令执行失败: {str(e)}")
        raise RuntimeError(f"无法克隆仓库: {str(e)}")
    except Exception as e:
        logger.error(f"克隆操作失败: {str(e)}")
        raise RuntimeError(f"无法克隆仓库: {str(e)}")


def setup_repository(fork_repo_url, gitee_token, clone_dir, branch_name=None):
    """
    设置仓库环境，克隆官方仓库，添加fork远程，如果明确说明要检出某个分支的情况下，检出分支
    
    Args:
        fork_repo_url: fork仓库URL
        gitee_token: Gitee访问令牌
        branch_name: 要检出的分支名,默认可以不执行检出分支
        clone_dir: 本地克隆目录
        official_org: 官方仓库组织名，默认为"openeuler"
        
    Returns:
        repo: git.Repo对象
        repo_path: 仓库本地路径
    """
    parts = fork_repo_url.strip().rstrip('/').split('/')
    fork_org = parts[-2]
    repo_name = parts[-1].replace('.git', '')
    repo_path = os.path.join(clone_dir, "kernel")
    official_org = "openeuler"
    
    # 确保主仓库（官方仓库）已克隆
    if not os.path.exists(repo_path) or not os.path.exists(os.path.join(repo_path, '.git')):
        _clone_repository(
            org_name=official_org,
            repo_name="kernel",
            clone_dir=clone_dir,
            gitee_token=gitee_token
        )
    
    repo = git.Repo(repo_path)
    repo.git.fetch('origin')
    
    fork_remote_name = f"fork-{fork_org}"
    if fork_remote_name not in [remote.name for remote in repo.remotes]:
        auth_url = f"https://oauth2:{gitee_token}@gitee.com/{fork_org}/{repo_name}.git"
        repo.create_remote(fork_remote_name, auth_url)
    
    repo.remote(fork_remote_name).fetch()
    
    # 创建或切换到本地分支
    if branch_name:
        remote_branch_ref = f"{fork_remote_name}/{branch_name}"
        if branch_name not in repo.heads:
            logging.info(f"设置仓库，切换分支：{branch_name}， 同步远程分支：{remote_branch_ref}")
            repo.git.checkout('-b', branch_name, remote_branch_ref)
        else:
            logging.info(f"设置仓库，切换本地分支：{branch_name}，同步{fork_remote_name}代码")
            repo.git.checkout(branch_name)
            repo.git.pull(fork_remote_name, branch_name)
    
    return repo, repo_path