import git
import logging
import os
import re
import subprocess

from .gitee import setup_repository
from .patch import getUrlText
from .commits import get_vulnerability_commits
from .locales import i18n

logger = logging.getLogger(__name__)

def config_git_signer(signer_name, signer_email, repo_path):
    subprocess.run(
        ["git", "config", "--global", "user.name", signer_name],
        check=True,
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    subprocess.run(
        ["git", "config", "--global", "user.email", signer_email],
        check=True,
        cwd=repo_path,
        capture_output=True,
        text=True
    )

def get_commit_reference(commit_id, repo_path):
    # 判断目录是否存在
    if not os.path.exists(repo_path):
        # 获取上一层目录
        parent_dir = os.path.dirname(repo_path)
        result = subprocess.run(
            ["git", "clone", "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git", repo_path],
            check=True,
            cwd=parent_dir,
            capture_output=True,
            text=True
        )
        if not os.path.exists(repo_path):
            result = subprocess.run(
                ["git", "clone", "https://kernel.googlesource.com/pub/scm/linux/kernel/git/stable/linux.git", repo_path],
                check=True,
                cwd=parent_dir,
                capture_output=True,
                text=True
            )
        if not os.path.exists(repo_path):
            result = subprocess.run(
                ["git", "clone", "https://gitee.com/mirrors/linux_old1.git", repo_path],
                check=True,
                cwd=parent_dir,
                capture_output=True,
                text=True
            )
        if not os.path.exists(repo_path):
            raise RuntimeError("linux仓库克隆失败: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git")

    repo = git.Repo(repo_path)
    try:
        repo.git.checkout('master')
        repo.git.pull("origin", "master", "--rebase")
    except Exception as e:
        logger.error(f"更新仓库失败: {e}")
    """获取提交的引用信息，如mainline版本或stable版本"""
    is_stable = True
    try:
        name_rev = repo.git.name_rev(commit_id)
        # 不带rc版本号的tag为stable版本
        if '-rc' in name_rev:
            is_stable = False
        # 解析name_rev输出，格式通常为: <commit-hash> tags/<tag-name>~<number>
        match = re.search(r'tags/([^~]+)', name_rev)
        if match:
            tag_name = match.group(1)
            return tag_name, is_stable
        return "unknown", is_stable
    except Exception as e:
        logger.error(f"获取提交引用失败: {e}")
        return "unknown", is_stable


def generate_patch_header(commit_id, cve_id, bugzilla_url, patch_url, repo_path):
    """生成符合规范的补丁头"""
    ref_version, is_stable = get_commit_reference(commit_id, repo_path)

    inclusion_type = "stable inclusion" if is_stable else "mainline inclusion"
    if ref_version == "unknown":
        from_line = f"from mainline" if not is_stable else f"from stable"
    else:
        from_line = f"from mainline-{ref_version}" if not is_stable else f"from stable-{ref_version}"

    commit_text = getUrlText(patch_url)
    pattern = re.compile(r"<div class='commit-subject'>(.+?)</div>", re.S)
    subject = re.search(pattern, commit_text).group(1)
    pattern = re.compile(r"<div class='commit-msg'>(.+?)</div>", re.S)
    msg = re.search(pattern, commit_text).group(1)
    msg = msg.replace('&lt;', '<').replace('&gt;', '>')

    header = f"""{subject}

{inclusion_type}
{from_line}
commit id: {commit_id}
bugzilla: {bugzilla_url}
CVE: {cve_id}

Reference: {patch_url}

-------------------

{msg}
"""
    return header


def generate_commit_message(cve_id, issue_url, repo_path):
    """生成commit信息"""
    introduced_commit, fixed_commit = get_vulnerability_commits(cve_id)
    patch_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={fixed_commit}"
    message = generate_patch_header(fixed_commit, cve_id, issue_url, patch_url, repo_path=repo_path)

    return message


def apply_patch(
        fork_repo_url: str,
        gitee_token: str,
        branch: str,
        clone_dir: str,
        patch_path: str,
        signer_name: str,
        signer_email: str,
        cve_id: str,
        issue_url: str,
):
    """合并分支并且提交

    Args:
        fork_repo_url: git仓库地址
        gitee_token: Gitee访问令牌(必须有仓库写入权限)
        branch: 处理的分支
        clone_dir: 本地克隆目录
        patch_path: patch文件路径
        signer_name: 签名者名称
        signer_email: 签名者邮箱
        cve_id: cve id
        issue_url: issue链接

    Returns:
        patch应用信息字典
    """
    try:
        commit_msg = generate_commit_message(cve_id, issue_url, repo_path=os.path.join(clone_dir, 'linux'))
    except Exception as e:
        logger.error(f"生成commit信息失败: {str(e)}")
        return {
                "status": "error",
                "error": i18n("生成commit信息失败: %s") % (str(e))
            }
    # 解析fork URL获取组织名和仓库名
    parts = fork_repo_url.strip().rstrip('/').split('/')
    org_name = parts[-2]
    repo_name = parts[-1].replace('.git', '')

    repo, repo_path = setup_repository(fork_repo_url, gitee_token, clone_dir)
    try:
        config_git_signer(signer_name, signer_email, repo_path)
    except Exception as e:
        logger.error(f"配置用户信息失败: {str(e)}")
        return {
                "status": "error",
                "error": i18n("配置用户信息失败: %s") % (str(e))
            }
    branches = repo.git.branch().split()
    issue_num = os.path.basename(issue_url)
    fix_branch = f"fix-{branch}-{issue_num}"
    try:
        if branch in branches:
            repo.git.checkout(branch)
        else:
            repo.git.checkout('-b', branch, f'origin/{branch}')
        repo.git.pull("origin", branch, "--rebase")
        if fix_branch in branches:
            repo.git.branch('-D', fix_branch)
        repo.git.checkout('-b', fix_branch)
    except Exception as e:
        logger.error(f"切换分支失败: {str(e)}")
        return {
                "status": "error",
                "error": i18n("切换分支失败: %s") % (str(e))
            }
    try:
        # 执行 git am patch_path
        repo.git.apply(patch_path)
        logger.info("补丁成功应用")
    except git.exc.GitCommandError as e:
        logger.error(f"应用补丁失败: {str(e)}")

        # 检查是否处于 am 过程中的冲突状态
        if "Applying" in str(e):
            repo.git.am("--abort")
            return {
                "status": "error",
                "error": i18n("无法完成补丁应用，请检查冲突并重试: %s") % (str(e))
            }
        else:
            logger.info("已中止补丁应用过程")
            return {
                "status": "error",
                "error": i18n("无法应用补丁: %s") % (str(e))
            }

    # 添加所有变更并提交
    repo.git.add("--all")
    repo.git.commit("-m", commit_msg, "-s", f"--author={signer_name} <{signer_email}>")

    remote = f"fork-{org_name}"
    # 推送变更到远程仓库
    repo_remote = None
    for repo_remote in repo.remotes:
        if repo_remote.name == remote:
            break
    if not repo_remote:
        repo_remote = repo.create_remote(remote, fork_url)
    try:
        logger.info(f"开始推送变更到远程仓库: {repo_remote.url}")
        repo.git.push(remote, fix_branch)
        logger.info("变更推送成功")
    except Exception as e:
        try:
            repo.git.push(f"{remote} --set-upstream", fix_branch)
        except Exception as e:
            try:
                repo.git.push(remote, fix_branch, "--force")
            except Exception as e:
                logger.error(f"推送变更失败: {str(e)}")
                return {
                    "status": "error",
                    "error": i18n("无法推送变更: %s") % (str(e))
                }

    return {
        "status": "success",
        "remote": remote,
        "branch": branch,
        "fix_branch": fix_branch,
        "repo_path": repo_path,
    }
