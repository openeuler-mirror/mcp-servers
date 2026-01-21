#!/usr/bin/env python3

from typing import Dict, Any

from flask import Flask, request, jsonify

from config import (
    logger,
    GITEE_WEBHOOK_TOKEN,
    GITCODE_WEBHOOK_TOKEN,
)
from common import (
    extract_cve_id,
    _handle_comment_commands,
    build_guide_comment_body,
)
from worker import _start_workers
from gitee_client import _handle_issue_created_webhook
from gitcode_client import handle_gitcode_issue_created_webhook


app = Flask(__name__)


@app.route("/gitcode/webhook", methods=["POST"])
def gitcode_webhook():
    """
    GitCode WebHook 回调入口（Issue + Note）。
    """
    # 1. 校验 WebHook 密码（可选）
    if GITCODE_WEBHOOK_TOKEN:
        token = request.headers.get("X-GitCode-Token", "")
        if token != GITCODE_WEBHOOK_TOKEN:
            logger.warning("收到非法 GitCode WebHook 请求，X-GitCode-Token 不匹配。")
            return jsonify({"msg": "invalid token for gitcode"}), 403

    payload = request.get_json(silent=True) or {}
    logger.info(
        "收到 GitCode WebHook: X-GitCode-Event=%s, object_kind=%s, event_type=%s, issue_url=%s",
        request.headers.get("X-GitCode-Event"),
        payload.get("object_kind"),
        payload.get("event_type"),
        (payload.get("object_attributes") or {}).get("url"),
    )

    event_type = (payload.get("event_type") or "").lower()
    object_kind = (payload.get("object_kind") or "").lower()

    # ---------- 1. 处理 Issue Hook：新建 Issue 场景 ----------
    if event_type == "issue" and object_kind == "issue":
        # 具体的 GitCode 新建 Issue 处理逻辑下沉到 gitcode_client 中
        return handle_gitcode_issue_created_webhook(payload)

    # ---------- 2. 处理 Note Hook：Issue 评论指令 ----------
    if event_type == "note" and object_kind == "note":
        attrs = payload.get("object_attributes") or {}
        note = attrs.get("note") or attrs.get("description") or ""
        issue_obj = payload.get("issue") or {}
        issue_title = issue_obj.get("title") or ""

        logger.info("GitCode Note 评论内容: %s", note)

        resp = _handle_comment_commands(
            payload,
            issue_title=issue_title,
            comment_body=note,
            allow_reply_comment=True,
            platform="gitcode",
        )
        if resp is not None:
            return resp

        return jsonify(
            {
                "msg": "ignored (no /analysis_branches or /create_pr command in gitcode note)",
                "event_type": event_type,
                "object_kind": object_kind,
            }
        ), 200

    # 其它 GitCode 事件暂不处理，直接返回 200，避免 WebHook 多次重试
    return jsonify(
        {
            "msg": "ignored (unsupported gitcode event)",
            "event_type": event_type,
            "object_kind": object_kind,
        }
    ), 200


@app.route("/gitee/webhook", methods=["POST"])
def gitee_webhook():
    """
    Gitee WebHook 回调入口。
    """
    # 1. 校验 WebHook 密码（可选但强烈建议开启）
    if GITEE_WEBHOOK_TOKEN:
        token = request.headers.get("X-Gitee-Token", "")
        if token != GITEE_WEBHOOK_TOKEN:
            logger.warning("收到非法 WebHook 请求，X-Gitee-Token 不匹配。")
            return jsonify({"msg": "invalid token"}), 403

    payload = request.get_json(silent=True) or {}
    logger.info(
        "收到 Gitee WebHook: hook_name=%s, X-GIT-OSCHINA-EVENT=%s, X-Gitee-Event=%s",
        payload.get("hook_name"),
        request.headers.get("X-GIT-OSCHINA-EVENT"),
        request.headers.get("X-Gitee-Event"),
    )

    hook_name = (payload.get("hook_name") or payload.get("hookName") or "").lower()

    # ---------- 0. 处理新建 Issue 类事件：自动回复使用指引 ----------
    # Gitee 的 Issue 相关 hook_name 一般为 issue_hooks，这里做一个宽松匹配
    if hook_name in {"issue_hooks", "issues"}:
        return _handle_issue_created_webhook(payload)

    # Gitee Issue 评论事件通常为 note_hooks，这里同时兼容历史的 comment 命名
    valid_comment_hooks = {"comment", "note_hooks"}
    if hook_name not in valid_comment_hooks:
        return jsonify({"msg": "ignored (not comment/note event)"}), 200

    comment_body = (payload.get("comment") or {}).get("body") or ""
    logger.info("评论内容: %s", comment_body)

    issue_title = (payload.get("issue") or {}).get("title") or ""
    return _handle_comment_commands(
        payload,
        issue_title=issue_title,
        comment_body=comment_body,
        allow_reply_comment=True,
        platform="gitee",
    )


if __name__ == "__main__":
    # 启动后台 Worker 线程
    _start_workers()

    # 固定监听 6002 端口
    port = 6000
    logger.info("启动 CVE WebHook 服务（带内存消息队列），监听端口 %d ...", port)
    app.run(host="0.0.0.0", port=port)