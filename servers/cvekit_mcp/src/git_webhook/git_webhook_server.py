#!/usr/bin/env python3

import os
from typing import Dict, Any

from flask import Flask, request, jsonify

import uuid

# 加载 .env（容器中通过 -e 传入，本地开发时从 .env 读取）
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), '..', 'cve_service', '.env')
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

from config import (
    logger,
    GITEE_WEBHOOK_TOKEN,
    GITCODE_WEBHOOK_TOKEN,
    MIGRATE_WEBHOOK_TOKEN,
    DEFAULT_CLONE_DIR,
    DEFAULT_BACKPORT_ENGINE,
)
from common import (
    extract_cve_id,
    _handle_comment_commands,
    build_guide_comment_body,
    TASK_QUEUE,
)
from worker import _start_workers
from gitee_client import _handle_issue_created_webhook
from gitcode_client import handle_gitcode_issue_created_webhook
from migrate_client import (
    validate_migrate_params,
    parse_pr_url,
    parse_target_repo_url,
    MigrateError,
)
from migrate_worker import (
    get_task_result,
)


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


# ---- PR 迁移接口 ----

@app.route("/migrate/pr", methods=["POST"])
def migrate_pr():
    """
    PR 代码迁移接口。
    接收迁移请求，校验参数后入队，返回 202 及 task_id。
    后台 Worker 通过 app_client.py --action pr-migration 执行迁移。
    """
    # 1. 校验 Token
    if MIGRATE_WEBHOOK_TOKEN:
        token = request.headers.get("X-Webhook-Token", "")
        if token != MIGRATE_WEBHOOK_TOKEN:
            logger.warning("收到非法迁移请求，X-Webhook-Token 不匹配。")
            return jsonify({"code": 403, "message": "invalid token"}), 403

    data = request.get_json(silent=True) or {}

    # 2. 参数校验
    errors = validate_migrate_params(data)
    if errors:
        return jsonify({"code": 400, "message": "参数校验失败", "errors": errors}), 400

    source_pr_url = data["source_pr_url"].strip()
    commit_id = data["commit_id"].strip()
    signer_name = data["signer_name"].strip()
    signer_email = data["signer_email"].strip()
    target_repo_url = data["target_repo_url"].strip()
    target_branch = (data.get("target_branch") or "main").strip()
    message = (data.get("message") or "").strip() or None
    clone_dir = (data.get("clone_dir") or DEFAULT_CLONE_DIR).strip()
    if not clone_dir.endswith("/"):
        clone_dir += "/"
    backport_engine = "mystique"  # pr-migration 写死使用 mystique 引擎
    task_id = str(uuid.uuid4())

    # 3. 从 URL 解析出 project_dir 和 target_path
    project_dir = ""
    target_path = ""
    try:
        src_info = parse_pr_url(source_pr_url)
        project_dir = f"{clone_dir}{src_info['owner']}/{src_info['repo']}"
    except MigrateError:
        project_dir = clone_dir.rstrip("/")
    try:
        tgt_info = parse_target_repo_url(target_repo_url)
        target_path = f"{clone_dir}{tgt_info['owner']}/{tgt_info['repo']}"
    except MigrateError:
        target_path = clone_dir.rstrip("/")

    # 4. 构建任务并入 TASK_QUEUE，由现有 Worker 统一调度
    task = {
        "task_id": task_id,
        "cve_id": "",  # pr-migration 不依赖 cve_id
        "payload": {},
        "action": "pr-migration",
        "commit_id": commit_id,
        "source_pr_url": source_pr_url,
        "signer_name": signer_name,
        "signer_email": signer_email,
        "target_repo_url": target_repo_url,
        "target_branch": target_branch,
        "message": message,
        "project_dir": project_dir,
        "target_path": target_path,
        "clone_dir": clone_dir,
        "backport_engine": backport_engine,
    }

    try:
        TASK_QUEUE.put(task)
        logger.info(
            "迁移任务已入队: task_id=%s, commit=%s, engine=%s, project_dir=%s, target_path=%s",
            task_id, commit_id[:12], backport_engine, project_dir, target_path,
        )
    except Exception as e:
        logger.exception("迁移任务入队失败: %s", e)
        return jsonify({"code": 500, "message": "任务入队失败", "data": {"error": str(e)}}), 500

    return jsonify({
        "code": 0,
        "message": "迁移任务已提交",
        "data": {
            "task_id": task_id,
            "source_pr_url": source_pr_url,
            "commit_id": commit_id,
            "target_repo_url": target_repo_url,
            "target_branch": target_branch,
            "project_dir": project_dir,
            "target_path": target_path,
            "clone_dir": clone_dir,
            "backport_engine": backport_engine,
            "status": "pending",
        },
    }), 202


@app.route("/migrate/pr/<task_id>", methods=["GET"])
def query_migrate_task(task_id: str):
    """
    查询迁移任务状态。
    GET /migrate/pr/{task_id}
    """
    result = get_task_result(task_id)
    if not result:
        return jsonify({"code": 404, "message": "任务不存在或已过期"}), 404

    return jsonify({"code": 0, "message": "ok", "data": result}), 200


if __name__ == "__main__":
    # 启动后台 Worker 线程
    _start_workers()

    # 固定监听 6002 端口
    port = 6000
    logger.info("启动 CVE WebHook 服务（带内存消息队列），监听端口 %d ...", port)
    app.run(host="0.0.0.0", port=port)