import git
import logging
import os
from datetime import datetime

from .gitee import setup_repository
from .patch import get_cve_patch, getUrlText, ensure_patch_file
from .commits import get_vulnerability_commits, branch_commit_from_upstream
from .locales import i18n
from .cache import BRANCHES_ANALYSIS_CACHE, _get_cache_key, cached, load_cache
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

def get_commit_date(repo, commit_hash, linux_repo=None):
    """获取 commit 的提交日期字符串（YYYY-MM-DD），用于 git log --since
    
    注意：
        - 直接使用 git 命令（--date=short --format=%cd）来获取日期，
          避免 Python 本地时区与 git 行为不一致的问题。
    
    Args:
        repo: Git 仓库对象（kernel 仓库，用于回退）
        commit_hash: 要查询的 commit hash
        linux_repo: 可选，linux 仓库对象，优先从 linux 仓库查询
    """
    # 优先从 linux 仓库查询
    if linux_repo is not None:
        try:
            # 使用 git log -1 --date=short --format=%cd 输出类似 2019-02-27 的日期
            date_str = linux_repo.git.log(
                "-1",
                "--date=short",
                "--format=%cd",
                commit_hash,
            ).strip()
            return date_str
        except Exception as e:
            logger.debug(
                f"无法从 linux 仓库获取 commit {commit_hash} 的提交日期: {str(e)}，尝试从 kernel 仓库查询"
            )
    
    # 如果 linux 仓库查询失败，从 kernel 仓库查询
    try:
        date_str = repo.git.log(
            "-1",
            "--date=short",
            "--format=%cd",
            commit_hash,
        ).strip()
        return date_str
    except Exception as e:
        logger.warning(f"无法获取 commit {commit_hash} 的提交日期: {str(e)}")
        return None

def get_commit_message(repo, commit_hash, linux_repo=None, max_length=200):
    """获取commit的提交信息（commit message）
    
    Args:
        repo: Git仓库对象（kernel仓库，用于回退）
        commit_hash: 要查询的commit hash
        linux_repo: 可选，linux仓库对象，优先从linux仓库查询
        max_length: 最大长度，超过则截断
    """
    # 优先从linux仓库查询
    if linux_repo is not None:
        try:
            commit = linux_repo.commit(commit_hash)
            message = commit.message.strip()
            # 只取第一行（标题）
            first_line = message.split('\n')[0]
            if len(first_line) > max_length:
                return first_line[:max_length] + "..."
            return first_line
        except Exception as e:
            logger.debug(f"无法从linux仓库获取commit {commit_hash} 的提交信息: {str(e)}，尝试从kernel仓库查询")
    
    # 如果linux仓库查询失败，从kernel仓库查询
    try:
        commit = repo.commit(commit_hash)
        message = commit.message.strip()
        # 只取第一行（标题）
        first_line = message.split('\n')[0]
        if len(first_line) > max_length:
            return first_line[:max_length] + "..."
        return first_line
    except Exception as e:
        logger.debug(f"无法获取commit {commit_hash} 的提交信息: {str(e)}")
        return None

def get_branches_containing_commit(repo, commit_hash, target_branches, linux_repo=None):
    """获取包含指定commit的分支，使用时间范围优化查询
    
    Args:
        repo: Git仓库对象（kernel仓库）
        commit_hash: 要查询的commit hash
        target_branches: 指定要查询的分支列表
        linux_repo: 可选，linux仓库对象，用于查询commit时间
    """
    if not target_branches:
        return []
    
    result = []
    
    # 获取 commit 的提交日期字符串（优先从 linux 仓库查询）
    date_str = get_commit_date(repo, commit_hash, linux_repo=linux_repo)
    
    # 为每个分支找到正确的分支引用
    unique_branches = []
    for branch_name in target_branches:
        # 尝试多种分支引用格式
        branch_refs = [
            branch_name,  # 本地分支
            f"origin/{branch_name}",  # origin远程分支
        ]
        # 查找fork远程名称
        try:
            remotes = repo.git.remote().splitlines()
            for remote in remotes:
                if remote != 'origin':
                    branch_refs.append(f"{remote}/{branch_name}")
        except Exception:
            pass
        
        # 尝试每个分支引用，找到第一个存在的
        found = False
        for branch_ref in branch_refs:
            try:
                # 尝试检查分支是否存在（通过尝试获取分支的HEAD）
                logger.info(f"执行 git rev-parse {branch_ref}")
                repo.git.rev_parse(branch_ref)
                unique_branches.append((branch_name, branch_ref))
                found = True
                break
            except git.exc.GitCommandError:
                continue
        
        if not found:
            logger.debug(f"分支 {branch_name} 不存在，跳过")
    
    if not unique_branches:
        return []
    
    # 如果无法获取 commit 日期，回退到原始方法
    if not date_str:
        logger.debug(f"无法获取 commit 日期，使用原始方法查询: {commit_hash}")
        for branch_name, branch_ref in unique_branches:
            try:
                # 使用 -a 确保同时检查本地和远程分支，否则只有远程跟踪分支时会查不到
                logger.info(f"执行 git branch -a --contains {commit_hash} {branch_ref}")
                if repo.git.branch("-a", "--contains", commit_hash, branch_ref):
                    result.append(branch_name)
            except Exception:
                continue
        return result
    
    logger.debug(f"使用时间范围优化查询: commit={commit_hash}, date={date_str}")
    
    # 对每个分支，使用时间范围查询
    for branch_name, branch_ref in unique_branches:
        found = False
        try:
            # 方法1: 直接检查commit是否在分支历史中
            # 使用 --since 参数限制查询范围，只查询该commit提交时间之后的commit
            # 直接查询该时间之后的commit hash列表，然后检查目标commit是否在其中
            logger.info(
                f"执行 git log --since {date_str} --format=%H {branch_ref} "
                f"用于检查 commit 是否在分支历史中: {commit_hash}"
            )
            log_output = repo.git.log(
                "--since", date_str,
                "--format=%H",
                branch_ref
            )
            # 检查目标commit是否在结果中
            if log_output and (commit_hash in log_output or commit_hash[:12] in log_output):
                found = True
        except git.exc.GitCommandError:
            pass
        except Exception as e:
            logger.debug(f"查询分支 {branch_name} 的commit历史时出错: {str(e)}")
        
        # 方法2: 如果方法1没找到，检查commit message中是否提到这个commit hash
        # 这适用于通过PR合入的情况，commit message中可能会提到上游commit hash
        if not found:
            try:
                logger.info(
                    f"执行 git log --since {date_str} --grep {commit_hash} {branch_ref} "
                    "用于在 commit message 中搜索上游 commit hash"
                )
                grep_output = repo.git.log(
                    "--since", date_str,
                    "--grep", commit_hash,
                    branch_ref
                )
                if grep_output:
                    found = True
            except git.exc.GitCommandError:
                pass
            except Exception as e:
                logger.debug(f"查询分支 {branch_name} 的commit message时出错: {str(e)}")
        
        # 如果两种方法都没找到，尝试使用原始方法（不使用时间范围）
        if not found:
            try:
                # 同样使用 -a，避免只存在远程分支时查不到
                logger.info(f"执行 git branch -a --contains {commit_hash} {branch_ref}（回退查询）")
                if repo.git.branch("-a", "--contains", commit_hash, branch_ref):
                    found = True
            except Exception:
                pass
        
        if found:
            result.append(branch_name)
    
    return result

def git_apply_check_patch(
        fork_repo_url: str,
        commit_hash: str,
        gitee_token: str = None,
        branch_name: str = "",
        clone_dir: str = os.path.join(os.path.expanduser("~"), "Image"),
        patch_path: str = "",
        repo: git.Repo = None,
):
    # 如果提供了 repo，直接使用；否则调用 setup_repository（会使用缓存）
    if repo is None:
        repo, repo_path = setup_repository(fork_repo_url, gitee_token, clone_dir, branch_name)
    else:
        repo_path = repo.working_dir
        # 确保切换到正确的分支（如果提供了 repo）
        try:
            current_branch = repo.active_branch.name if not repo.head.is_detached else None
            if current_branch != branch_name:
                _ensure_clean_worktree(repo)
                logger.info(f"执行 git checkout {branch_name}（当前分支: {current_branch}）")
                logger.debug(f"切换到分支: {branch_name}")
                repo.git.checkout(branch_name)
        except Exception as e:
            # 如果分支不存在，调用 setup_repository 来创建分支
            logger.debug(f"分支 {branch_name} 不存在，调用 setup_repository 创建: {str(e)}")
            repo, repo_path = setup_repository(fork_repo_url, gitee_token, clone_dir, branch_name)
    
    # 检查补丁是否可应用
    try:
        logger.info(f"执行 git apply --check {patch_path}（repo: {repo_path}）")
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
        gitee_token: str = None,
        branch_name: str = "",
        fixed_commit: str = "",
        clone_dir: str = os.path.join(os.path.expanduser("~"), "Image"),
        repo: git.Repo = None,
):
    try:
        patch_api_url = 'https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num=' + cve_id

        if fixed_commit:
            commit_hash = fixed_commit
            commit_id = branch_commit_from_upstream(fixed_commit, branch_name, clone_dir)
            if commit_id:
                logger.info(
                    "check_cve_patch_apply_status: fixed_commit: %s, branch_name: %s, commit_id: %s",
                    fixed_commit,
                    branch_name,
                    commit_id
                    )
                commit_hash = commit_id
            patch_filename = f"commit_patch_{commit_hash}.patch"
            patch_path = os.path.abspath(os.path.join(clone_dir, patch_filename))
            # 固定 commit 的场景：优先从本地 linux 仓库生成 patch，如果失败再从 kernel.org 获取并校验
            patch_path = ensure_patch_file(
                commit_hash=commit_hash,
                patch_path=patch_path,
                clone_dir=clone_dir,
            )
        else:
            logger.info(f"从 CVE 管理平台获取补丁信息: {patch_api_url}")
            patch_info = get_cve_patch(patch_api_url)
            if not patch_info:
                logger.error("无法获取补丁信息")
                return []
            commit_hash = patch_info["hash"]
            patch_filename = f"commit_patch_{commit_hash}.patch"
            patch_path = os.path.abspath(os.path.join(clone_dir, patch_filename))
            patch_url = patch_info["patch_url"]
            # CVE 场景：优先从本地 linux 仓库生成 patch，如果失败再根据 CVE 提供的 URL 从网络获取并校验
            patch_path = ensure_patch_file(
                commit_hash=commit_hash,
                patch_path=patch_path,
                clone_dir=clone_dir,
                patch_url=patch_url,
            )
            logger.info(f"检查补丁能否应用: {commit_hash}")
        
        # 处理单个补丁，传递 repo 参数避免重复调用 setup_repository
        item = git_apply_check_patch(
            fork_repo_url,
            commit_hash,
            gitee_token,
            branch_name,
            clone_dir,
            patch_path,
            repo=repo,
        )
        return [item]
        
    except Exception as e:
        logger.error(f"获取补丁信息失败: {str(e)}")
        return []

@cached(
    BRANCHES_ANALYSIS_CACHE,
    key_builder=lambda repo, issue_info, fork_repo_url, gitee_token, clone_dir, branchList, use_cache=True: _get_cache_key(
        issue_info.cve_id, ",".join(sorted(branchList))
    ),
    use_cache_kw="use_cache",
)
def process_branches(repo, issue_info, fork_repo_url, gitee_token=None, clone_dir=None, branchList=None, use_cache=True):
    """处理所有需要补丁的分支
    
    Args:
        repo: Git仓库对象
        issue_info: 问题信息对象
        fork_repo_url: Fork仓库URL
        gitee_token: Gitee访问令牌（可选，用于私有仓库认证）
        clone_dir: 克隆目录
        branchList: 分支列表
        use_cache: 是否使用缓存
    """
    logger.info(f"分析分支: {branchList}")
    
    # 缓存未命中，执行分析
    items = []
    
    # 尝试从linux仓库获取commit时间
    linux_repo = None
    linux_repo_path = os.path.join(clone_dir, "linux")
    if os.path.exists(linux_repo_path):
        try:
            linux_repo = git.Repo(linux_repo_path)
            logger.debug(f"使用linux仓库查询commit时间: {linux_repo_path}")
        except Exception as e:
            logger.debug(f"无法打开linux仓库: {linux_repo_path}, {str(e)}")
    
    # 获取修复commit的提交信息，用于展示给用户
    fixed_commit_message = None
    if issue_info.fixed_commit:
        fixed_commit_message = get_commit_message(repo, issue_info.fixed_commit, linux_repo=linux_repo)
        if fixed_commit_message:
            logger.debug(f"修复commit的提交信息: {fixed_commit_message}")

    # 缺少 fixed_commit 时，直接报错退出
    if not issue_info.fixed_commit:
        logger.error("缺少修复commit，无法继续分支分析流程")
        raise RuntimeError(i18n("未能获取修复提交(fixed)，无法继续流程"))

    if not issue_info.introduced_commit:
        logger.warning("缺少引入commit，仅基于修复commit判断分支状态")
        fixed_branches = get_branches_containing_commit(
            repo,
            issue_info.fixed_commit,
            target_branches=branchList,
            linux_repo=linux_repo,
        )
        logger.info(f"包含修复commit的分支: {fixed_branches}")
        for branch in branchList:
            if branch in fixed_branches:
                item = {
                    i18n("补丁ID"): issue_info.cve_id,
                    i18n("目标分支"): branch,
                    i18n("是否受影响"): i18n("已修复"),
                    i18n("适配状态"): "",
                    i18n("冲突点"): i18n("已修复"),
                    i18n("建议调整文件"): "N/A",
                    i18n("是否存在冲突"): i18n("否"),
                }
            else:
                # 无法判断是否受影响时，仍进行补丁应用检查以给出适配状态
                patchs = check_cve_patch_apply_status(
                    fork_repo_url,
                    issue_info.cve_id,
                    gitee_token,
                    branch,
                    issue_info.fixed_commit,
                    clone_dir,
                    repo=repo,
                )
                logger.info(f"分支 {branch} 的补丁信息(无法判断是否受影响): {patchs}")
                # 仅取第一条结果作为状态依据
                patch = patchs[0] if patchs else {"status": "error", "patch_path": i18n("无法判断")}
                item = {
                    i18n("补丁ID"): issue_info.cve_id,
                    i18n("目标分支"): branch,
                    i18n("是否受影响"): i18n("无法判断"),
                    i18n("冲突点"): patch.get("patch_path", i18n("无法判断")),
                }
                if patch.get("status") == "success":
                    item[i18n("适配状态")] = i18n("成功")
                    item[i18n("建议调整文件")] = "N/A"
                    item[i18n("是否存在冲突")] = i18n("否")
                else:
                    item[i18n("适配状态")] = i18n("需要调整")
                    item[i18n("建议调整文件")] = ""
                    item[i18n("是否存在冲突")] = i18n("是")
            if fixed_commit_message:
                item[i18n("提交信息")] = fixed_commit_message
            items.append(item)
        return items
    
    # 只查询指定的分支，而不是所有分支
    vulnerable_branches = get_branches_containing_commit(repo, issue_info.introduced_commit, target_branches=branchList, linux_repo=linux_repo)
    logger.info(f"包含引入commit的分支: {vulnerable_branches}")

    # 对于包含引入commit的分支，检查是否包含修复commit
    analyse_fix_brancees = [branch for branch in vulnerable_branches if branch in branchList]
    fixed_branches = get_branches_containing_commit(repo, issue_info.fixed_commit, target_branches=analyse_fix_brancees, linux_repo=linux_repo)
    logger.info(f"包含修复commit的分支: {fixed_branches}")
    
    needs_patch_branches = [branch for branch in vulnerable_branches
                           if branch in branchList and branch not in fixed_branches]
    logger.info(f"需要补丁的分支: {needs_patch_branches}")
    
    # 只 fetch origin（后续只用到 origin/{branch}），失败时继续使用本地缓存
    try:
        logger.info(f"执行 git fetch origin（repo: {repo.working_dir}）")
        repo.git.fetch('origin')
    except Exception as e:
        logger.warning(f"git fetch origin 失败，继续使用本地缓存: {str(e)}")
    
    for branch in needs_patch_branches:
        remote_branch = f"origin/{branch}"
        try:
            # 清理工作区（仅当有改动时）
            _ensure_clean_worktree(repo)
        except Exception as e:
            logger.warning(f"重置工作区失败: {str(e)}")
        
        try:
            # 尝试切换到本地分支（如果存在）
            logger.info(f"执行 git checkout {branch}")
            repo.git.checkout(branch)
        except Exception:
            try:
                # 如果本地分支不存在，创建并切换到跟踪分支
                logger.info(f"执行 git checkout -b {branch} --track {remote_branch}")
                repo.git.checkout('-b', branch, '--track', remote_branch)
            except Exception as e:
                logger.error(f"创建并切换分支 {branch} 失败: {str(e)}")
                continue
            
        # 传递 repo 参数，避免重复调用 setup_repository
        patchs = check_cve_patch_apply_status(fork_repo_url, issue_info.cve_id, gitee_token, branch, issue_info.fixed_commit, clone_dir, repo=repo)
        logger.info(f"分支 {branch} 的补丁信息: {patchs}")
        
        for patch in patchs:
            item = {
                i18n("补丁ID"): issue_info.cve_id,
                i18n("目标分支"): branch,
                i18n("是否受影响"): i18n("受影响"),
                i18n("冲突点"): patch['patch_path'],
            }
            
            if patch['status'] == 'success':
                item[i18n("适配状态")] = i18n("成功")
                item[i18n("建议调整文件")] = "N/A"
                item[i18n("是否存在冲突")] = i18n("否")
            else:
                item[i18n("适配状态")] = i18n("需要调整")
                item[i18n("建议调整文件")] = ""
                item[i18n("是否存在冲突")] = i18n("是")
            
            # 添加commit message
            if fixed_commit_message:
                item[i18n("提交信息")] = fixed_commit_message
            
            items.append(item)
    
    fixed_in_branches = [branch for branch in branchList if branch in fixed_branches]
    for branch in fixed_in_branches:
        item = {
            i18n("补丁ID"): issue_info.cve_id,
            i18n("目标分支"): branch,
            i18n("是否受影响"): i18n("已修复"),
            i18n("适配状态"): "",
            i18n("冲突点"): i18n("已修复"),
            i18n("建议调整文件"): "N/A",
            i18n("是否存在冲突"): i18n("否"),
        }
        # 添加commit message
        if fixed_commit_message:
            item[i18n("提交信息")] = fixed_commit_message
        items.append(item)
    
    unaffected_branches = [branch for branch in branchList
                          if branch not in vulnerable_branches and branch not in fixed_branches]
    for branch in unaffected_branches:
        item = {
            i18n("补丁ID"): issue_info.cve_id,
            i18n("目标分支"): branch,
            i18n("是否受影响"): i18n("不受影响"),
            i18n("适配状态"): "",
            i18n("冲突点"): i18n("无"),
            i18n("建议调整文件"): "N/A",
            i18n("是否存在冲突"): i18n("否"),
        }
        # 添加commit message
        if fixed_commit_message:
            item[i18n("提交信息")] = fixed_commit_message
        items.append(item)
    
    return items


def check_analyse_cache_result(cve_id: str, branch: str)-> bool:
    """检查分支上的CVE是否已修复

    Args:
        cve_id: CVE id
        branch: 分支名
    """
    cache = load_cache(BRANCHES_ANALYSIS_CACHE)
    for key, value in cache.items():
        for item in value.get("data", []):
            cache_cve = item.get(i18n("补丁ID"))
            cache_branch = item.get(i18n("目标分支"))
            if cve_id == cache_cve and cache_branch == branch:
                cache_affected = item.get(i18n("是否受影响"))
                if cache_affected == i18n("不受影响") or \
                    cache_affected == i18n("已修复"):
                    return True
    return False
