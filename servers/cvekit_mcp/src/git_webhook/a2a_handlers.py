import re
import ast
from typing import List, Optional, Dict, Any

from config import logger
from common import RESULT_QUEUE


def _handle_status_update_event(
    *,
    result_obj: Dict[str, Any],
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
    reported_task_error: bool,
) -> bool:
    """
    处理 A2A 的 status-update 事件：
      - 识别整体任务失败状态（failed/error/failure），推送 error 事件
      - 从 metadata / 文本中解析 analyze_branches / create_pr / get_commits 等工具结果
    """
    status = result_obj.get("status", {})
    message = status.get("message") or {}

    # 1) 整体任务失败检测
    state = (status.get("state") or status.get("status") or "").lower()
    if state in {"failed", "error", "failure"} and not reported_task_error:
        texts: List[str] = []
        for p in message.get("parts") or []:
            if p.get("kind") == "text" and p.get("text"):
                texts.append(str(p.get("text")))
        error_text = " ".join(texts).strip() or f"后端任务状态为 {state}"
        logger.warning(
            "run_app_client: 检测到后端任务失败状态，CVE-ID: %s, action=%s, error=%s",
            cve_id,
            action,
            error_text[:200],
        )
        RESULT_QUEUE.put(
            {
                "event": "error",
                "cve_id": cve_id,
                "payload": payload,
                "error": error_text,
                "action": action,
            }
        )
        reported_task_error = True

    # 2) 逐个 part 解析 metadata / 文本
    for part in message.get("parts") or []:
        # 2.1 优先解析结构化 metadata
        if _handle_status_update_meta_part(
            part=part,
            cve_id=cve_id,
            action=action,
            payload=payload,
        ):
            continue

        # 2.2 解析人类可读文本
        handled = _handle_status_update_text_part(
            part=part,
            cve_id=cve_id,
            action=action,
            payload=payload,
        )
        if handled:
            continue

    return reported_task_error


def _handle_status_update_meta_part(
    *,
    part: Dict[str, Any],
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
) -> bool:
    meta = part.get("metadata") or {}
    if not meta:
        return False
    try:
        exec_res = meta.get("execuation_result")
        # analyze_branches：execuation_result 为列表
        if isinstance(exec_res, list) and exec_res:
            logger.info(
                "run_app_client: 检测到 analyze_branches 元数据结果，CVE-ID: %s，分支数=%d，准备写入 RESULT_QUEUE。",
                cve_id,
                len(exec_res),
            )
            event_payload = {
                "event": "branches_analysis",
                "cve_id": cve_id,
                "payload": payload,
                "items": exec_res,
                "action": action,
            }
            RESULT_QUEUE.put(event_payload)
            logger.info(
                "run_app_client: 已写入 RESULT_QUEUE 事件 branches_analysis，CVE-ID: %s，items_len=%d",
                cve_id,
                len(exec_res),
            )
            return True
        # create_pr：execuation_result 为字典，包含 PR 链接等信息
        if isinstance(exec_res, dict):
            branch = exec_res.get("branch") or exec_res.get("target_branch") or ""
            pr_url = (
                exec_res.get("pr_html_url")
                or exec_res.get("pr_url")
                or exec_res.get("pr_link")
                or ""
            )
            if pr_url:
                logger.info(
                    "run_app_client: 检测到 create_pr 元数据结果，CVE-ID: %s，branch=%s, pr_url=%s，准备写入 RESULT_QUEUE。",
                    cve_id,
                    branch,
                    pr_url,
                )
                event_payload = {
                    "event": "pr_created",
                    "cve_id": cve_id,
                    "payload": payload,
                    "branch": branch,
                    "pr_url": pr_url,
                    "action": action,
                }
                RESULT_QUEUE.put(event_payload)
                logger.info(
                    "run_app_client: 已写入 RESULT_QUEUE 事件 pr_created，CVE-ID: %s，branch=%s, pr_url=%s",
                    cve_id,
                    branch,
                    pr_url,
                )
                return True
    except Exception as e:
        logger.warning(
            "解析 metadata 失败，将回退到文本解析，CVE-ID: %s, meta=%s, error=%s",
            cve_id,
            str(meta)[:200],
            e,
        )
    return False


def _handle_status_update_text_part(
    *,
    part: Dict[str, Any],
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
    # 保持与其它 handler 一致的参数结构，便于扩展
) -> bool:
    if part.get("kind") != "text":
        return False
    text = part.get("text") or ""
    if not text:
        return False

    _log_a2a_tool_event(text=text, cve_id=cve_id)

    handled = _handle_get_commits_failure(
        text=text,
        cve_id=cve_id,
        action=action,
        payload=payload,
    )
    if handled:
        return True

    handled = _handle_analyze_branches_complete(
        text=text,
        cve_id=cve_id,
        action=action,
        payload=payload,
    )
    if handled:
        return True

    handled = _handle_create_pr_complete(
        text=text,
        cve_id=cve_id,
        action=action,
        payload=payload,
    )
    if handled:
        return True

    return False


def _log_a2a_tool_event(*, text: str, cve_id: str) -> None:
    tool_evt = None
    try:
        m_tool = re.search(
            r"tool_(start|complete)\s*,\s*tool_name:([a-zA-Z0-9_]+)", text
        )
        if m_tool:
            phase = m_tool.group(1)
            tool_name = m_tool.group(2)
            tool_evt = (phase, tool_name)
    except Exception:
        tool_evt = None

    if not tool_evt:
        return
    phase, tool_name = tool_evt
    logger.info(
        "检测到 A2A 工具事件，CVE-ID: %s，phase=%s, tool=%s, text=%s",
        cve_id,
        phase,
        tool_name,
        text[:200],
    )


def _handle_get_commits_failure(
    *,
    text: str,
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
) -> bool:
    if "tool_complete" not in text or "tool_name:get_commits" not in text:
        return False
    reason = ""
    try:
        _, result_part = text.split("execuation_result:", 1)
        reason = result_part.strip()
    except ValueError:
        reason = text

    if (
        "Failed to obtain submission information" in reason
        or "未能获取完整的引入提交" in reason
        or "无法继续流程" in reason
    ):
        logger.info(
            "run_app_client: 检测到 get_commits 失败事件，CVE-ID: %s，reason=%s",
            cve_id,
            reason[:200],
        )
        RESULT_QUEUE.put(
            {
                "event": "get_commits_error",
                "cve_id": cve_id,
                "payload": payload,
                "error": reason,
                "action": action,
            }
        )
        return True
    return False


def _handle_analyze_branches_complete(
    *,
    text: str,
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
) -> bool:
    if "tool_complete" not in text or "tool_name:analyze_branches" not in text:
        return False
    try:
        _, result_part = text.split("execuation_result:", 1)
    except ValueError:
        if action == "branches-analysis":
            logger.info(
                "run_app_client: analyze_branches 文本结果无法解析 execuation_result，将以 raw 形式回传，CVE-ID: %s",
                cve_id,
            )
            RESULT_QUEUE.put(
                {
                    "event": "branches_analysis_raw",
                    "cve_id": cve_id,
                    "payload": payload,
                    "raw_text": text,
                    "action": action,
                }
            )
        return True

    result_part = (result_part or "").strip()
    items = None

    # 1) 优先尝试按 Python 字面量解析（兼容老格式）
    if result_part and result_part[0] in "[{":
        try:
            items = ast.literal_eval(result_part)
        except Exception as e:
            logger.warning(
                "解析 analyze_branches 结果为 Python 字面量失败，将退化为 Markdown 表格解析，CVE-ID: %s, text=%s, error=%s",
                cve_id,
                text[:200],
                e,
            )

    # 2) 如未能解析为字面量，再尝试从 Markdown 表格中提取
    if items is None:
        items = _parse_analyze_branches_markdown(result_part)

    if not items:
        # 仍然解析失败时，对于 /analysis_branches 兜底返回 raw 文本，pipeline 则只在最终汇总里体现失败原因
        logger.warning(
            "解析 analyze_branches 结果失败（字面量+Markdown 均无法解析），CVE-ID: %s, text=%s",
            cve_id,
            text[:200],
        )
        if action == "branches-analysis":
            logger.info(
                "run_app_client: analyze_branches 结果无法结构化解析，将以 raw 形式回传，CVE-ID: %s",
                cve_id,
            )
            RESULT_QUEUE.put(
                {
                    "event": "branches_analysis_raw",
                    "cve_id": cve_id,
                    "payload": payload,
                    "raw_text": result_part,
                    "action": action,
                }
            )
        return True

    logger.info(
        "run_app_client: 检测到 analyze_branches 文本结果，CVE-ID: %s，分支数=%d，准备写入 RESULT_QUEUE。",
        cve_id,
        len(items),
    )
    event_payload = {
        "event": "branches_analysis",
        "cve_id": cve_id,
        "payload": payload,
        "items": items,
        "action": action,
    }
    RESULT_QUEUE.put(event_payload)
    logger.info(
        "run_app_client: 已写入 RESULT_QUEUE 事件 branches_analysis（文本），CVE-ID: %s，items_len=%d",
        cve_id,
        len(items),
    )
    return True


def _handle_create_pr_complete(
    *,
    text: str,
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
    # create_pr 的完成文本里包含目标分支信息，不再依赖临时缓存
) -> bool:
    if "tool_complete" not in text or "tool_name:create_pr" not in text:
        return False
    try:
        _, result_part = text.split("execuation_result:", 1)
    except ValueError:
        return False

    (
        result_part,
        result_lines,
        pr_url,
        target_repo_url,
        target_branch,
    ) = _parse_create_pr_result(result_part)

    if not pr_url:
        _handle_create_pr_failure(
            cve_id=cve_id,
            action=action,
            payload=payload,
            result_part=result_part,
            result_lines=result_lines,
            target_repo_url=target_repo_url,
            target_branch=target_branch,
        )
        return True

    _emit_pr_created_event(
        cve_id=cve_id,
        action=action,
        payload=payload,
        branch=target_branch or "",
        pr_url=pr_url,
        log_prefix="run_app_client: 检测到 create_pr 文本结果",
        log_suffix="已写入 RESULT_QUEUE 事件 pr_created（文本）",
    )
    return True


def _parse_create_pr_result(
    result_part: str,
) -> (str, List[str], Optional[str], str, str):
    result_lines = result_part.splitlines()
    pr_url = _extract_field_from_lines(result_lines, "- pr link:")
    target_repo_url = _extract_field_from_lines(result_lines, "- target repository:") or ""
    target_branch = _extract_field_from_lines(result_lines, "- target branch:") or ""

    if not pr_url:
        # 兼容某些 agent 直接在文本里输出 PR 链接的情况
        m_pr = re.search(r'(https?://[^\s"\']+/pulls/\d+)', result_part)
        if m_pr:
            pr_url = m_pr.group(1).strip()
    return result_part, result_lines, pr_url, target_repo_url, target_branch


def _handle_create_pr_failure(
    *,
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
    result_part: str,
    result_lines: List[str],
    target_repo_url: str,
    target_branch: str,
) -> None:
    error_summary = _extract_create_pr_error_summary(
        result_part=result_part,
        result_lines=result_lines,
    )
    err_branch = target_branch or _extract_create_pr_error_branch(result_lines=result_lines)
    existing_pr_url = _extract_existing_pr_url(
        result_part=result_part,
        target_repo_url=target_repo_url,
        error_summary=error_summary,
    )

    if _emit_existing_pr_event_if_any(
        cve_id=cve_id,
        action=action,
        payload=payload,
        err_branch=err_branch,
        existing_pr_url=existing_pr_url,
    ):
        return

    _emit_pr_failed_event(
        cve_id=cve_id,
        action=action,
        payload=payload,
        err_branch=err_branch,
        error_summary=error_summary,
    )


def _emit_existing_pr_event_if_any(
    *,
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
    err_branch: str,
    existing_pr_url: Optional[str],
) -> bool:
    if not existing_pr_url:
        return False
    # 将「已有 MR」视作已存在的 PR，直接按 pr_created 事件回传，
    # 这样最终汇总表格中的 PR 列会展示为可点击的链接，而不是一段错误文本。
    logger.info(
        "run_app_client: 检测到 create_pr 失败但已有 MR 存在，CVE-ID: %s，branch=%s, pr_url=%s",
        cve_id,
        err_branch or "",
        existing_pr_url,
    )
    _emit_pr_created_event(
        cve_id=cve_id,
        action=action,
        payload=payload,
        branch=err_branch or "",
        pr_url=existing_pr_url,
        log_prefix="run_app_client: 检测到 create_pr 失败但已有 MR 存在",
        log_suffix="已写入 RESULT_QUEUE 事件 pr_created（文本）",
    )
    return True


def _emit_pr_failed_event(
    *,
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
    err_branch: str,
    error_summary: str,
) -> None:
    # 不属于「已有 MR」场景，退化为原有的 pr_failed 处理逻辑
    logger.info(
        "run_app_client: 检测到 create_pr 失败文本结果，CVE-ID: %s，branch=%s, reason=%s",
        cve_id,
        err_branch or "",
        error_summary,
    )
    RESULT_QUEUE.put(
        {
            "event": "pr_failed",
            "cve_id": cve_id,
            "payload": payload,
            "branch": err_branch or "",
            "error": error_summary,
            "action": action,
        }
    )


def _extract_create_pr_error_summary(
    *,
    result_part: str,
    result_lines: List[str],
) -> str:
    error_summary = _extract_field_from_lines(result_lines, "- failure reason:") or ""
    if not error_summary:
        error_summary = (result_part or "").strip()
    if len(error_summary) > 200:
        error_summary = error_summary[:200] + "..."
    return error_summary


def _extract_create_pr_error_branch(
    *,
    result_lines: List[str],
) -> str:
    return _extract_field_from_lines(result_lines, "- target branch:") or ""


def _extract_field_from_lines(
    result_lines: List[str],
    prefix: str,
) -> Optional[str]:
    prefix_lower = prefix.lower()
    for l in result_lines:
        ls = (l or "").strip()
        if ls.lower().startswith(prefix_lower):
            parts = ls.split(":", 1)
            value = parts[1].strip() if len(parts) > 1 else ""
            return value or ""
    return None


def _extract_existing_pr_url(
    *,
    result_part: str,
    target_repo_url: str,
    error_summary: str,
) -> Optional[str]:
    # 尝试从 error_message 中解析「已有 MR」编号，例如：
    #   "error_message":"Another open merge request already exists for this source branch: !20060"
    existing_pr_url: Optional[str] = None
    try:
        # 1) 从 JSON 片段中提取 error_message 字段
        m_err = re.search(r'"error_message"\s*:\s*"([^"]+)"', result_part)
        err_msg_raw = m_err.group(1) if m_err else error_summary

        # 2) 从 error_message 中提取 MR 序号（形如 !20060）
        if err_msg_raw:
            m_mr = re.search(
                r"Another open merge request already exists for this source branch:\s*!?(\d+)",
                err_msg_raw,
                re.IGNORECASE,
            )
            if m_mr and target_repo_url:
                mr_iid = m_mr.group(1)
                repo_base = target_repo_url.rstrip("/")
                # AtomGit / GitLab 风格的 MR 链接：<repo_url>/merge_requests/<iid>
                existing_pr_url = f"{repo_base}/merge_requests/{mr_iid}"
    except Exception:
        existing_pr_url = None
    return existing_pr_url


def _emit_pr_created_event(
    *,
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
    branch: str,
    pr_url: str,
    log_prefix: str,
    log_suffix: str,
) -> None:
    logger.info(
        "%s，CVE-ID: %s，branch=%s, pr_url=%s",
        log_prefix,
        cve_id,
        branch,
        pr_url,
    )
    event_payload = {
        "event": "pr_created",
        "cve_id": cve_id,
        "payload": payload,
        "branch": branch,
        "pr_url": pr_url,
        "action": action,
    }
    RESULT_QUEUE.put(event_payload)
    logger.info(
        "%s，CVE-ID: %s，branch=%s, pr_url=%s",
        log_suffix,
        cve_id,
        branch,
        pr_url,
    )


def _handle_artifact_update_event(
    *,
    result_obj: Dict[str, Any],
    cve_id: str,
    action: str,
    payload: Dict[str, Any],
) -> None:
    """
    处理 A2A 的 artifact-update 事件，目前只关心 name=final_result，
    用于触发“最终汇总表格”的生成。
    """
    artifact = result_obj.get("artifact") or {}
    name = artifact.get("name")
    if name != "final_result":
        return

    logger.info(
        "run_app_client: 检测到 final_result artifact，CVE-ID: %s，artifactId=%s，准备写入 RESULT_QUEUE。",
        cve_id,
        artifact.get("artifactId"),
    )
    event_payload = {
        "event": "final_result",
        "cve_id": cve_id,
        "payload": payload,
        "artifact": artifact,
        "action": action,
    }
    RESULT_QUEUE.put(event_payload)
    logger.info(
        "run_app_client: 已写入 RESULT_QUEUE 事件 final_result，CVE-ID: %s，artifactId=%s",
        cve_id,
        artifact.get("artifactId"),
    )


def _parse_analyze_branches_markdown(result_part: str) -> List[Dict[str, Any]]:
    """
    尝试从 analyze_branches 的 Markdown 表格文本中解析出结构化分支信息。

    支持中英文表头，列顺序可能调整，示例：
      | Patch ID | Target Branch | Whether Affected | Adaptation Status | Patch Path | Suggested Adjustment Files | Diff File | Whether Conflicts Exist | Commit Message |
      |--------|----------|------------|----------|--------|--------------|----------|--------------|----------|
      | CVE-2025-68742 | OLK-5.10 | Affected | success | ... | N/A | diff | No | commit msg |

      | 补丁ID | 目标分支 | 是否受影响 | 适配状态 | 补丁路径 | 建议调整文件 | 差异文件 | 是否存在冲突 | 提交信息 |
      |--------|----------|------------|----------|--------|--------------|----------|--------------|----------|
      | CVE-2025-68742 | OLK-5.10 | 受影响 | 成功 | ... | N/A | diff | 否 | 提交信息 |
    """
    if not result_part:
        logger.debug("analyze_branches Markdown 解析：result_part 为空，直接返回空列表。")
        return []

    lines = [ln.rstrip() for ln in str(result_part).splitlines()]
    logger.debug(
        "analyze_branches Markdown 解析：共 %d 行，前 3 行预览：%s",
        len(lines),
        " || ".join(lines[:3])[:300],
    )

    header_idx = -1
    header_cells: List[str] = []
    for i, ln in enumerate(lines):
        ln_stripped = ln.strip()
        if "|" not in ln_stripped:
            continue
        # 优先识别中英文表头（包含“目标分支/Target Branch”和“是否受影响/Whether Affected”）
        if ("目标分支" in ln_stripped and "是否受影响" in ln_stripped) or (
            "target" in ln_stripped.lower()
            and "branch" in ln_stripped.lower()
            and "whether" in ln_stripped.lower()
        ):
            header_cells = [p.strip() for p in ln_stripped.strip("|").split("|")]
            header_idx = i
            break

    if header_idx < 0 or header_idx + 2 >= len(lines):
        logger.warning(
            "analyze_branches Markdown 解析：未找到表头或行数不足，header_idx=%d, total_lines=%d",
            header_idx,
            len(lines),
        )
        return []

    def normalize_header(name: str) -> str:
        base = name.strip().lower().replace(" ", "")
        base = base.replace("_", "")
        return base

    header_map: Dict[str, int] = {}
    for idx, col in enumerate(header_cells):
        key = normalize_header(col)
        if not key:
            continue
        if any(k in key for k in ["补丁id", "patchid"]):
            header_map["patch_id"] = idx
        elif "目标分支" in key or "targetbranch" in key:
            header_map["target_branch"] = idx
        elif "是否受影响" in key or "whetheraffected" in key:
            header_map["weather_affected"] = idx
        elif "适配状态" in key or "adaptationstatus" in key:
            header_map["adjust_status"] = idx
        elif "补丁路径" in key or "冲突点" in key or "patchpath" in key or "conflictpoint" in key:
            header_map["patch_path"] = idx
        elif "建议调整文件" in key or "suggestedadjustmentfiles" in key:
            header_map["suggest_adjust_files"] = idx
        elif "差异文件" in key or "difffile" in key:
            header_map["diff_file"] = idx
        elif "是否存在冲突" in key or "whetherconflictsexist" in key:
            header_map["conflicts_exist"] = idx
        elif "提交信息" in key or "commitmessage" in key:
            header_map["commit_msg"] = idx

    if "target_branch" not in header_map:
        logger.warning(
            "analyze_branches Markdown 解析：表头未包含目标分支字段，header=%s",
            header_cells,
        )
        return []

    items: List[Dict[str, Any]] = []
    # 数据行从 header 下一行（分隔行）之后开始
    for ln in lines[header_idx + 2 :]:
        ln_stripped = ln.strip()
        # 表格数据通常以 '|' 开头，遇到空行或非表格行则结束
        if not ln_stripped or not ln_stripped.startswith("|"):
            break

        cells = [p.strip() for p in ln_stripped.strip("|").split("|")]
        if len(cells) < len(header_cells):
            continue

        def pick(col_key: str) -> str:
            idx = header_map.get(col_key)
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx]

        target_branch = pick("target_branch")
        if not target_branch:
            continue

        patch_path = pick("patch_path")
        item: Dict[str, Any] = {
            "patch_id": pick("patch_id"),
            "target_branch": target_branch,
            "weather_affected": pick("weather_affected"),
            "adjust_status": pick("adjust_status"),
            "patch_path": patch_path,
            "conflict_point": patch_path,
            "suggest_adjust_files": pick("suggest_adjust_files"),
            "Diff file": pick("diff_file"),
            "Commit message": pick("commit_msg"),
            "conflicts_exist": pick("conflicts_exist"),
        }
        items.append(item)

    logger.debug(
        "analyze_branches Markdown 解析完成：解析到 %d 条记录，示例首条记录：%s",
        len(items),
        repr(items[0])[:300] if items else "N/A",
    )
    return items
