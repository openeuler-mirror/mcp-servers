import git
import logging
import os
import re
import subprocess
from difflib import SequenceMatcher

from .gitee import setup_repository
from .patch import getUrlText, ensure_patch_file
from .commits import get_vulnerability_commits, branch_commit_from_upstream
from .locales import i18n
from .tools.project import safe_git_reset_hard
from .branches import check_analyse_cache_result

logger = logging.getLogger(__name__)


def _patch_is_mbox_format(patch_path: str) -> bool:
    """检测补丁文件是否为 git am 所需的 mbox 格式（首行为 'From ' 等邮件头）。"""
    try:
        with open(patch_path, "rb") as f:
            first_line = f.readline().decode("utf-8", errors="ignore").strip()
        return first_line.startswith("From ")
    except Exception:
        return False


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
            "https://mirrors.cernet.edu.cn/linux-stable.git",
            "https://mirrors.tuna.tsinghua.edu.cn/git/linux-stable.git",
            "https://mirrors.bfsu.edu.cn/git/linux-stable.git",
            "https://mirrors.cqu.edu.cn/git/linux-stable.git",
            "https://mirror.nju.edu.cn/git/linux-stable.git",
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
    # 处理 bugzilla_url 为 None 的情况，显示为空字符串
    bugzilla_value = bugzilla_url if bugzilla_url else ""
    header = f"""{subject}

{inclusion_type}
{from_line}
commit {commit_id}
category: bugfix
bugzilla: {bugzilla_value}
CVE: {cve_id}

Reference: {patch_url}

--------------------------------

{msg}"""
    return header, headers 


def generate_commit_message(cve_id, issue_url, repo_path, branch_commit):
    """生成commit信息"""
    logger.info(
        f"generate_commit_message: cve_id={cve_id}, issue_url={issue_url}, repo_path={repo_path}"
    )
    message, headers = generate_patch_header(
        branch_commit, cve_id, issue_url, repo_path=repo_path
    )
    logger.debug(
        "generate_commit_message: message_preview=%r",
        message[:200] if isinstance(message, str) else message,
    )
    return message, headers

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


def extract_commit_message_from_patch(patch_path: str):
    """
    从 patch 中提取原始 commit message（仅保留原提交标题与正文，不拼接额外头信息）。
    """
    if not patch_path or not os.path.exists(patch_path):
        raise ValueError(f"patch 文件不存在: {patch_path}")

    with open(patch_path, "r", encoding="utf-8", errors="ignore") as f:
        patch_content = f.read()
    lines = patch_content.splitlines()

    # 兼容 git show 风格补丁（以 "commit <sha>" 开头，正文每行常见 4 空格缩进）
    if lines and lines[0].startswith("commit "):
        message_lines = []
        idx = 1
        # 跳过 Author/Date/Merge 等头部直到正文块
        while idx < len(lines):
            line = lines[idx]
            if line.startswith("diff --git "):
                break
            if line.startswith("    ") or line.startswith("\t"):
                break
            idx += 1

        while idx < len(lines):
            line = lines[idx]
            if line.startswith("diff --git "):
                break
            if line.startswith("    "):
                message_lines.append(line[4:])
            elif line.startswith("\t"):
                message_lines.append(line[1:])
            else:
                # 遇到非缩进行通常意味着提交说明结束
                if line.strip():
                    break
                message_lines.append("")
            idx += 1

        # 规范化首尾空行
        while message_lines and not message_lines[0].strip():
            message_lines.pop(0)
        while message_lines and not message_lines[-1].strip():
            message_lines.pop()
        if not message_lines:
            raise ValueError(f"无法从 patch 提取提交说明: {patch_path}")
        return "\n".join(message_lines), {}

    headers, body = _parse_patch_headers_and_body(patch_content)

    subject = (headers.get("Subject") or "").strip()
    if subject:
        # 去除 [PATCH]、[PATCH v2]、[PATCH 1/3] 等前缀
        subject = re.sub(
            r"\s*\[(?=[^\]]*PATCH)[^\]]*\]\s*",
            " ",
            subject,
            flags=re.IGNORECASE,
        ).strip()

    msg_part = body
    split_indexes = []
    split_m1 = re.search(r"(?m)^---\s*$", msg_part)
    split_m2 = re.search(r"(?m)^diff --git ", msg_part)
    if split_m1:
        split_indexes.append(split_m1.start())
    if split_m2:
        split_indexes.append(split_m2.start())
    if split_indexes:
        msg_part = msg_part[: min(split_indexes)]
    msg_body = msg_part.strip()

    if not subject:
        for line in msg_body.splitlines():
            candidate = line.strip()
            if candidate:
                subject = candidate
                break
    if not subject:
        raise ValueError(f"无法从 patch 提取提交标题: {patch_path}")

    if msg_body:
        first_non_empty = ""
        for line in msg_body.splitlines():
            candidate = line.strip()
            if candidate:
                first_non_empty = candidate
                break
        if first_non_empty == subject:
            return msg_body, headers
        return f"{subject}\n\n{msg_body}", headers
    return subject, headers


def _extract_patch_modified_files(patch_path: str):
    """
    从 patch 文本中提取“实际修改的文件名”列表（去重且保序）。
    优先解析 `diff --git a/... b/...`，并用 `+++ b/...` 兜底。
    """
    files = []
    seen = set()
    try:
        with open(patch_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
                if m:
                    # 一般以 b/ 路径作为“补丁实际应用后的文件路径”
                    candidate = m.group(2).strip()
                    if candidate and candidate != "/dev/null" and candidate not in seen:
                        seen.add(candidate)
                        files.append(candidate)
                    continue

                m = re.match(r"^\+\+\+\s+b/(.+)$", line)
                if m:
                    candidate = m.group(1).strip()
                    if candidate and candidate != "/dev/null" and candidate not in seen:
                        seen.add(candidate)
                        files.append(candidate)
    except Exception as ex:
        logger.warning(
            "extract patch modified files failed, patch_path=%s, err=%s",
            patch_path,
            ex,
        )
    return files


def _extract_patch_file_pairs(patch_path: str):
    """
    从 patch 中按顺序提取文件对 (a_path, b_path)。
    主要用于在“原始补丁文件名”和“调整后补丁文件名”之间做位置映射。
    """
    pairs = []
    try:
        with open(patch_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
                if not m:
                    continue
                a_path = m.group(1).strip()
                b_path = m.group(2).strip()
                pairs.append((a_path, b_path))
    except Exception as ex:
        logger.warning(
            "extract patch file pairs failed, patch_path=%s, err=%s",
            patch_path,
            ex,
        )
    return pairs


def _map_original_conflict_to_adjusted_file(
    conflict_file: str,
    adjusted_file_pairs,
    adjusted_modified_files,
):
    """
    将原始补丁中的冲突文件，映射到“调整后补丁”中的实际修改文件。
    映射策略（从严到宽）：
    1) 精确路径命中（命中 adjusted 的 a_path/b_path）；
    2) basename 唯一命中；
    3) 路径相似度兜底（仅高相似度时采纳）。
    """
    if not conflict_file:
        return None

    conflict_file = conflict_file.strip()
    if not conflict_file:
        return None

    # 1) 精确路径命中：若冲突路径正好出现在调整后补丁的 a/b 路径中，直接取对应 b 路径。
    alias_to_target = {}
    for adj_a, adj_b in adjusted_file_pairs:
        if not adj_b or adj_b == "/dev/null":
            continue
        if adj_a and adj_a != "/dev/null":
            alias_to_target[adj_a] = adj_b
        alias_to_target[adj_b] = adj_b
    exact = alias_to_target.get(conflict_file)
    if exact:
        return exact

    # 2) basename 唯一命中
    conflict_base = os.path.basename(conflict_file)
    base_hits = [
        p for p in adjusted_modified_files
        if os.path.basename(p) == conflict_base
    ]
    if len(base_hits) == 1:
        return base_hits[0]

    # 3) 相似度兜底：避免误配，设置较高阈值
    best_path = None
    best_score = 0.0
    for candidate in adjusted_modified_files:
        full_ratio = SequenceMatcher(None, conflict_file, candidate).ratio()
        base_ratio = SequenceMatcher(
            None, conflict_base, os.path.basename(candidate)
        ).ratio()
        score = full_ratio * 0.7 + base_ratio * 0.3
        if score > best_score:
            best_score = score
            best_path = candidate
    if best_path and best_score >= 0.72:
        return best_path

    return None


def get_patch(branch_commit, clone_dir):
    """
    获取指定 commit 的 patch 文件路径。
    
    优先策略：
    1. 如果存在本地 linux 仓库（clone_dir/linux），使用 git format-patch 直接生成 patch；
    2. 如果本地生成失败或 linux 仓库不存在，则从 kernel.org 获取 patch 文本；
    3. 对从网络获取的内容做简单校验，避免将 HTML 重定向页面当成 patch 使用。
    """
    patch_path = os.path.abspath(
        os.path.join(clone_dir, f"commit_patch_{branch_commit}.patch")
    )
    # 统一复用 patch.ensure_patch_file 逻辑
    return ensure_patch_file(
        commit_hash=branch_commit,
        patch_path=patch_path,
        clone_dir=clone_dir,
    )


def get_conflict_file_message(cve_id, repo, clone_dir, branch_commit, adjusted_patch_path=None):
    # 原始补丁路径始终需要，用于 git apply --check 获取真实冲突信息。
    original_patch_path = get_patch(branch_commit, clone_dir)
    # 实际修改文件列表优先从“调整后的补丁”提取；未提供时回退原始补丁。
    patch_for_modified_files = adjusted_patch_path or original_patch_path
    patch_modified_files = _extract_patch_modified_files(patch_for_modified_files)
    adjusted_file_pairs = _extract_patch_file_pairs(patch_for_modified_files)
    logger.info(
        "get_conflict_file_message: start, cve_id=%s, branch_commit=%s, original_patch=%s, modified_files_patch=%s",
        cve_id,
        branch_commit,
        original_patch_path,
        patch_for_modified_files,
    )
    conflict_message = ""
    try:
        logger.info(
            "get_conflict_file_message: 执行 git apply --check %s (repo=%s)",
            original_patch_path,
            repo.working_dir,
        )
        res = repo.git.apply("--check", original_patch_path)
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
        seen_files = set()

        for raw_line in e.stderr.split('\n'):
            line = raw_line
            logger.debug("get_conflict_file_message: 处理 stderr 行: %r", line)
            line = line.strip()
            if not line:
                continue

            # 兼容 GitPython stderr 的包装格式，例如:
            # "stderr: 'error: drivers/net/can/usb/esd_usb.c: No such file or directory'"
            normalized = line
            if normalized.startswith("stderr:"):
                normalized = normalized[len("stderr:"):].strip()
            normalized = normalized.strip().strip("'").strip('"')

            # 统一提取路径: 支持英文/中文报错、文件不存在、以及 GitPython 的 stderr 包装行。
            # 这里用一组更宽松的模式，避免因引号或大小写差异漏掉冲突文件。
            patterns = [
                ("apply_conflict", r'error:\s+(.+?):\s+patch does not apply\b'),
                ("apply_conflict", r'错误[:：]\s*(.+?)[:：]\s*补丁未应用\b'),
                ("missing_file", r'error:\s+(.+?):\s+No such file or directory\b'),
                ("missing_file", r'error:\s+(.+?):\s+没有那个文件或目录\b'),
            ]

            conflict_file = None
            conflict_kind = None
            for kind, pattern in patterns:
                matched = re.search(pattern, normalized, flags=re.IGNORECASE)
                if matched:
                    conflict_file = matched.group(1).strip()
                    conflict_kind = kind
                    break

            if not conflict_file:
                logger.debug(
                    "get_conflict_file_message: 行未匹配到冲突文件模式，跳过: %r",
                    normalized,
                )
                continue
            logger.info(
                "get_conflict_file_message: 匹配到冲突/问题文件: %s",
                conflict_file,
            )
            if conflict_file in seen_files:
                continue
            seen_files.add(conflict_file)
            if conflict_message:
                conflict_message = f"{conflict_message}\n    {conflict_file}"
            else:
                conflict_message = f"\nConflicts:\n     {conflict_file}"

            # 文件不存在时，除了报错文件，还补充 patch 实际修改的文件名，便于定位路径差异问题。
            if conflict_kind == "missing_file":
                mapped_patch_file = _map_original_conflict_to_adjusted_file(
                    conflict_file,
                    adjusted_file_pairs,
                    patch_modified_files,
                )
                if mapped_patch_file and mapped_patch_file not in seen_files:
                    seen_files.add(mapped_patch_file)
                    conflict_message = f"{conflict_message}\n    {mapped_patch_file}"
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
        fork_repo_url: str = None,
        gitee_token: str = None,
        branch: str = None,
        clone_dir: str = None,
        patch_path: str = None,
        signer_name: str = None,
        signer_email: str = None,
        cve_id: str = None,
        issue_url: str = None,
        fix_branch: str = None,
        use_llm: bool = False,
        llm_provider: str = None,
        llm_base_url: str = None,
        llm_model_name: str = None,
        api_key: str = None,
        llm_confirm: bool = False,  # 新增：LLM 解决后是否需要人工确认
):
    """合并分支并且提交

    Args:
        fork_repo_url: git 仓库地址（可选，如果不提供则只做本地补丁应用，不推送）
        gitee_token: Gitee 访问令牌（可选，用于私有仓库认证）
        branch: 处理的分支
        clone_dir: 本地克隆目录
        patch_path: patch 文件路径
        signer_name: 签名者名称
        signer_email: 签名者邮箱
        cve_id: cve id
        issue_url: issue 链接（可选）
        fix_branch: 修复分支名称（可选，未指定时自动生成）
        use_llm: 是否使用 LLM 自动解决冲突
        llm_provider: LLM 提供商
        llm_base_url: LLM API 基础地址
        llm_model_name: LLM 模型名称
        api_key: LLM API 密钥
        llm_confirm: 是否在 LLM 解决冲突后需要人工确认（默认 False）

    Returns:
        patch 应用信息字典
    """
    if check_analyse_cache_result(cve_id, branch):
        return {
            "action": "apply_patch",
            "cve_id": cve_id,
            "error": i18n("分支: %s, CVE: %s 已修复或不受影响, 补丁应用失败") % (branch, cve_id)
        }
    linux_repo_path = os.path.join(clone_dir, 'linux')
    introduced_commit, fixed_commit = get_vulnerability_commits(
        cve_id,
        clone_dir=clone_dir,
    )
    logger.info(
        f"apply_patch: introduced_commit={introduced_commit}, fixed_commit={fixed_commit}"
    )
    if not fixed_commit:
        raise RuntimeError(i18n("未能获取修复提交(fixed)，无法继续流程"))
    branch_commit = branch_commit_from_upstream(fixed_commit, branch, clone_dir)
    if branch_commit:
        logger.info(
            "apply_patch: fixed_commit: %s, branch: %s, branch_commit: %s",
            fixed_commit,
            branch,
            branch_commit
            )
    else:
        branch_commit = fixed_commit

    logger.info(f"apply_patch: 生成 commit message，repo_path={linux_repo_path}")
    try:
        commit_msg, headers = generate_commit_message(
            cve_id,
            issue_url,
            repo_path=linux_repo_path,
            branch_commit=branch_commit,
        )
    except Exception as e:
        logger.error(f"生成commit信息失败: {str(e)}")
        return {
                "status": "error",
                "error": i18n("生成commit信息失败: %s") % (str(e))
            }
    # 解析fork URL获取组织名和仓库名（可选，仅用于推送）
    org_name = ""
    repo_name = ""
    if fork_repo_url:
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
    # 标记是否用户明确指定了 fix_branch
    fix_branch_specified = bool(fix_branch)
    # 如果未指定 fix_branch，则自动生成
    if not fix_branch:
        issue_num = os.path.basename(issue_url) if issue_url else cve_id
        fix_branch = f"fix-{branch}-{issue_num}"
    logger.info(f"修复分支名称: {fix_branch}{'（用户指定）' if fix_branch_specified else '（自动生成）'}")
    try:
        if branch in branches:
            logger.info(f"检出已存在分支: {branch}")
            repo.git.checkout(branch)
            # 尝试同步远程分支，失败时继续使用本地分支
            try:
                logger.info(f"同步远程分支: origin/{branch} (--rebase)")
                repo.git.pull("origin", branch, "--rebase")
            except Exception as pull_error:
                logger.warning(f"同步远程分支失败，继续使用本地分支: {str(pull_error)}")
        else:
            logger.info(f"本地不存在分支 {branch}，从 origin/{branch} 创建")
            repo.git.checkout('-b', branch, f'origin/{branch}')

        # 处理修复分支
        if fix_branch in branches:
            if fix_branch_specified:
                # 用户明确指定了 fix_branch，不删除，直接切换（累积提交模式）
                logger.info(f"修复分支已存在，切换到: {fix_branch}（累积提交模式）")
                repo.git.checkout(fix_branch)
            else:
                # 自动生成的 fix_branch，删除重建
                logger.info(f"删除已存在的修复分支: {fix_branch}")
                repo.git.branch('-D', fix_branch)
                logger.info(f"创建并切换到修复分支: {fix_branch}")
                repo.git.checkout('-b', fix_branch)
        else:
            # 分支不存在，创建新分支
            logger.info(f"创建并切换到修复分支: {fix_branch}")
            repo.git.checkout('-b', fix_branch)
    except Exception as e:
        logger.error(f"切换分支失败: {str(e)}")
        return {
                "status": "error",
                "error": i18n("切换分支失败: %s") % (str(e))
            }
    logger.info("apply_patch: 预检查补丁冲突文件（git apply --check）...")
    # 如果没有提供 patch_path，则自动获取
    if not patch_path:
        patch_path = get_patch(branch_commit, clone_dir)
        logger.info(f"apply_patch: 未提供 patch_path，自动获取: {patch_path}")
    
    try:
        conflict_message = get_conflict_file_message(
            cve_id,
            repo,
            clone_dir,
            branch_commit,
            adjusted_patch_path=patch_path,
        )
    except Exception as e:
        logger.warning(f"get conflict file message failed: {str(e)}")
        conflict_message = ""

    logger.info(f"apply_patch: 应用补丁文件，patch_path={patch_path}")
    try:
        # 有冲突说明时用 git apply；无冲突时仅当补丁为 mbox 格式才用 git am，否则用 git apply
        use_apply = bool(conflict_message) or not _patch_is_mbox_format(patch_path)
        if use_apply:
            repo.git.apply(patch_path)
            repo.git.add("--all")
            author = headers.get("From", f"{signer_name} <{signer_email}>")
            date = headers.get("Date")
            msg = f"{commit_msg}{conflict_message}" if conflict_message else commit_msg
            if date:
                repo.git.commit("-m", msg, f"--author={author}", f"--date={date}", "-s")
            else:
                repo.git.commit("-m", msg, f"--author={author}", "-s")
        else:
            repo.git.am(patch_path)
            repo.git.add("-u")
            repo.git.commit("--amend", "-m", commit_msg, "-s")
        logger.info("补丁成功应用")
    except git.exc.GitCommandError as e:
        logger.error(f"应用补丁失败: {str(e)}")

        # 检查是否处于 am 过程中的冲突状态
        if "Applying" in str(e):
            repo.git.am("--abort")

        # 尝试使用 LLM 自动解决冲突
        if use_llm and api_key:
            logger.info("尝试使用 LLM 自动解决冲突...")
            try:
                from .agent.conflict_resolver import resolve_patch_conflict

                # 读取补丁内容
                with open(patch_path, 'r', encoding='utf-8') as f:
                    patch_content = f.read()

                # 调用 LLM 解决冲突
                result = resolve_patch_conflict(
                    repo_path=repo.working_dir,
                    patch_content=patch_content,
                    target_branch=branch,
                    api_key=api_key,
                    provider=llm_provider or 'openai',
                    custom_base_url=llm_base_url,
                    custom_model_name=llm_model_name,
                    context={'cve_id': cve_id, 'issue_url': issue_url}
                )

                if result.success and result.patch_content:
                    logger.info("LLM 成功解决冲突，生成修复后的补丁...")

                    # 先保存修复后的补丁到文件（确认前保存，方便用户查看和调试）
                    import pathlib
                    original_patch_path = pathlib.Path(patch_path)
                    resolved_patch_filename = f"{original_patch_path.stem}_resolved{original_patch_path.suffix}"
                    resolved_patch_path = str(original_patch_path.parent / resolved_patch_filename)

                    with open(resolved_patch_path, 'w', encoding='utf-8') as f:
                        f.write(result.patch_content)

                    logger.info(f"修复后的补丁已保存到: {resolved_patch_path}")

                    # 分析补丁差异（无论是否需要确认都显示）
                    try:
                        from .patch_diff_analyzer import analyze_patch_differences, generate_difference_summary
                        diff_analysis = analyze_patch_differences(patch_content, result.patch_content)
                        diff_summary = generate_difference_summary(diff_analysis)
                    except Exception as analysis_error:
                        logger.warning(f"补丁差异分析失败：{analysis_error}")
                        diff_summary = "无法分析补丁差异"

                    # 显示补丁信息（无论是否需要确认）
                    logger.info("")
                    logger.info("="*80)
                    logger.info("【补丁修复信息】")
                    logger.info("="*80)
                    logger.info(f"原始补丁路径：{patch_path}")
                    logger.info(f"修复后补丁路径：{resolved_patch_path}")
                    logger.info("")
                    logger.info("【补丁变更摘要】")
                    logger.info(diff_summary)
                    logger.info("="*80)

                    # 非 debug 模式下额外用 print 输出到终端
                    # 通过检查是否有控制台处理器(StreamHandler)来判断是否为 debug 模式
                    root_logger = logging.getLogger()
                    has_console_handler = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers)
                    if not has_console_handler:
                        print("")
                        print("="*80)
                        print("【补丁修复信息】")
                        print("="*80)
                        print(f"原始补丁路径：{patch_path}")
                        print(f"修复后补丁路径：{resolved_patch_path}")
                        print("")
                        print("【补丁变更摘要】")
                        print(diff_summary)
                        print("="*80)

                    # 如果需要人工确认，则显示完整补丁并等待用户确认
                    if llm_confirm:
                        # 计算补丁行数，决定显示方式
                        patch_lines = result.patch_content.count('\n') + 1
                        max_display_lines = 50

                        if patch_lines <= max_display_lines:
                            # 短补丁：直接显示完整内容
                            if has_console_handler:
                                logger.info("\nLLM 生成的补丁内容如下，请确认是否应用：")
                                logger.info("-"*80)
                                print("\n" + result.patch_content)
                                logger.info("-"*80)
                            else:
                                print("\nLLM 生成的补丁内容如下，请确认是否应用：")
                                print("-"*80)
                                print(result.patch_content)
                                print("-"*80)
                        else:
                            # 长补丁：显示摘要
                            print(f"\n补丁较长（{patch_lines} 行），已保存到：{resolved_patch_path}")
                            print("请用编辑器查看完整内容")
                            print("-"*80)

                        while True:
                            response = input("\n是否应用此补丁？(y/n/e): ").strip().lower()
                            if response in ('y', 'yes'):
                                logger.info("用户确认应用补丁")
                                break
                            elif response in ('n', 'no'):
                                logger.info("用户拒绝应用补丁")
                                logger.info(f"补丁文件已保留: {resolved_patch_path}")
                                return {
                                    "status": "cancelled",
                                    "error": i18n("用户拒绝应用 LLM 生成的补丁"),
                                    "resolved_patch_path": resolved_patch_path
                                }
                            elif response in ('edit', 'e'):
                                # 允许用户编辑已保存的补丁文件
                                try:
                                    logger.info(f"\n编辑补丁文件：{resolved_patch_path}")

                                    # 使用默认编辑器打开
                                    editor = os.environ.get('EDITOR', 'vi')
                                    logger.info(f"正在使用 {editor} 编辑器打开补丁...")
                                    logger.info("提示：请保持 unified diff 格式（--- a/, +++ b/, @@ ... @@），不要修改文件头部")
                                    subprocess.run([editor, resolved_patch_path])

                                    with open(resolved_patch_path, 'r', encoding='utf-8') as f:
                                        edited_patch = f.read()

                                    # 验证编辑后的补丁是否包含必要的头部
                                    if not edited_patch.strip().startswith('---'):
                                        logger.error("错误：补丁缺少文件头部（--- a/...）")
                                        logger.error("请确保补丁以正确的 unified diff 格式开头")
                                        logger.warning("已放弃编辑，将重新显示补丁内容")
                                        continue  # 回到确认循环

                                    result.patch_content = edited_patch
                                    logger.info("补丁已编辑")

                                    # 在应用前先用 git apply --check 验证
                                    try:
                                        repo.git.apply('--check', resolved_patch_path)
                                        logger.info("补丁验证通过")
                                        # 重新显示编辑后的补丁，等待用户确认
                                        edited_patch_lines = edited_patch.count('\n') + 1
                                        if edited_patch_lines <= max_display_lines:
                                            if has_console_handler:
                                                logger.info("\n编辑后的补丁内容如下，请确认是否应用：")
                                                logger.info("-"*80)
                                                print("\n" + edited_patch)
                                                logger.info("-"*80)
                                            else:
                                                print("\n编辑后的补丁内容如下，请确认是否应用：")
                                                print("-"*80)
                                                print(edited_patch)
                                                print("-"*80)
                                        else:
                                            print(f"\n编辑后的补丁较长（{edited_patch_lines} 行），已保存到：{resolved_patch_path}")
                                            print("请用编辑器查看完整内容")
                                            print("-"*80)
                                        # 继续循环，等待用户再次确认
                                    except Exception as check_error:
                                        logger.error(f"补丁验证失败，无法应用：{str(check_error)}")
                                        logger.warning("请重新编辑或选择其他选项")
                                        continue  # 回到确认循环
                                except Exception as edit_error:
                                    logger.error(f"编辑补丁失败：{edit_error}")
                            else:
                                logger.info("无效输入，请输入 y/n/e")

                    logger.info("应用修复后的补丁...")

                    try:
                        # 应用修复后的补丁
                        repo.git.apply(resolved_patch_path)
                        repo.git.add("--all")
                        author = headers.get("From", f"{signer_name} <{signer_email}>")
                        date = headers.get("Date")
                        msg = f"{commit_msg}{conflict_message}" if conflict_message else commit_msg
                        if date:
                            repo.git.commit("-m", msg, f"--author={author}", f"--date={date}", "-s")
                        else:
                            repo.git.commit("-m", msg, f"--author={author}", "-s")
                        logger.info("修复后的补丁成功应用")
                        logger.info(f"原始补丁：{patch_path}")
                        logger.info(f"修复后补丁：{resolved_patch_path}")
                    except Exception as apply_error:
                        # 应用失败时保留补丁文件以便调试
                        logger.error(f"应用 LLM 修复的补丁失败: {apply_error}")
                        logger.error(f"补丁文件已保留: {resolved_patch_path}")
                        raise
                else:
                    logger.error(f"LLM 无法解决冲突: {result.error_message}")
                    return {
                        "status": "error",
                        "error": i18n("无法应用补丁，LLM 冲突解决失败: %s") % (result.error_message or str(e))
                    }
            except Exception as llm_error:
                logger.error(f"LLM 冲突解决过程出错: {str(llm_error)}")
                return {
                    "status": "error",
                    "error": i18n("无法应用补丁，LLM 冲突解决失败: %s") % (str(llm_error))
                }
        else:
            logger.info("已中止补丁应用过程")
            return {
                "status": "error",
                "error": i18n("无法应用补丁: %s") % (str(e))
            }

    logger.info("apply_patch: 提交变更到本地仓库...")
    # 添加所有变更并提交

    # 推送变更到远程仓库（仅当提供了 fork_repo_url 时）
    remote = None
    if fork_repo_url and org_name:
        remote = f"fork-{org_name}"
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
    else:
        logger.info("未提供 fork_repo_url，跳过推送步骤，补丁仅应用在本地仓库")

    return {
        "status": "success",
        "remote": remote,
        "branch": branch,
        "fix_branch": fix_branch,
        "repo_path": repo_path,
        "pushed": bool(fork_repo_url),
    }
