import os
import threading
import subprocess
import json
from typing import Dict, Any, List

from config import (
    logger,
    APP_CLIENT_LOG,
    BRANCHES_ANALYSIS_CACHE_FILE,
    APP_WORK_DIR,
    APP_CLIENT_FILENAME,
    VENV_PYTHON,
)
from common import (
    TASK_QUEUE,
    RESULT_QUEUE,
    _format_branches_table,
    _format_final_summary_table,
    _extract_prs_from_final_artifact,
)
from a2a_handlers import (
    _handle_status_update_event,
    _handle_artifact_update_event,
)
from gitee_client import _post_issue_comment
from gitcode_client import _post_gitcode_issue_comment


def run_app_client(
    cve_id: str,
    payload: Dict[str, Any],
    action: str = "pipeline",
    branches: List[str] | None = None,
    signer_name: str | None = None,
    signer_email: str | None = None,
) -> None:
    """
    调用本地 app_client.py 脚本，例如：
      - 分支分析：
          python app_client.py --cve-id CVE-2025-38051 --action branches-analysis
      - 全流程（pipeline），带多分支和签名信息：
          python app_client.py --cve-id CVE-2025-38051 --action pipeline \\
              --branches OLK-6.6,OLK-6.12 \\
              --signer-name "张三" --signer-email "zhangsan@example.com"

    注意：
      - 根据 action 选择不同模式：
          * branches-analysis：仅做分支分析
          * pipeline：分支分析 + 自动创建 PR，可携带多分支和签名信息
      - 通过 branches / signer_name / signer_email 进一步控制行为。
      - 在 APP_WORK_DIR 目录下、使用虚拟环境执行。
    """
    if not cve_id:
        logger.info("没有解析出任何 CVE-ID，不触发脚本。")
        return

    # 直接调用虚拟环境中的 python，可避免依赖 shell 和 source
    cmd = [
        VENV_PYTHON,
        APP_CLIENT_FILENAME,
        "--cve-id",
        cve_id,
        "--action",
        action,
    ]

    # 对于需要分支和签名信息的 action（目前是 pipeline / patch-apply-pr-creation）
    if action in {"pipeline", "patch-apply-pr-creation"}:
        if branches:
            # app_client.py 使用 --branches 参数，多个分支用逗号拼接
            branch_arg = ",".join(branches)
            cmd.extend(["--branches", branch_arg])
        if signer_name:
            cmd.extend(["--signer-name", signer_name])
        if signer_email:
            cmd.extend(["--signer-email", signer_email])

    logger.info("准备执行命令 (cwd=%s): %s", APP_WORK_DIR, " ".join(cmd))

    # 注意：此函数会被 Worker 线程同步调用（阻塞直到任务执行完成）
    # 这里不再依赖 cvekit 的缓存文件，而是实时解析 app_client.py 的日志输出，
    # 并将关键信息推送到 RESULT_QUEUE，由结果 Worker 负责写入 Issue 评论。
    try:
        log_dir = os.path.dirname(APP_CLIENT_LOG)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        # 标记是否已经向 RESULT_QUEUE 报告过一次「整体任务失败」（例如后端超时）
        reported_task_error = False

        # 使用 Popen 以便实时读取 stdout
        with open(APP_CLIENT_LOG, "a", buffering=1) as log_fp:  # 行缓冲
            process = subprocess.Popen(
                cmd,
                cwd=APP_WORK_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            assert process.stdout is not None

            for raw_line in process.stdout:
                # 写入日志文件，方便排查问题（相当于 tee）
                log_fp.write(raw_line)
                log_fp.flush()

                line = raw_line.strip()
                if not line:
                    continue

                # 典型格式为：INFO:root:{"contextId": "...", ...}
                # 尝试提取 JSON 部分进行解析
                json_start = line.find("{")
                if json_start < 0:
                    continue

                json_str = line[json_start:]
                try:
                    data = json.loads(json_str)
                except Exception:
                    # 非 JSON 行忽略
                    continue

                # 只关心 A2A 返回的 result 对象
                result_obj = data
                kind = result_obj.get("kind")
                logger.debug("收到 A2A 结果事件: kind=%s, contextId=%s", kind, result_obj.get("contextId"))

                if kind == "status-update":
                    reported_task_error = _handle_status_update_event(
                        result_obj=result_obj,
                        cve_id=cve_id,
                        action=action,
                        payload=payload,
                        reported_task_error=reported_task_error,
                    )
                elif kind == "artifact-update":
                    _handle_artifact_update_event(
                        result_obj=result_obj,
                        cve_id=cve_id,
                        action=action,
                        payload=payload,
                    )

            # 等待子进程结束
            returncode = process.wait()

        if returncode != 0:
            logger.warning("app_client.py 退出码非零: %s, CVE-ID: %s", returncode, cve_id)
            # 将错误信息放入结果队列，结果 Worker 会写入 Issue 评论
            RESULT_QUEUE.put(
                {
                    "event": "error",
                    "cve_id": cve_id,
                    "payload": payload,
                    "error": f"app_client.py 退出码非零: {returncode}",
                    "action": action,
                }
            )
        else:
            logger.info("app_client.py 执行完成，CVE-ID: %s", cve_id)
    except Exception as e:
        logger.exception("调用 app_client.py 失败: %s", e)
        # 将异常也发送到结果队列
        RESULT_QUEUE.put(
            {
                "event": "error",
                "cve_id": cve_id,
                "payload": payload,
                "error": str(e),
                "action": action,
            }
        )
        raise


def _task_worker_loop(worker_id: int) -> None:
    """
    任务 Worker：
      - 从 TASK_QUEUE 中取出任务
      - 同步执行 app_client.py
      - 将执行过程中解析出的结果事件写入 RESULT_QUEUE
    """
    logger.info("任务 Worker-%d 启动。", worker_id)
    while True:
        task = TASK_QUEUE.get()
        try:
            cve_id = task.get("cve_id")
            payload = task.get("payload") or {}
            action = task.get("action") or "pipeline"
            branches = task.get("branches") or None
            signer_name = task.get("signer_name") or None
            signer_email = task.get("signer_email") or None

            logger.info(
                "Worker-%d 开始处理任务，CVE-ID: %s, action=%s, branches=%s, signer_name=%s, signer_email=%s",
                worker_id,
                cve_id,
                action,
                ",".join(branches) if branches else "",
                signer_name or "",
                signer_email or "",
            )

            # 执行 app_client，同步等待完成（结果由 run_app_client 内部写入 RESULT_QUEUE）
            try:
                run_app_client(
                    cve_id,
                    payload,
                    action=action,
                    branches=branches,
                    signer_name=signer_name,
                    signer_email=signer_email,
                )
            except Exception as e:
                logger.exception(
                    "Worker-%d 执行 app_client 失败，CVE-ID: %s，action=%s，error=%s",
                    worker_id,
                    cve_id,
                    action,
                    e,
                )
                continue
            logger.info("Worker-%d 已完成任务执行，CVE-ID: %s, action=%s", worker_id, cve_id, action)
        except Exception as e:
            logger.exception("Worker-%d 处理任务时发生未捕获异常: %s", worker_id, e)
        finally:
            TASK_QUEUE.task_done()


def _result_worker_loop(worker_id: int) -> None:
    """
    结果 Worker：
      - 从 RESULT_QUEUE 中取出结果事件
      - 根据 items / error / artifact 等生成最终评论内容
      - 调用 Gitee/GitCode API 在 Issue 下追加评论
    """
    logger.info("结果 Worker-%d 启动。", worker_id)

    # 进程内简单维护一些状态：
    # - pr_state: {cve_id: {branch: pr_url}}       便于按 CVE 聚合 PR 信息
    # - branches_state: {cve_id: items}            便于在 final_result 阶段生成完整表格
    # - action_state: {cve_id: action_str}         记录该 CVE 对应任务的 action 类型（branches-analysis / pipeline 等）
    pr_state: Dict[str, Dict[str, str]] = {}
    branches_state: Dict[str, List[Dict[str, Any]]] = {}
    action_state: Dict[str, str] = {}
    while True:
        result = RESULT_QUEUE.get()
        try:
            event = result.get("event") or "legacy"
            cve_id = result.get("cve_id")
            payload = result.get("payload") or {}

            # 记录该 CVE 的 action 类型，区分 /analysis_branches 与 /create_pr(pipeline)
            action = (result.get("action") or "").strip()
            if cve_id and action:
                action_state[cve_id] = action

            logger.info(
                "结果 Worker-%d 取到事件: event=%s, CVE-ID=%s, action=%s",
                worker_id,
                event,
                cve_id,
                action_state.get(cve_id, "") or "UNKNOWN",
            )

            # 兼容旧格式（不带 event），目前理论上不会再出现
            if event == "legacy":
                items = result.get("items")
                error = result.get("error")
                if error:
                    body = (
                        f"⚠️ CVE 修复任务执行失败，CVE-ID: {cve_id}。\n"
                        f"错误信息：`{error}`。\n"
                        f"请检查服务器上的 app_client 日志（例如 `{APP_CLIENT_LOG}`）。\n"
                        f"provided by DevStation."
                    )
                elif items:
                    body = _format_branches_table(cve_id, items)
                else:
                    body = (
                        f"已完成 CVE 修复任务，但未在缓存中找到分支分析结果，CVE-ID: {cve_id}。\n"
                        f"请检查 cvekit 日志与缓存目录：`{BRANCHES_ANALYSIS_CACHE_FILE}`。\n"
                        f"provided by DevStation."
                    )
            elif event == "error":
                error = result.get("error") or "未知错误"
                body = (
                    f"⚠️ CVE 修复任务执行失败，CVE-ID: {cve_id}。\n"
                    f"错误信息：`{error}`。\n"
                    f"请检查服务器上的 app_client 日志（例如 `{APP_CLIENT_LOG}`）。\n"
                    f"provided by DevStation."
                )
            elif event == "branches_analysis_raw":
                # analyze_branches 的原始结果文本（无法结构化解析），直接完整展示给用户
                raw_text = result.get("raw_text") or ""
                if not raw_text:
                    logger.warning(
                        "结果 Worker-%d 收到 branches_analysis_raw 事件但缺少 raw_text，CVE-ID: %s",
                        worker_id,
                        cve_id,
                    )
                    RESULT_QUEUE.task_done()
                    continue

                logger.info(
                    "结果 Worker-%d 收到 branches_analysis_raw 事件，CVE-ID: %s，将直接回写原始分析结果文本。",
                    worker_id,
                    cve_id,
                )
                body_lines: List[str] = []
                body_lines.append(f"已完成 CVE 修复分支分析，CVE-ID: **{cve_id}**。")
                body_lines.append("")
                body_lines.append("以下为后端智能体返回的完整原始分支分析结果（按要求不做删减）：")
                body_lines.append("")
                body_lines.append("```")
                body_lines.append(raw_text)
                body_lines.append("```")
                body_lines.append("")
                body_lines.append("provided by DevStation.")
                body = "\n".join(body_lines)
            elif event == "get_commits_error":
                # 在 get_commits 步骤未能获取到 introduced/fixed commit，无法继续后续流程。
                error = result.get("error") or "未能获取到漏洞相关的引入/修复提交信息"
                body_lines = [
                    f"⚠️ CVE 修复任务在获取提交信息步骤（get_commits）失败，CVE-ID: {cve_id}。",
                    "",
                    f"原因：`{error}`。",
                    "",
                    "在未能找到完整的引入/修复提交（introduced / fixed commit）之前，系统无法继续后续的分支分析和自动创建 PR 流程。",
                    "",
                    "建议：",
                    "1. 确认 CVE ID 是否填写正确；",
                    "2. 查看上游社区/内核仓库的安全公告或提交历史，尝试人工定位相关提交；",
                    "3. 如该 CVE 为新近分配，可能暂未公开完整修复信息，可联系维护者或安全团队确认。",
                    "",
                    "provided by DevStation.",
                ]
                body = "\n".join(body_lines)
            elif event == "branches_analysis":
                items = result.get("items") or []
                # 记录分支分析结果，供后续使用
                branches_state[cve_id] = items

                # 区分两类场景：
                #   1) /analysis_branches（action=branches-analysis）：只需要“分支影响状态表格”，无需最终汇总表
                #   2) /create_pr（pipeline）：仅作为中间结果，不在此处重复输出表格，最终由 final_result 统一输出完整表
                act = action_state.get(cve_id, "")
                logger.info(
                    "结果 Worker-%d 收到 branches_analysis 事件，CVE-ID: %s，分支数=%d, action=%s，当前已缓存分支分析 CVEs=%d, PR CVEs=%d",
                    worker_id,
                    cve_id,
                    len(items),
                    act or "UNKNOWN",
                    len(branches_state),
                    len(pr_state),
                )
                if act == "branches-analysis":
                    body = _format_branches_table(cve_id, items)
                else:
                    # 对于 pipeline 等场景，这里仅缓存结果，不输出评论
                    continue
            elif event == "pr_failed":
                branch = (result.get("branch") or "").strip() or "-"
                error_text = (result.get("error") or "").strip() or "PR 创建失败（原因未知）"
                act = action_state.get(cve_id, "")
                logger.info(
                    "结果 Worker-%d 收到 pr_failed 事件，CVE-ID: %s，branch=%s, error=%s, action=%s",
                    worker_id,
                    cve_id,
                    branch,
                    error_text[:200],
                    act or "UNKNOWN",
                )
                pr_map = pr_state.setdefault(cve_id, {})
                pr_map[branch] = error_text

                # pipeline 场景下，最终会通过 final_result 输出带错误信息的汇总表格，这里不再单独发评论
                if act == "pipeline":
                    continue

                # 其他场景（理论上很少），直接输出一条错误说明评论
                lines = []
                lines.append(f"在为 CVE-ID **{cve_id}** 处理分支 `{branch}` 的 PR 时发生错误：")
                lines.append("")
                lines.append(f"- `{error_text}`")
                lines.append("\nprovided by DevStation.")
                body = "\n".join(lines)
            elif event == "pr_created":
                branch = (result.get("branch") or "").strip() or "-"
                pr_url = (result.get("pr_url") or "").strip()
                if not pr_url:
                    logger.warning(
                        "结果 Worker-%d 收到 pr_created 事件但缺少 pr_url，CVE-ID: %s, branch=%s",
                        worker_id,
                        cve_id,
                        branch,
                    )
                    continue
                act = action_state.get(cve_id, "")
                logger.info(
                    "结果 Worker-%d 收到 pr_created 事件，CVE-ID: %s，branch=%s, pr_url=%s, action=%s，将记录到 PR 状态中。",
                    worker_id,
                    cve_id,
                    branch,
                    pr_url,
                    act or "UNKNOWN",
                )
                pr_map = pr_state.setdefault(cve_id, {})
                pr_map[branch] = pr_url

                # 对于 pipeline 场景，最终会通过 final_result 输出“完整汇总表格”，
                # 这里不再额外输出“仅 PR 列表”的中间表格，以免重复。
                if act == "pipeline":
                    continue

                # 其他场景（理论上很少用到），保留原来的“按 CVE 聚合 PR 列表”的输出行为
                lines = []
                lines.append(f"已为 CVE-ID **{cve_id}** 创建/更新以下分支的 PR：")
                lines.append("")
                lines.append("| 目标分支 | PR 链接 |")
                lines.append("| -------- | ------- |")
                for b in sorted(pr_map.keys()):
                    url = pr_map[b]
                    lines.append(f"| {b} | [查看PR]({url}) |")
                lines.append("\nprovided by DevStation.")
                body = "\n".join(lines)
            elif event == "final_result":
                # final_result 触发“全流程汇总”表格输出
                artifact = result.get("artifact") or {}
                extra_prs = _extract_prs_from_final_artifact(artifact)
                if extra_prs:
                    logger.info(
                        "结果 Worker-%d 从 final_result 中提取到 PR 信息，CVE-ID: %s，条目数=%d（将在现有 PR 映射上进行合并）",
                        worker_id,
                        cve_id,
                        len(extra_prs),
                    )
                    pr_map0 = pr_state.setdefault(cve_id, {})
                    pr_map0.update(extra_prs)

                items = branches_state.get(cve_id) or []
                pr_map = pr_state.get(cve_id, {})
                act = action_state.get(cve_id, "")

                # 对于纯 /analysis_branches 场景（action=branches-analysis），只保留之前的分支分析表格
                if act == "branches-analysis":
                    logger.info(
                        "结果 Worker-%d 收到 final_result 事件但 action=branches-analysis，仅保留之前的分支分析表格，CVE-ID: %s（不会输出最终汇总表）",
                        worker_id,
                        cve_id,
                    )
                    continue

                if not items and not pr_map:
                    logger.info(
                        "结果 Worker-%d 收到 final_result 事件，但尚无分支或 PR 信息，CVE-ID: %s（跳过最终汇总表输出）",
                        worker_id,
                        cve_id,
                    )
                    continue
                logger.info(
                    "结果 Worker-%d 收到 final_result 事件，CVE-ID: %s，分支数=%d, PR数=%d，将生成最终汇总表。",
                    worker_id,
                    cve_id,
                    len(items),
                    len(pr_map),
                )
                body = _format_final_summary_table(cve_id, items, pr_map)
            else:
                # 未知事件类型，记录日志但不写评论
                logger.warning(
                    "结果 Worker-%d 收到未知事件类型: %s, CVE-ID: %s",
                    worker_id,
                    event,
                    cve_id,
                )
                continue

            # 根据 payload 判断是 Gitee 还是 GitCode，分别调用对应的评论接口
            try:
                if (payload.get("object_kind") or payload.get("event_type")):
                    _post_gitcode_issue_comment(payload, body)
                else:
                    _post_issue_comment(payload, body)
            except Exception as e:
                logger.exception("结果 Worker-%d 写入评论失败，CVE-ID: %s，error=%s", worker_id, cve_id, e)
        except Exception as e:
            logger.exception("结果 Worker-%d 处理结果时发生未捕获异常: %s", worker_id, e)
        finally:
            RESULT_QUEUE.task_done()


def _start_workers() -> None:
    """
    启动任务 Worker 和结果 Worker。
    """
    task_workers = int(os.environ.get("TASK_WORKERS", "2"))
    result_workers = int(os.environ.get("RESULT_WORKERS", "1"))

    for i in range(task_workers):
        t = threading.Thread(
            target=_task_worker_loop,
            args=(i + 1,),
            daemon=True,
        )
        t.start()

    for i in range(result_workers):
        t = threading.Thread(
            target=_result_worker_loop,
            args=(i + 1,),
            daemon=True,
        )
        t.start()


