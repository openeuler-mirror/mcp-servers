import git
import logging
import os
import re
import subprocess

from .gitee import setup_repository
from .patch import getUrlText, ensure_patch_file
from .commits import get_vulnerability_commits
from .locales import i18n
from .tools.project import safe_git_reset_hard

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
    """获取提交的引用信息，如 mainline 版本或 stable 版本。

    这里做两件事：
    1. 确保 linux 仓库存在（不存在则尝试多源 clone）；
    2. 使用 `git name-rev` 解析出 tags/vX.Y[.Z][-rcN] 形式的 tag，并区分 stable / mainline。
       解析失败时，返回 ("unknown", False/True)，但绝不会抛出 None.group 之类的异常。
    """
    # 判断目录是否存在
    if not os.path.exists(repo_path):
        # 获取上一层目录
        parent_dir = os.path.dirname(repo_path)
        # 依次尝试多个源，直到 clone 成功
        for url in [
            "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git",
            "https://kernel.googlesource.com/pub/scm/linux/kernel/git/stable/linux.git",
            "https://gitee.com/mirrors/linux_old1.git",
        ]:
            try:
                subprocess.run(
                    ["git", "clone", url, repo_path],
                    check=True,
                    cwd=parent_dir,
                    capture_output=True,
                    text=True,
                )
                if os.path.exists(repo_path):
                    break
            except Exception as e:
                logger.warning(f"克隆 linux 仓库失败({url}): {e}")

        if not os.path.exists(repo_path):
            raise RuntimeError("linux仓库克隆失败: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git")

    repo = git.Repo(repo_path)
    try:
        repo.git.checkout("master")
        repo.git.pull("origin", "master", "--rebase")
    except Exception as e:
        # 更新失败不影响后续 name-rev，只记录日志
        logger.error(f"更新仓库失败: {e}")

    # 获取提交引用信息
    is_stable = True
    try:
        # name_rev 典型输出:
        #   "<hash> tags/v6.19-rc1~171^2~34"
        # 或者只有分支名等其他形式
        name_rev = repo.git.name_rev(commit_id)

        # 只关心 tags/ 开头的引用，并且截断到 ~ 或 ^ 之前，避免把偏移也算进版本号
        # 例如：tags/v6.19-rc1~171^2~34 -> v6.19-rc1
        tag_match = re.search(r"(?:^|\s)tags/(v[^\s~^]+)", name_rev)
        if not tag_match:
            # 没有 tag 信息，直接返回 unknown
            return "unknown", is_stable

        tag_name = tag_match.group(1)

        # 带 rc 的认为是 mainline inclusion，其它形如 vX.Y.Z 的认为是 stable inclusion
        if "-rc" in tag_name:
            is_stable = False
        else:
            # 简单校验一下版本号格式（允许 v5.10 或 v5.10.1）
            if re.match(r"v?\d+\.\d+(\.\d+)?", tag_name):
                is_stable = True
            else:
                # 格式怪异的 tag，当作 mainline 处理，避免误判
                is_stable = False

        return tag_name, is_stable
    except Exception as e:
        logger.error(f"获取提交引用失败: {e}")
        return "unknown", is_stable


def generate_patch_header(commit_id, cve_id, bugzilla_url, repo_path):
    """生成符合规范的补丁头
    
    逻辑调整：
    - 不再直接从 kernel.org commit 页面抓 HTML 解析 subject/msg（容易被反爬、且与 patch 获取逻辑重复）
    - 统一通过本地/网络获取的 patch 文件来解析 subject 和 commit message
    """
    logger.info(
        f"generate_patch_header: start, commit_id={commit_id}, cve_id={cve_id}, "
        f"bugzilla_url={bugzilla_url}, repo_path={repo_path}"
    )
    ref_version, is_stable = get_commit_reference(commit_id, repo_path)

    inclusion_type = "stable inclusion" if is_stable else "mainline inclusion"
    if ref_version == "unknown":
        from_line = f"from mainline" if not is_stable else f"from stable"
    else:
        from_line = f"from mainline-{ref_version}" if not is_stable else f"from stable-{ref_version}"
    if is_stable:
        patch_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={commit_id}"
    else:
        patch_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id={commit_id}"

    logger.info(
        f"generate_patch_header: ref_version={ref_version}, is_stable={is_stable}, "
        f"inclusion_type={'stable' if is_stable else 'mainline'}, patch_url={patch_url}"
    )

    subject = None
    msg = None

    # 统一通过 patch 文件解析 subject / msg，避免与其他地方的网络获取逻辑重复
    try:
        # repo_path 一般为 <clone_dir>/linux，这里用其上一级目录作为 clone_dir
        clone_dir = os.path.dirname(repo_path)
        patch_path = get_patch(commit_id, clone_dir)
        logger.info("generate_patch_header: local_patch_path=%s", patch_path)

        with open(patch_path, "r", encoding="utf-8", errors="ignore") as f:
            patch_content = f.read()

        headers, body = _parse_patch_headers_and_body(patch_content)

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

        # 2) commit message：从正文开头到 '---' 或 'diff --git' 之前
        # 注意：format-patch 的正文开头就是提交说明（可能含 Signed-off-by 等）
        msg_part = body
        # 截到分隔符之前
        cut = None
        m1 = re.search(r"(?m)^---\s*$", msg_part)
        m2 = re.search(r"(?m)^diff --git ", msg_part)
        candidates = [m.start() for m in (m1, m2) if m]
        if candidates:
            cut = min(candidates)
            msg_part = msg_part[:cut]

        msg = msg_part.strip()

        logger.debug("generate_patch_header: from_patch msg_preview=%r", msg[:200])
    except Exception as e2:
        logger.error(
            "generate_patch_header: 从 patch 解析 commit 信息失败: %s", e2
        )
        # 兜底：保证 subject / msg 至少是非 None 的字符串，避免后续再次出错
        if not subject:
            subject = f"Backport {commit_id}"
        if msg is None:
            msg = ""
        logger.info(
            "generate_patch_header: fallback subject=%r, msg_len=%s",
            subject,
            len(msg) if msg is not None else 0,
        )

    logger.info("generate_patch_header: final subject=%r", subject)
    header = f"""{subject}

{inclusion_type}
{from_line}
commit {commit_id}
category: bugfix
bugzilla: {bugzilla_url}
CVE: {cve_id}

Reference: {patch_url}

--------------------------------

{msg}
"""
    return header


def generate_commit_message(cve_id, issue_url, repo_path, clone_dir: str | None = None):
    """生成commit信息"""
    logger.info(
        f"generate_commit_message: cve_id={cve_id}, issue_url={issue_url}, repo_path={repo_path}"
    )
    introduced_commit, fixed_commit = get_vulnerability_commits(
        cve_id,
        clone_dir=clone_dir,
    )
    logger.info(
        f"generate_commit_message: introduced_commit={introduced_commit}, fixed_commit={fixed_commit}"
    )
    if not fixed_commit:
        raise RuntimeError(i18n("未能获取修复提交(fixed)，无法继续流程"))
    message = generate_patch_header(
        fixed_commit, cve_id, issue_url, repo_path=repo_path
    )
    logger.debug(
        "generate_commit_message: message_preview=%r",
        message[:200] if isinstance(message, str) else message,
    )
    return message

def _parse_patch_headers_and_body(patch_content: str):
    """
    解析 patch 的 header 和 body
    """
    # 处理 format-patch 的 mbox "From <sha> ..." 首行（不是 RFC822 header）
    lines = patch_content.splitlines()
    idx = 0
    if lines and lines[0].startswith("From ") and " Mon Sep " in lines[0]:
        idx = 1

    # 解析 header：直到遇到第一个空行
    headers = {}
    cur_key = None
    cur_val_parts = []

    def flush():
        nonlocal cur_key, cur_val_parts
        if cur_key is not None:
            # unfold：把 CRLF + WSP 替换成一个空格
            val = "\n".join(cur_val_parts)
            val = re.sub(r"\r?\n[ \t]+", " ", val).strip()
            headers[cur_key] = val
        cur_key = None
        cur_val_parts = []

    # 逐行读 header
    while idx < len(lines):
        line = lines[idx]
        idx += 1

        if not line.strip():  # 空行，header 结束
            flush()
            break

        if line[0] in (" ", "\t"):  # 续行
            if cur_key is not None:
                cur_val_parts.append(line)
            continue

        # 新 header
        flush()
        m = re.match(r"^([!-9;-~]+):\s*(.*)$", line)  # 粗略匹配 "Key: Value"
        if m:
            cur_key = m.group(1)
            cur_val_parts = [m.group(2)]
        else:
            # 不符合 header 形态，保守起见：当作 header 结束，退回到正文
            idx -= 1
            break

    body = "\n".join(lines[idx:]) if idx < len(lines) else ""
    return headers, body

def get_patch(fixed_commit, clone_dir):
    """
    获取指定 commit 的 patch 文件路径。
    
    优先策略：
    1. 如果存在本地 linux 仓库（clone_dir/linux），使用 git format-patch 直接生成 patch；
    2. 如果本地生成失败或 linux 仓库不存在，则从 kernel.org 获取 patch 文本；
    3. 对从网络获取的内容做简单校验，避免将 HTML 重定向页面当成 patch 使用。
    """
    patch_path = os.path.abspath(
        os.path.join(clone_dir, f"commit_patch_{fixed_commit}.patch")
    )
    # 统一复用 patch.ensure_patch_file 逻辑
    return ensure_patch_file(
        commit_hash=fixed_commit,
        patch_path=patch_path,
        clone_dir=clone_dir,
    )


def get_conflict_file_message(cve_id, repo, clone_dir):
    introduced_commit, fixed_commit = get_vulnerability_commits(
        cve_id,
        clone_dir=clone_dir,
    )
    if not fixed_commit:
        raise RuntimeError(i18n("未能获取修复提交(fixed)，无法继续流程"))
    patch_path = get_patch(fixed_commit, clone_dir)
    logger.info(
        "get_conflict_file_message: start, cve_id=%s, introduced_commit=%s, "
        "fixed_commit=%s, patch_path=%s",
        cve_id,
        introduced_commit,
        fixed_commit,
        patch_path,
    )
    conflict_message = ""
    try:
        logger.info(
            "get_conflict_file_message: 执行 git apply --check %s (repo=%s)",
            patch_path,
            repo.working_dir,
        )
        res = repo.git.apply("--check", patch_path)
        logger.info(
            "get_conflict_file_message: git apply --check 无冲突，返回=%r",
            res,
        )
    except git.exc.GitCommandError as e:
        error_info = e.stderr
        logger.warning(
            "get_conflict_file_message: git apply --check 失败，stderr 原文:\n%s",
            error_info,
        )
        for line in e.stderr.split('\n'):
            logger.debug("get_conflict_file_message: 处理 stderr 行: %r", line)
            line = line.strip()
            if not line:
                continue
            res = re.match(r'error: (.*): patch does not apply', line)
            if not res:
                res = re.match(r'错误：(.*)：补丁未应用', line)
            if not res:
                logger.debug(
                    "get_conflict_file_message: 行未匹配到冲突文件模式，跳过: %r",
                    line,
                )
                continue
            logger.info(
                "get_conflict_file_message: 匹配到冲突文件: %s",
                res.group(1),
            )
            if conflict_message:
                conflict_message = f"{conflict_message}\n    {res.group(1)}"
            else:
                conflict_message = f"\nConflicts:\n     {res.group(1)}"
    if conflict_message:
        conflict_message = f"{conflict_message}\n[ Context conflict ]"
        logger.info(
            "get_conflict_file_message: 最终生成 conflict_message:\n%s",
            conflict_message,
        )
    else:
        logger.info(
            "get_conflict_file_message: 未从 stderr 中解析出任何冲突文件, cve_id=%s",
            cve_id,
        )
    return conflict_message


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
    linux_repo_path = os.path.join(clone_dir, 'linux')
    logger.info(f"apply_patch: 生成 commit message，repo_path={linux_repo_path}")
    try:
        commit_msg = generate_commit_message(
            cve_id,
            issue_url,
            repo_path=linux_repo_path,
            clone_dir=clone_dir,
        )
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

    logger.info("apply_patch: 准备/更新本地仓库（setup_repository）...")
    repo, repo_path = setup_repository(fork_repo_url, gitee_token, clone_dir)
    logger.info(f"本地仓库已准备就绪，repo_path={repo_path}")
    try:
        logger.info(f"apply_patch: 配置 Git 签名信息，signer_name={signer_name}, signer_email={signer_email}")
        config_git_signer(signer_name, signer_email, repo_path)
    except Exception as e:
        logger.error(f"配置用户信息失败: {str(e)}")
        return {
                "status": "error",
                "error": i18n("配置用户信息失败: %s") % (str(e))
            }
    
    # 清理工作区，确保没有未提交的文件导致后续操作失败
    try:
        logger.info("清理工作区，重置所有更改...")
        # 重置所有更改（使用安全函数处理锁文件问题）
        safe_git_reset_hard(repo)
        # 清理未跟踪的文件和目录
        repo.git.clean('-fdx')
        logger.info("工作区清理完成")
    except Exception as e:
        logger.warning(f"清理工作区时出现警告（可能工作区已经是干净的）: {str(e)}")
        # 清理工作区失败不应该阻止后续操作，只记录警告
    
    logger.info("apply_patch: 准备分支信息并创建修复分支...")
    branches = repo.git.branch().split()
    issue_num = os.path.basename(issue_url)
    fix_branch = f"fix-{branch}-{issue_num}"
    try:
        if branch in branches:
            logger.info(f"检出已存在分支: {branch}")
            repo.git.checkout(branch)
        else:
            logger.info(f"本地不存在分支 {branch}，从 origin/{branch} 创建")
            repo.git.checkout('-b', branch, f'origin/{branch}')
        logger.info(f"同步远程分支: origin/{branch} (--rebase)")
        repo.git.pull("origin", branch, "--rebase")
        if fix_branch in branches:
            logger.info(f"删除已存在的修复分支: {fix_branch}")
            repo.git.branch('-D', fix_branch)
        logger.info(f"创建并切换到修复分支: {fix_branch}")
        repo.git.checkout('-b', fix_branch)
    except Exception as e:
        logger.error(f"切换分支失败: {str(e)}")
        return {
                "status": "error",
                "error": i18n("切换分支失败: %s") % (str(e))
            }
    logger.info("apply_patch: 预检查补丁冲突文件（git apply --check）...")
    try:
        conflict_message = get_conflict_file_message(cve_id, repo, clone_dir)
    except Exception as e:
        logger.warning(f"get conflict file message failed: {str(e)}")
        conflict_message = ""

    logger.info(f"apply_patch: 应用补丁文件，patch_path={patch_path}")
    try:
        # 执行 git apply patch_path
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

    logger.info("apply_patch: 提交变更到本地仓库...")
    # 添加所有变更并提交
    repo.git.add("--all")
    repo.git.commit("-m", f"{commit_msg}{conflict_message}", "-s", f"--author={signer_name} <{signer_email}>")

    remote = f"fork-{org_name}"
    # 推送变更到远程仓库
    repo_remote = None
    for repo_remote in repo.remotes:
        if repo_remote.name == remote:
            break
    if not repo_remote:
        logger.info(f"apply_patch: 未找到远程 {remote}，创建新的远程指向 {fork_repo_url}")
        repo_remote = repo.create_remote(remote, fork_repo_url)
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
