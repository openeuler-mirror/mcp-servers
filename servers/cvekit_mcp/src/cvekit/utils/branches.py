import git
import logging
import os
from .gitee import setup_repository
from .patch import get_cve_patch, getUrlText
from .commits import get_vulnerability_commits
from .locales import i18n

logger = logging.getLogger(__name__)

def get_branches_containing_commit(repo, commit_hash):
    """获取包含指定commit的所有分支（包括远程分支）"""
    try:
        # 获取所有包含该commit的分支（包括远程分支）
        output = repo.git.branch("-a", "--contains", commit_hash)
        branches = []
        for branch in output.splitlines():
            branch = branch.strip('*').strip()
            # 处理远程分支（格式：remotes/origin/分支名）
            if branch.startswith('remotes/'):
                # 提取最后一部分作为分支名
                branch = branch.split('/')[-1]
            branches.append(branch)
        
        # 去重并保持顺序
        seen = set()
        unique_branches = []
        for branch in branches:
            if branch not in seen:
                seen.add(branch)
                unique_branches.append(branch)
                
        return unique_branches
    except Exception as e:
        logger.error(f"获取包含commit的分支失败: {str(e)}")
        return []

def git_apply_check_patch(
        fork_repo_url: str,
        commit_hash: str,
        gitee_token: str,
        branch_name: str,
        clone_dir: str = os.path.join(os.path.expanduser("~"), "Image"),
        patch_url: str = "",
):
    logger.info(f"检查补丁能否应用: {commit_hash}")
    if not patch_url:
        patch_url = f'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id={commit_hash}'

    # 创建补丁文件
    patch_filename = f"commit_patch_{commit_hash}.patch"
    patch_path = os.path.join(clone_dir, patch_filename)
    with open(patch_path, "w") as f:
        f.write(getUrlText(patch_url))
 
    repo, repo_path = setup_repository(fork_repo_url, gitee_token, clone_dir, branch_name)
    
    # 检查补丁是否可应用
    try:
        repo.git.apply("--check", patch_path)
        return {
            "status": "success",
            "repo_path": repo_path,
            "patch_path": patch_path,
            "hash": commit_hash
        }
    except git.exc.GitCommandError as e:
        return {
            "status": "error",
            "repo_path": repo_path,
            "patch_path": patch_path,
            "error": str(e)
        }

def check_cve_patch_apply_status(
        fork_repo_url: str,
        cve_id: str,
        gitee_token: str,
        branch_name: str,
        fixed_commit: str = "",
        clone_dir: str = os.path.join(os.path.expanduser("~"), "Image")
):
    try:
        patch_api_url = 'https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num=' + cve_id
        
        if fixed_commit:
            commit_hash = fixed_commit
            patch_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id={commit_hash}"
        else:
            patch_info = get_cve_patch(patch_api_url)
            if not patch_info:
                logger.error("无法获取补丁信息")
                return []
            commit_hash = patch_info["hash"]
            patch_url = patch_info["patch_url"]
        
        # 处理单个补丁
        item = git_apply_check_patch(
            fork_repo_url,
            commit_hash,
            gitee_token,
            branch_name,
            clone_dir,
            patch_url,
        )
        return [item]
        
    except Exception as e:
        logger.error(f"获取补丁信息失败: {str(e)}")
        return []

def process_branches(repo, issue_info, fork_repo_url, gitee_token, clone_dir, signer_name, signer_email, branchList):
    """处理所有需要补丁的分支"""
    logger.info(f"分析分支: {branchList}")
    items = []
    
    vulnerable_branches = get_branches_containing_commit(repo, issue_info.introduced_commit)
    logger.info(f"包含引入commit的分支: {vulnerable_branches}")
    
    fixed_branches = get_branches_containing_commit(repo, issue_info.fixed_commit)
    logger.info(f"包含修复commit的分支: {fixed_branches}")
    
    needs_patch_branches = [branch for branch in vulnerable_branches
                           if branch in branchList and branch not in fixed_branches]
    logger.info(f"需要补丁的分支: {needs_patch_branches}")
    
    repo.git.fetch('--all')
    
    for branch in needs_patch_branches:
        remote_branch = f"origin/{branch}"
        try:
            # 尝试切换到本地分支（如果存在）
            repo.git.checkout(branch)
        except Exception:
            try:
                # 如果本地分支不存在，创建并切换到跟踪分支
                repo.git.checkout('-b', branch, '--track', remote_branch)
            except Exception as e:
                logger.error(f"创建并切换分支 {branch} 失败: {str(e)}")
                continue
            
        patchs = check_cve_patch_apply_status(fork_repo_url, issue_info.cve_id, gitee_token, branch, issue_info.fixed_commit, clone_dir)
        logger.info(f"分支 {branch} 的补丁信息: {patchs}")
        
        for patch in patchs:
            if patch['status'] == 'success':
                items.append({
                    "补丁ID": issue_info.cve_id,
                    "目标分支": branch,
                    "是否受影响": i18n("受影响"),
                    "适配状态": i18n("成功"),
                    "冲突点": patch['patch_path'],
                    "建议调整文件": "N/A",
                })
            else:
                items.append({
                    "补丁ID": issue_info.cve_id,
                    "目标分支": branch,
                    "是否受影响": i18n("受影响"),
                    "适配状态": i18n("需要调整"),
                    "冲突点": patch['patch_path'],
                    "建议调整文件": "",
                })
    
    fixed_in_branches = [branch for branch in branchList if branch in fixed_branches]
    for branch in fixed_in_branches:
        items.append({
            "补丁ID": issue_info.cve_id,
            "目标分支": branch,
            "是否受影响": i18n("已修复"),
            "适配状态": "",
            "冲突点": i18n("已修复"),
            "建议调整文件": "N/A",
        })
    
    unaffected_branches = [branch for branch in branchList
                          if branch not in vulnerable_branches and branch not in fixed_branches]
    for branch in unaffected_branches:
        items.append({
            "补丁ID": issue_info.cve_id,
            "目标分支": branch,
            "是否受影响": i18n("不受影响"),
            "适配状态": "",
            "冲突点": i18n("无"),
            "建议调整文件": "N/A",
        })
    
    return items