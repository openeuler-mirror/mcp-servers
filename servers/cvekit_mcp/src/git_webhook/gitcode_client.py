from typing import Dict, Any

import requests
from flask import jsonify

from config import logger, GITCODE_ACCESS_TOKEN, GITCODE_API_BASE
from common import extract_cve_id, build_guide_comment_body


def _post_gitcode_issue_comment(payload: Dict[str, Any], body: str) -> None:
    """
    在 GitCode Issue 下追加一条评论。

    说明：
      - 仅当配置了 GITCODE_ACCESS_TOKEN 时才会真正调用 GitCode OpenAPI；
      - 路径格式参考 GitCode Issues 接口文档：
          POST https://api.gitcode.com/api/v5/repos/:owner/:repo/issues/:number/comments
    """
    if not GITCODE_ACCESS_TOKEN:
        logger.info("未配置 GITCODE_ACCESS_TOKEN，跳过在 GitCode 上回复评论。")
        return

    project = payload.get("project") or payload.get("repository") or {}
    path_with_namespace = project.get("path_with_namespace") or project.get("full_name")

    # GitCode 的 Issue 信息：
    # - Issue Hook:   issue 信息在 object_attributes 中（含 iid）
    # - Note Hook:    issue 信息在 payload['issue'] 中（含 iid）
    issue = payload.get("issue") or payload.get("object_attributes") or {}
    issue_number = issue.get("iid") or issue.get("number")

    if not path_with_namespace or not issue_number:
        logger.warning("无法解析 GitCode 项目或 Issue 编号，跳过回复评论。")
        return

    try:
        owner, repo = path_with_namespace.split("/", 1)
    except ValueError:
        logger.warning("GitCode path_with_namespace 格式异常: %s", path_with_namespace)
        return

    # 这里沿用 GitCode 官方文档和你 curl 测试通过的方式：
    # 通过 query 参数 access_token 传递个人访问令牌，而不是使用 Authorization 头，
    # 避免出现 "404, token not found" 的问题。
    api_url = f"{GITCODE_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    headers = {
        "Content-Type": "application/json",
    }
    params = {"access_token": GITCODE_ACCESS_TOKEN}
    data = {"body": body}

    try:
        resp = requests.post(api_url, headers=headers, params=params, json=data, timeout=10)
        if not (200 <= resp.status_code < 300):
            logger.warning(
                "回复 GitCode 评论失败: status=%s, resp=%s",
                resp.status_code,
                resp.text[:500],
            )
        else:
            logger.info(
                "已在 GitCode Issue %s 下回复评论，内容前 200 字: %s",
                issue_number,
                body.replace("\n", "\\n")[:200],
            )
    except Exception as e:
        logger.exception("调用 GitCode API 回复评论失败: %s", e)


def reply_gitcode_issue_comment(payload: Dict[str, Any], cve_id: str) -> None:
    """
    在 GitCode Issue 下回复一条“已触发 CVE 修复服务”的确认评论。
    """
    body = f"已触发 CVE 修复服务，CVE-ID: {cve_id}。\nprovided by DevStation."
    _post_gitcode_issue_comment(payload, body)


def handle_gitcode_issue_created_webhook(payload: Dict[str, Any]):
    """
    处理 GitCode Issue Hook：新建 CVE Issue 时自动回复使用指引评论。
    """
    attrs = payload.get("object_attributes") or {}
    action = (attrs.get("action") or "").lower()

    # 只在新建（open/opened）场景下尝试解析 CVE-ID，其它操作直接忽略
    if action not in {"open", "opened", ""}:
        logger.info("GitCode Issue 动作非 open/opened(action=%s)，忽略。", action)
        return jsonify({"msg": "ignored (gitcode issue action not open)"}), 200

    title = attrs.get("title") or ""
    cve_id = extract_cve_id(title) or ""

    if not cve_id:
        logger.info("GitCode 新建 Issue 标题中未识别到 CVE-ID，跳过。title=%s", title)
        return jsonify({"msg": "ignored (no cve-id in gitcode issue title)"}), 200

    logger.info(
        "检测到 GitCode 新建 CVE Issue，CVE-ID: %s, url=%s",
        cve_id,
        attrs.get("url"),
    )

    # 在 GitCode Issue 下回复与 Gitee 一致的“使用指引”评论
    try:
        body = build_guide_comment_body(cve_id)
        _post_gitcode_issue_comment(payload, body)
    except Exception as e:
        logger.exception("在 GitCode 新建 CVE Issue 下写入指导评论失败: %s", e)

    resp = {"msg": "gitcode cve issue received", "cve_id": cve_id, "action": "issue-open"}
    return jsonify(resp), 200


