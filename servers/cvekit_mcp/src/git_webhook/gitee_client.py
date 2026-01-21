from typing import Dict, Any

import requests
from flask import jsonify

from config import logger, GITEE_ACCESS_TOKEN, GITEE_API_BASE
from common import extract_cve_id, build_guide_comment_body


def _post_issue_comment(payload: Dict[str, Any], body: str) -> None:
    """
    在 Gitee Issue 下追加一条评论。
    """
    if not GITEE_ACCESS_TOKEN:
        logger.info("未配置 GITEE_ACCESS_TOKEN，跳过在 Gitee 上回复评论。")
        return

    project = payload.get("project") or payload.get("repository") or {}
    path_with_namespace = project.get("path_with_namespace") or project.get("full_name")

    issue = payload.get("issue") or {}
    # Gitee 的 issue number，如 "ID7QMP"
    issue_number = issue.get("number") or (payload.get("per_iid") or "").lstrip("#")

    if not path_with_namespace or not issue_number:
        logger.warning("无法解析 Gitee 项目或 Issue 编号，跳过回复评论。")
        return

    try:
        owner, repo = path_with_namespace.split("/", 1)
    except ValueError:
        logger.warning("path_with_namespace 格式异常: %s", path_with_namespace)
        return

    api_url = f"{GITEE_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    data = {
        "access_token": GITEE_ACCESS_TOKEN,
        "body": body,
    }

    try:
        resp = requests.post(api_url, data=data, timeout=10)
        if not (200 <= resp.status_code < 300):
            logger.warning(
                "回复 Gitee 评论失败: status=%s, resp=%s",
                resp.status_code,
                resp.text[:500],
            )
        else:
            logger.info(
                "已在 Gitee Issue %s 下回复评论，内容前 200 字: %s",
                issue_number,
                body.replace("\n", "\\n")[:200],
            )
    except Exception as e:
        logger.exception("调用 Gitee API 回复评论失败: %s", e)


def reply_issue_comment(payload: Dict[str, Any], cve_id: str) -> None:
    """
    在对应的 Gitee Issue 下回复一条评论，告知已触发 CVE 修复服务。
    失败不会影响 WebHook 主流程。
    """
    body = f"已触发 CVE 修复服务，CVE-ID: {cve_id}。\nprovided by DevStation."
    _post_issue_comment(payload, body)


def _handle_issue_created_webhook(payload: Dict[str, Any]):
    """
    处理「新建 Issue」类 WebHook（Gitee）：
      - 当检测到是一个新的 CVE Issue 时，自动在该 Issue 下回复一条指导评论，
        告知用户如何使用 /analysis_branches 与 /create_pr。
    """
    issue = payload.get("issue") or {}
    action = (payload.get("action") or "").lower()

    # 仅在新建（open/opened）场景下回复指导评论，其他（如更新、关闭）忽略
    if action not in {"open", "opened", ""}:
        # action 为空时，有些场景可能仍是新建，这里放宽处理：只是在 action 明确为更新/关闭时忽略
        logger.info("Issue WebHook 动作非 open/opened(action=%s)，忽略指导评论。", action)
        return jsonify({"msg": "ignored (issue action not open)"}), 200

    title = issue.get("title") or ""
    cve_id = extract_cve_id(title) or ""

    if not cve_id:
        logger.info("新建 Issue 标题中未识别到 CVE-ID，跳过自动指导评论。title=%s", title)
        return jsonify({"msg": "ignored (no cve-id in new issue title)"}), 200

    try:
        body = build_guide_comment_body(cve_id)
        _post_issue_comment(payload, body)
    except Exception as e:
        logger.exception("在新建 CVE Issue 下写入指导评论失败: %s", e)
        return jsonify({"msg": "failed to post guide comment", "error": str(e)}), 500

    return jsonify({"msg": "guide comment posted for new CVE issue", "cve_id": cve_id}), 200


