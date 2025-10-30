import git
import logging
import subprocess
import re
import json
import os

from .patch import getUrlText
from .commits import get_vulnerability_commits
from .locales import i18n

logger = logging.getLogger(__name__)


def generate_pr_body(cve_id, issue_url):
    """读取标题和内容"""
    introduced_commit, fixed_commit = get_vulnerability_commits(cve_id)

    commit_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={fixed_commit}"
    commit_text = getUrlText(commit_url)
    pattern = re.compile(r"<div class='commit-subject'>(.+?)</div>", re.S)
    subject = re.search(pattern, commit_text).group(1)
    result = f"""{subject}

{issue_url}
"""
    return result


def create_pr(
    cve_id: str,
    issue_url: str,
    gitee_token: str,
    fork_repo_url: str,
    repo_url: str,
    branch: str,
    clone_dir: str
    ):
    """创建PR
    Args:
        cve_id: cve id
        issue_url: issue链接
        gitee_token: Gitee访问令牌(必须有仓库写入权限)
        fork_repo_url: fork仓库地址
        repo_url: 提交PR仓库目标地址
        branch: 处理的分支
        clone_dir: 本地克隆目录

    Returns:
        PR创建结果字典
    """
    # 解析repo URL获取组织名和仓库名
    parts = fork_repo_url.strip().rstrip('/').split('/')
    head_org_name = parts[-2]
    head_repo_name = parts[-1].replace('.git', '')
    parts = repo_url.strip().rstrip('/').split('/')
    base_org_name = parts[-2]
    base_repo_name = parts[-1].replace('.git', '')
    title = f"Fix {cve_id}"
    body = generate_pr_body(cve_id, issue_url)
    issue_num = os.path.basename(issue_url)
    fix_branch = f"fix-{branch}-{issue_num}"

    try:
        subprocess.run(
            ['oegitext', 'config', '-token', gitee_token],
            check=True,
            cwd=clone_dir,
            capture_output=True,
            text=True
        )
    except Exception as e:
        logger.error(f"oegitext配置token失败: {str(e)}")
        return {
            "status": "error",
            "error": i18n("oegitext配置token失败: %s, stderr: %s") % (str(e), str(e.stderr))
        }

    cmd = [
        'oegitext', 'pull', '-cmd', 'create', '-user', base_org_name, '-repo', base_repo_name,
        '-title', title, '-head', f'{head_org_name}/{head_repo_name}:{fix_branch}', '-base', f'{branch}',
        '-body', body, '-show'
        ]

    try:
        result = subprocess.run(
                cmd,
                check=True,
                cwd=clone_dir,
                capture_output=True,
                text=True
            )
    except Exception as e:
        logger.error(f"提交pr失败: {str(e)}")
        return {
            "status": "error",
            "error": i18n("提交pr失败: %s, stderr: %s") % (str(e), str(e.stderr))
        }
    result = json.loads(result.stdout)

    return {
        "status": "success",
        "pr_html_url": result['html_url'],
    }
