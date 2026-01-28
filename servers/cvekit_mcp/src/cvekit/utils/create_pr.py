import git
import logging
import subprocess
import re
import json
import os

from .patch import getUrlText
from .commits import get_vulnerability_commits
from .locales import i18n
from .apply_patch import get_patch
from .apply_patch import _parse_patch_headers_and_body
from .branches import check_analyse_cache_result

logger = logging.getLogger(__name__)


def generate_pr_body(cve_id, issue_url, clone_dir: str):
    """读取 PR 标题和内容。

    优先从 kernel.org 提交页面解析 commit-subject；
    若网络不可用或页面结构变化，则回退到本地 patch 文件中解析 Subject 行，
    避免出现 NoneType.group 这类错误。
    """
    introduced_commit, fixed_commit = get_vulnerability_commits(
        cve_id,
        clone_dir=clone_dir,
    )
    if not fixed_commit:
        raise RuntimeError(i18n("未能获取修复提交(fixed)，无法继续流程"))

    subject = None

    # 1. 优先从 kernel.org 网页获取 subject
    commit_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={fixed_commit}"
    try:
        commit_text = getUrlText(commit_url)
        # 兼容单引号 / 双引号
        subject_pattern = re.compile(r"<div class=['\"]commit-subject['\"]>(.+?)</div>", re.S)
        subject_match = re.search(subject_pattern, commit_text)
        if not subject_match:
            raise RuntimeError("网页中未找到 commit-subject")
        subject = subject_match.group(1).strip()
    except Exception as e:
        logger.warning("从网页获取 PR 标题失败(%s)，尝试从本地 patch 解析", e)
        # 2. 当网页不可用或解析失败时，回退到本地 patch
        try:
            patch_path = get_patch(fixed_commit, clone_dir)
            with open(patch_path, "r", encoding="utf-8", errors="ignore") as f:
                patch_content = f.read()

            headers, _ = _parse_patch_headers_and_body(patch_content)

            # 1) Subject（已 unfold）
            subject = headers.get("Subject", "")
            if subject:
                # 去除 [PATCH]、[PATCH v2]、[PATCH 1/3] 等
                subject = re.sub(
                    r"\s*\[(?=[^\]]*PATCH)[^\]]*\]\s*",
                    " ",
                    subject,
                    flags=re.IGNORECASE,
                ).strip()

            logger.info(
                "generate_patch_header: from_patch subject_found=%s, subject=%r",
                bool(subject),
                subject,
            )
        except Exception as e2:
            logger.error("从本地 patch 解析 PR 标题失败: %s", e2)

    # 3. 兜底：确保 subject 至少是一个合理的默认值
    if not subject:
        subject = f"Fix {cve_id}"

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
    if check_analyse_cache_result(cve_id, branch):
        return {
            "action": "create_pr",
            "cve_id": cve_id,
            "error": i18n("分支: %s, CVE: %s 已修复或不受影响, 创建PR失败") % (branch, cve_id)
        }
    # 解析repo URL获取组织名和仓库名
    parts = fork_repo_url.strip().rstrip('/').split('/')
    head_org_name = parts[-2]
    head_repo_name = parts[-1].replace('.git', '')
    parts = repo_url.strip().rstrip('/').split('/')
    base_org_name = parts[-2]
    base_repo_name = parts[-1].replace('.git', '')
    title = f"Fix {cve_id}"
    body = generate_pr_body(cve_id, issue_url, clone_dir)
    issue_num = os.path.basename(issue_url)
    fix_branch = f"fix-{branch}-{issue_num}"


    repo_path = os.path.join(clone_dir, "kernel")
    repo = git.Repo(repo_path)
    temp_remote_name = fix_branch
    try:
        fork_repo_with_token = fork_repo_url.replace(
            "https://", 
            f"https://oauth2:{gitee_token}@"
        )

        if temp_remote_name in repo.remotes:
            repo.delete_remote(temp_remote_name)
        temp_remote = repo.create_remote(temp_remote_name, url=fork_repo_with_token)

        push_result = temp_remote.push(refspec=fix_branch, force=False)

        for info in push_result:
            if info.flags & git.PushInfo.ERROR:
                raise git.GitCommandError(
                    command="git push",
                    status=f"推送失败，远程返回错误：{info.summary}"
                )

        logger.info(f"分支 {fix_branch} 已成功推送到远程 fork 仓库：{fork_repo_url}")

    except git.GitCommandError as e:
        logger.error(f"推送分支到远程 fork 仓库失败：{str(e)}")
        # 提取 Git 命令的 stderr 信息（GitPython 错误对象的 stderr 属性）
        stderr_info = e.stderr if hasattr(e, 'stderr') else "未获取到详细错误信息"
        return {
            "status": "error",
            "error": i18n("推送分支到远程 fork 仓库失败：%s，stderr：%s") % (str(e), stderr_info)
        }
    except Exception as e:
        logger.error(f"推送分支时发生未知错误：{str(e)}")
        return {
            "status": "error",
            "error": i18n("推送分支时发生未知错误：%s") % str(e)
        }
    # =====================================================================================
    if fork_repo_url.startswith('https://gitee.com'):
        api_type = 'gitee'
    else:
        api_type = 'gitcode'

    try:
        subprocess.run(
            ['oegitext', 'config', '-token', gitee_token, '-api-type', api_type],
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
    html_url = result.get('html_url', '')
    if not html_url:
        html_url = result.get('web_url', '')

    # PR 创建成功后，清理临时 remote，避免远程过多、泄露 token
    try:
        if temp_remote_name in repo.remotes:
            repo.delete_remote(temp_remote_name)
            logger.info(f"已删除临时 remote: {temp_remote_name}")
    except Exception as e:
        logger.warning(f"删除临时 remote 失败: {str(e)}")

    return {
        "status": "success",
        "pr_html_url": html_url,
    }
