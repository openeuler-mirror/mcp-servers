import os
import re
from queue import Queue
from typing import List, Optional, Dict, Any

from flask import jsonify

from config import (
    logger,
    DEFAULT_BACKPORT_ENGINE,
)

# 简单的单机消息队列：任务队列 & 结果队列
TASK_QUEUE: "Queue[Dict[str, Any]]" = Queue()
RESULT_QUEUE: "Queue[Dict[str, Any]]" = Queue()

def extract_cve_id(text: str) -> Optional[str]:
    """
    从给定字符串中解析 CVE-ID，匹配形如 "CVE-2025-38051" 的模式。

    解析结果：
      - 找到第一个符合 "CVE-YYYY-NNNNN" 模式的子串，返回其大写形式
      - 未找到则返回 None
    """
    if not text:
        return None

    # 匹配 CVE-2025-38051 这类格式（年份 4 位 + 后面至少 1 位数字）
    m = re.search(r"cve-\d{4}-\d{1,}", text, flags=re.IGNORECASE)
    if not m:
        return None

    cve_id = m.group(0).upper()
    return cve_id

def _format_branches_table(cve_id: str, items: List[Dict[str, Any]]) -> str:
    """
    将分支分析结果格式化为 Markdown 表格评论内容。
    """
    if not items:
        return f"已完成 CVE 修复服务，但暂未找到分支分析结果，CVE-ID: {cve_id}。\nprovided by DevStation."

    def norm(item: Dict[str, Any]) -> Dict[str, Any]:
        """
        归一化一条分支记录的字段名：
          - 先构造一个大小写不敏感、空格/下划线不敏感的 key 映射，
          - 然后用一组“规范 key”去查找。

        这样无论是：
          - target_branch / Target branch / Target Branch / TARGET_BRANCH
          - Whether affected / whether_affected
        等，都可以统一映射到同一字段。
        """

        # 构造一个简化 key 的映射：原始、lower、lower+去空格/替换下划线
        canon: Dict[str, Any] = {}
        for k, v in item.items():
            if not isinstance(k, str):
                continue
            canon[k] = v
            lk = k.strip().lower()
            canon.setdefault(lk, v)
            lk2 = lk.replace(" ", "_")
            canon.setdefault(lk2, v)

        def pick(*names: str) -> str:
            for name in names:
                if not name:
                    continue
                # 先直接用传入 key，再用 lower / lower+下划线 形式
                candidates = {
                    name,
                    name.strip().lower(),
                    name.strip().lower().replace(" ", "_"),
                }
                for c in candidates:
                    if c in canon and canon[c] not in (None, ""):
                        return str(canon[c])
            return ""

        branch = pick("target_branch", "branch", "目标分支", "分支")
        affected = pick("weather_affected", "whether_affected", "whether affected", "是否受影响")
        adjust = pick("adjust_status", "adaptation_status", "适配状态", "adjust")
        conflicts_exist = pick("conflicts_exist", "whether conflicts exist", "是否存在冲突")
        commit_msg = pick("commit message", "commit_message", "提交信息")

        return {
            "branch": branch,
            "affected": affected,
            "adjust": adjust,
            "conflicts_exist": conflicts_exist,
            "commit_msg": commit_msg,
        }

    normed = [norm(x) for x in items]

    # 取第一个非空的提交信息
    commit_msg = ""
    for n in normed:
        if n["commit_msg"]:
            commit_msg = n["commit_msg"]
            break

    lines = []
    lines.append(f"已完成 CVE 修复分支分析，CVE-ID: **{cve_id}**。")
    if commit_msg:
        lines.append(f"\n关联修复提交信息：`{commit_msg}`\n")
    else:
        lines.append("")

    # 表头（仅分支分析信息，不再依赖缓存中的 PR 结果）
    lines.append("| 目标分支 | 是否受影响 | 适配状态 | 是否存在冲突 |")
    lines.append("| -------- | ---------- | -------- | ------------ |")

    for n in normed:
        branch = n["branch"] or "-"
        affected = n["affected"] or "-"
        adjust = n["adjust"] or "-"
        conflicts_exist = n["conflicts_exist"] or "-"

        lines.append(
            f"| {branch} | {affected} | {adjust} | {conflicts_exist} |"
        )

    lines.append("\nprovided by DevStation.")
    return "\n".join(lines)


def _format_final_summary_table(
    cve_id: str,
    items: List[Dict[str, Any]],
    pr_map: Dict[str, str],
) -> str:
    """
    基于分支分析结果 + PR 信息，生成最终的汇总 Markdown 表格。
    列包括：目标分支、是否受影响、适配状态、是否存在冲突、PR 链接。
    """
    # 如无分支分析结果，仅基于 PR 信息给出简单表格
    if not items:
        if not pr_map:
            return (
                f"已完成 CVE 修复全流程，但未获取到分支分析或 PR 信息，CVE-ID: {cve_id}。\n"
                f"provided by DevStation."
            )
        lines = []
        lines.append(f"已完成 CVE 修复全流程，CVE-ID: **{cve_id}**。")
        lines.append("")
        lines.append("| 目标分支 | PR 链接 |")
        lines.append("| -------- | ------- |")
        for branch in sorted(pr_map.keys()):
            val = pr_map[branch]
            val_str = str(val) if val is not None else ""
            if re.match(r"^https?://", val_str):
                pr_display = f"[查看PR]({val_str})"
            elif val_str:
                # 非 URL 文本（例如错误原因），直接展示在 PR 列
                pr_display = f"`{val_str}`"
            else:
                pr_display = "-"
            lines.append(f"| {branch} | {pr_display} |")
        lines.append("\nprovided by DevStation.")
        return "\n".join(lines)

    def norm(item: Dict[str, Any]) -> Dict[str, Any]:
        """
        同 _format_branches_table 中的 norm：对一条分支记录做大小写/空格无关的字段归一化。
        """

        canon: Dict[str, Any] = {}
        for k, v in item.items():
            if not isinstance(k, str):
                continue
            canon[k] = v
            lk = k.strip().lower()
            canon.setdefault(lk, v)
            lk2 = lk.replace(" ", "_")
            canon.setdefault(lk2, v)

        def pick(*names: str) -> str:
            for name in names:
                if not name:
                    continue
                candidates = {
                    name,
                    name.strip().lower(),
                    name.strip().lower().replace(" ", "_"),
                }
                for c in candidates:
                    if c in canon and canon[c] not in (None, ""):
                        return str(canon[c])
            return ""

        branch = pick("target_branch", "branch", "目标分支", "分支")
        affected = pick("weather_affected", "whether_affected", "whether affected", "是否受影响")
        adjust = pick("adjust_status", "adaptation_status", "适配状态", "adjust")
        conflicts_exist = pick("conflicts_exist", "whether conflicts exist", "是否存在冲突")
        commit_msg = pick("commit message", "commit_message", "提交信息")
        diff_file = pick("diff file", "diff_file", "差异文件")

        return {
            "branch": branch,
            "affected": affected,
            "adjust": adjust,
            "conflicts_exist": conflicts_exist,
            "commit_msg": commit_msg,
            "diff_file": diff_file,
        }

    normed = [norm(x) for x in items]

    # 取第一个非空的提交信息
    commit_msg = ""
    for n in normed:
        if n["commit_msg"]:
            commit_msg = n["commit_msg"]
            break

    lines: List[str] = []
    lines.append(f"已完成 CVE 修复全流程汇总，CVE-ID: **{cve_id}**。")
    if commit_msg:
        lines.append(f"\n关联修复提交信息：`{commit_msg}`\n")
    else:
        lines.append("")

    # 带 PR 列的最终表格
    lines.append("| 目标分支 | 是否受影响 | 适配状态 | 是否存在冲突 | PR 链接 |")
    lines.append("| -------- | ---------- | -------- | ------------ | ------- |")

    for n in normed:
        branch = n["branch"] or "-"
        affected = n["affected"] or "-"
        adjust = n["adjust"] or "-"
        conflicts_exist = n["conflicts_exist"] or "-"

        pr_val = pr_map.get(branch) or ""
        pr_str = str(pr_val) if pr_val is not None else ""
        if re.match(r"^https?://", pr_str):
            pr_display = f"[查看PR]({pr_str})"
        elif pr_str:
            # 非 URL 文本（例如错误原因），直接展示在 PR 列
            pr_display = f"`{pr_str}`"
        else:
            pr_display = "-"

        lines.append(
            f"| {branch} | {affected} | {adjust} | {conflicts_exist} | {pr_display} |"
        )

    lines.append("\nprovided by DevStation.")
    return "\n".join(lines)


def _extract_prs_from_final_artifact(artifact: Dict[str, Any]) -> Dict[str, str]:
    """
    从 final_result 的 artifact 文本中尽力提取 {branch: pr_url} 映射。

    目前 agent 的输出格式类似：
      1. **OLK-6.6 Branch**
         - ℹ️ PR already exists: [PR #31](https://.../pulls/31)
    """
    text = ""
    for part in artifact.get("parts") or []:
        if isinstance(part, dict) and part.get("kind") == "text" and part.get("text"):
            text += str(part.get("text")) + "\n"

    if not text:
        return {}

    pr_map: Dict[str, str] = {}
    current_branch: Optional[str] = None

    # 0) 特殊场景：PR 创建失败但错误信息中包含「已有 MR/PR」提示，
    #    例如：
    #      - Target Branch: OLK-5.10
    #      - Target Repository: https://atomgit.com/openeuler/kernel
    #      - Error Reason: Another open merge request already exists ... (PR #20060)
    #
    #    这种场景下可以根据 target repo + PR 序号拼出 PR 链接：
    #      https://atomgit.com/openeuler/kernel/pull/20060
    branch_in_err = re.search(r"Target Branch:\s*([A-Za-z0-9_.\-]+)", text)
    repo_in_err = re.search(r"Target Repository:\s*(https?://\S+)", text)
    prnum_in_err = re.search(r"PR\s*#(\d+)", text)
    if branch_in_err and repo_in_err and prnum_in_err:
        b = branch_in_err.group(1).strip()
        repo_url = repo_in_err.group(1).strip().rstrip("/")
        pr_num = prnum_in_err.group(1).strip()
        if b and repo_url and pr_num:
            # AtomGit 当前 PR URL 形如：https://atomgit.com/openeuler/kernel/pull/20060
            pr_url = f"{repo_url}/pull/{pr_num}"
            pr_map[b] = pr_url

    # 1) 解析形如 "**OLK-6.6 Branch**" 的分支标题
    heading_branch_pattern = re.compile(r"\*\*(.+?) Branch\*\*")
    # 2) 解析形如 "For OLK-6.6: PR #31 exists at [xxx](url)" 的行
    for_branch_pr_pattern = re.compile(
        r"For\s+([A-Za-z0-9_.\-]+)\s*:\s*PR\s*#\d+\s+exists at\s+\[[^\]]+\]\((https?://[^)]+)\)",
        re.IGNORECASE,
    )
    # 3) 通用 PR 链接提取（在已经知道 current_branch 的前提下）
    generic_pr_pattern = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # 优先匹配 "For OLK-6.6: PR #31 exists at ..." 这种行，直接拿到分支和 URL
        m_for = for_branch_pr_pattern.search(line)
        if m_for:
            branch = m_for.group(1).strip()
            pr_url = m_for.group(2).strip()
            if branch and pr_url:
                pr_map[branch] = pr_url
            continue

        # 其次匹配 "**OLK-6.6 Branch**" 标题行，记住当前分支名
        m_heading = heading_branch_pattern.search(line)
        if m_heading:
            current_branch = m_heading.group(1).strip()
            continue

        # 如果已经有 current_branch，再在后续行里找通用 PR 链接
        if current_branch:
            m_pr = generic_pr_pattern.search(line)
            if m_pr:
                pr_url = m_pr.group(1).strip()
                if pr_url:
                    pr_map[current_branch] = pr_url

    return pr_map


def _parse_create_pr_command(comment_body: str) -> Optional[Dict[str, Any]]:
    """
    解析评论中的 /create_pr 指令，仅支持多行形式，例如：

      /create_pr

      branch: OLK-6.6 OLK-5.10
      name: dev
      email: dev@devstation.com

    约束：
      - 仅当“首个非空行”以 /create_pr 开头时才认为是有效指令，
      - 各个字段必须单独占一行，且以 "branch:" / "name:" / "email:" 开头，
        这样可以避免指导评论中的示例或一行写完的复杂格式被误触发。

    返回:
      {
        "branches": ["OLK-6.6", "OLK-5.10"],
        "signer_name": "dev",
        "signer_email": "dev@devstation.com",
      }

    若评论中不包含 /create_pr，则返回 None。
    若包含 /create_pr 但缺少必填字段，则抛出 ValueError。
    """
    text = comment_body or ""
    if not text.strip():
        return None

    # 只在“首个非空行”是 /create_pr 时才继续解析，避免指导评论里的示例代码块被误识别
    lines = [(line or "").strip() for line in text.splitlines()]
    first_non_empty = ""
    for ln in lines:
        if ln:
            first_non_empty = ln
            break

    flags = re.IGNORECASE
    if not first_non_empty or not re.match(r"^/create_pr\b", first_non_empty, flags):
        return None

    # 优先按“每个字段一行”的形式解析，更直观可靠：
    #   branch: OLK-6.6 OLK-5.10
    #   name: dev
    #   email: dev@devstation.com
    branch_line = None
    name_line = None
    email_line = None
    backport_engine_line = None
    for ln in lines:
        if re.match(r"^branch\s*:", ln, flags):
            branch_line = ln
        elif re.match(r"^name\s*:", ln, flags):
            name_line = ln
        elif re.match(r"^email\s*:", ln, flags):
            email_line = ln
        elif re.match(r"^backport[-_]engine\s*:", ln, flags):
            backport_engine_line = ln

    missing_fields: List[str] = []

    branches: List[str] = []
    if branch_line is not None:
        branch_part = re.sub(r"^branch\s*:\s*", "", branch_line, flags).strip()
        if branch_part:
            # 支持空格或逗号分隔多个分支
            branches = [b for b in re.split(r"[,\s]+", branch_part) if b]
    if not branches:
        missing_fields.append("branch")

    signer_name = ""
    if name_line is not None:
        signer_name = re.sub(r"^name\s*:\s*", "", name_line, flags).strip()
    if not signer_name:
        missing_fields.append("name")

    signer_email = ""
    if email_line is not None:
        signer_email = re.sub(r"^email\s*:\s*", "", email_line, flags).strip()
    if not signer_email:
        missing_fields.append("email")

    backport_engine = ""
    if backport_engine_line is not None:
        backport_engine = re.sub(r"^backport[-_]engine\s*:\s*", "", backport_engine_line, flags).strip()

    if missing_fields:
        # 抛出异常，由上层负责在 Issue 下给出详细提示
        raise ValueError(f"缺少必填字段: {', '.join(missing_fields)}")

    result = {
        "branches": branches,
        "signer_name": signer_name,
        "signer_email": signer_email,
    }
    if backport_engine:
        result["backport_engine"] = backport_engine
    return result


def build_guide_comment_body(cve_id: str) -> str:
    """
    生成在新建 CVE Issue 下的“使用指引”评论内容（Gitee / GitCode 共用）。
    """
    guide_lines = [
        f"检测到新建 CVE Issue，CVE-ID: **{cve_id}**。",
        "",
        "你可以通过以下两种方式使用 CVE 修复服务：",
        "",
        "1. **分支影响分析**",
        "   - 在本 Issue 下评论：`/analysis_branches`",
        "   - 系统将自动分析各个分支是否受影响，并在本 Issue 下给出表格形式的分析结果；",
        "",
        "2. **在指定分支上创建 PR（修复提交）**",
        "   - 在本 Issue 下按如下格式评论（字段均为必填，每个字段单独一行）：",
        "",
        "```",
        "/create_pr",
        "",
        "branch: OLK-6.6 OLK-5.10",
        "name: dev",
        "email: dev@devstation.com",
        "```",
        "",
        "   - 说明：",
        "     - `branch`: 需要创建 PR 的目标分支列表，例如 `OLK-6.6 OLK-5.10`；",
        "     - `name`: PR 签名人姓名（如责任人或安全负责人）；",
        "     - `email`: PR 签名人邮箱；",
        "",
        "系统会根据上述信息自动在指定分支上创建 PR，并在本 Issue 下反馈结果。",
        "",
        "provided by DevStation.",
    ]
    return "\n".join(guide_lines)


def _handle_comment_commands(
    payload: Dict[str, Any],
    issue_title: str,
    comment_body: str,
    *,
    allow_reply_comment: bool,
    platform: str,
):
    """
    通用的评论指令处理逻辑：
      - /analysis_branches：触发分支分析任务
      - /create_pr：触发 pipeline 任务

    参数:
      - payload: 原始 WebHook JSON（Gitee 或 GitCode）
      - issue_title: 对应 Issue 的标题
      - comment_body: 本条评论内容
      - allow_reply_comment: 是否允许在 Issue 下自动回复确认/指引评论
      - platform: "gitee" 或 "gitcode"
    """
    # ---------- 1. 解析 /analysis_branches 指令 ----------
    # 仅当“首个非空行”是 /analysis_branches 时才触发分支分析，
    # 避免在指导评论或示例代码块中误触发。
    lines = [(line or "").strip() for line in (comment_body or "").splitlines()]
    first_non_empty = ""
    for ln in lines:
        if ln:
            first_non_empty = ln
            break

    if first_non_empty and re.match(r"^/analysis_branches\b", first_non_empty, flags=re.IGNORECASE):
        logger.info("Issue 标题: %s", issue_title)

        cve_id = extract_cve_id(issue_title) or extract_cve_id(comment_body)
        if not cve_id:
            logger.info("Issue 标题/评论中未解析到 CVE-ID，忽略 /analysis_branches 指令。")
            return jsonify({"msg": "ignored (no cve-id for /analysis_branches)"}), 200

        task = {
            "cve_id": cve_id,
            "payload": payload,
            "action": "branches-analysis",
        }
        try:
            TASK_QUEUE.put(task)
            logger.info("已将分支分析任务入队，CVE-ID: %s, action=branches-analysis", cve_id)
        except Exception as e:
            logger.exception("分支分析任务入队失败: %s", e)
            return jsonify({"msg": "enqueue task failed", "detail": str(e)}), 500

        if allow_reply_comment:
            try:
                if platform == "gitcode":
                    # 延迟导入，避免在 common 与 gitcode_client 之间形成循环依赖
                    from gitcode_client import reply_gitcode_issue_comment

                    reply_gitcode_issue_comment(payload, cve_id)
                else:
                    # 延迟导入，避免在 common 与 gitee_client 之间形成循环依赖
                    from gitee_client import reply_issue_comment

                    reply_issue_comment(payload, cve_id)
            except Exception:
                # reply_issue_comment 内部已记录日志，这里避免影响 WebHook 返回
                pass

        return jsonify({"msg": "accepted", "cve_id": cve_id, "action": "branches-analysis"}), 202

    # ---------- 2. 解析 /create_pr 指令 ----------
    try:
        parsed_cmd = _parse_create_pr_command(comment_body or "")
    except ValueError as e:
        # 评论中包含 /create_pr 但缺少必填字段：在支持自动回复的平台下给出指导评论
        issue_title_for_msg = issue_title or ""
        cve_id_for_msg = extract_cve_id(issue_title_for_msg) or extract_cve_id(comment_body or "") or ""

        logger.info(
            "解析 /create_pr 指令失败，CVE-ID: %s, error=%s",
            cve_id_for_msg or "UNKNOWN",
            e,
        )

        if allow_reply_comment:
            guide_body_lines = [
                f"⚠️ `/create_pr` 指令格式错误：{e}",
                "",
                "请按照以下格式在评论中填写（字段均为必填，且每个字段单独一行；`branch` 支持多个分支，使用空格分隔）：",
                "",
                "/create_pr",
                "",
                "branch: OLK-6.6 OLK-5.10",
                "name: dev",
                "email: dev@devstation.com",
                "",
                "说明：",
                "- `branch`: 需要创建 PR 的目标分支列表，例如 `OLK-6.6 OLK-5.10`；",
                "- `name`: PR 签名人姓名（如责任人或安全负责人）；",
                "- `email`: PR 签名人邮箱；",
                "",
                "你也可以先评论 `/analysis_branches` 获取各分支的受影响情况，然后再使用以上格式的 `/create_pr` 指令在指定分支上自动创建 PR。",
                "",
                "provided by DevStation.",
            ]
            body = "\n".join(guide_body_lines)
            try:
                if platform == "gitcode":
                    # 延迟导入，避免循环依赖
                    from gitcode_client import _post_gitcode_issue_comment

                    _post_gitcode_issue_comment(payload, body)
                else:
                    from gitee_client import _post_issue_comment

                    _post_issue_comment(payload, body)
            except Exception:
                # 指导评论失败不影响 WebHook 返回
                pass

        return jsonify({"msg": "ignored (invalid /create_pr format)", "error": str(e)}), 200

    if not parsed_cmd:
        logger.info("评论中未包含 /create_pr 指令，忽略。")
        return jsonify({"msg": "ignored (no /create_pr command in comment)"}), 200

    branches = parsed_cmd.get("branches") or []
    signer_name = parsed_cmd.get("signer_name")
    signer_email = parsed_cmd.get("signer_email")
    backport_engine = parsed_cmd.get("backport_engine") or DEFAULT_BACKPORT_ENGINE

    logger.info("Issue 标题: %s", issue_title)

    # 优先从 Issue 标题解析 CVE-ID（你的场景：Issue 标题本身就是 CVE-ID）；
    # 若标题中没有，再从评论正文里兜底解析一次
    cve_id = extract_cve_id(issue_title) or extract_cve_id(comment_body or "")
    if not cve_id:
        logger.info("Issue 标题/评论中未解析到 CVE-ID，忽略 /create_pr 指令。")
        return jsonify({"msg": "ignored (no cve-id in issue title or comment)"}), 200

    # 1) 将任务入队，由后台 Worker 处理，避免阻塞 WebHook
    task = {
        "cve_id": cve_id,
        "payload": payload,
        "action": "pipeline",
        "backport_engine": backport_engine,
    }
    if branches:
        task["branches"] = branches
    if signer_name:
        task["signer_name"] = signer_name
    if signer_email:
        task["signer_email"] = signer_email

    try:
        TASK_QUEUE.put(task)
        logger.info(
            "已将 pipeline 任务入队，CVE-ID: %s, branches=%s, signer_name=%s, signer_email=%s, backport_engine=%s",
            cve_id,
            ",".join(branches) if branches else "",
            signer_name or "",
            signer_email or "",
            backport_engine,
        )
    except Exception as e:
        logger.exception("pipeline 任务入队失败: %s", e)
        return jsonify({"msg": "enqueue task failed", "detail": str(e)}), 500

    # 2) 立即在 Issue 下回复一条确认评论（失败不影响 WebHook 返回）
    if allow_reply_comment:
        try:
            if platform == "gitcode":
                from gitcode_client import reply_gitcode_issue_comment

                reply_gitcode_issue_comment(payload, cve_id)
            else:
                from gitee_client import reply_issue_comment

                reply_issue_comment(payload, cve_id)
        except Exception:
            # reply_issue_comment 内部已记录日志，这里避免影响 WebHook 返回
            pass

    # 3) 立即返回成功响应，后续分析和结果回写由后台 Worker 完成
    resp_data: Dict[str, Any] = {"msg": "accepted", "cve_id": cve_id, "action": "pipeline"}
    if branches:
        resp_data["branches"] = branches
    if signer_name:
        resp_data["signer_name"] = signer_name
    if signer_email:
        resp_data["signer_email"] = signer_email

    return jsonify(resp_data), 202