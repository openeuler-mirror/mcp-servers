from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

PROVIDER = "opencode"
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_MAX_ATTEMPTS = 3
MAX_RAW_TEXT_CHARS = 4000


def extract_touched_files(*patch_texts: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for patch_text in patch_texts:
        for line in patch_text.splitlines():
            path = ""
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) >= 4:
                    path = _normalize_patch_path(parts[3])
            elif line.startswith("+++ ") or line.startswith("--- "):
                path = _normalize_patch_path(line[4:].strip().split("\t", 1)[0])
            if path and path != "/dev/null" and path not in seen:
                seen.add(path)
                files.append(path)
    return files


def extract_last_text_from_jsonl(output: str) -> str:
    texts: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") != "text":
            continue
        part = item.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return texts[-1] if texts else ""


def summarize_conflict_item(
    *,
    target_branch: str,
    original_patch_path: str,
    backported_patch_path: str,
    target_path: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    try:
        original_patch = Path(original_patch_path).read_text(encoding="utf-8", errors="replace")
        backported_patch = Path(backported_patch_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _failed(f"failed to read patch file: {exc}")

    touched_files = extract_touched_files(original_patch, backported_patch)
    git_state, git_state_error = _capture_git_state(target_path)
    if git_state_error:
        return _failed(git_state_error)
    if git_state.get("status"):
        return _failed(
            "target repository is dirty before conflict summary; "
            "skip opencode to avoid losing existing changes"
        )

    prompt = _build_prompt(
        target_branch=target_branch,
        touched_files=touched_files,
        original_patch_path=original_patch_path,
        backported_patch_path=backported_patch_path,
    )

    attempts = max(1, int(max_attempts or 1))
    last_raw = ""
    last_summary = ""
    last_format_error = ""
    for attempt in range(1, attempts + 1):
        try:
            cmd = ["opencode", "run"]
            conflict_reporter_url = os.environ.get("CONFLICT_REPORTER_URL", "").strip()
            if conflict_reporter_url:
                cmd.extend(["--attach", conflict_reporter_url, "--dir", target_path])
            cmd.extend([
                "--format",
                "json",
                "--file",
                original_patch_path,
                "--file",
                backported_patch_path,
                prompt,
            ])
            completed = subprocess.run(
                cmd,
                cwd=target_path,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return _failed("opencode command not found")
        except subprocess.TimeoutExpired:
            return _failed(f"opencode timed out after {timeout_seconds}s")
        except OSError as exc:
            return _failed(f"failed to run opencode: {exc}")

        restore_error = _restore_if_opencode_changed_repo(target_path, git_state)
        if restore_error:
            return _failed(restore_error)

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            return _failed(f"opencode exited with code {completed.returncode}: {stderr}")

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        text = extract_last_text_from_jsonl(stdout)
        if not text:
            last_format_error = "opencode did not return a text response"
            last_raw = stdout
            last_summary = _summarize_opencode_output(stdout, stderr)
        else:
            last_raw = text
            last_summary = ""
            parsed = _parse_model_json(text)
            if isinstance(parsed, dict):
                return {
                    "status": "success",
                    "provider": PROVIDER,
                    "score": parsed.get("score"),
                    "reason": str(parsed.get("reason") or "").strip(),
                    "error": "",
                    "attempts": attempt,
                }
            last_format_error = "opencode returned non-JSON text"

        if attempt < attempts:
            logger.warning(
                "[backport-conflict-summary] %s; retrying attempt %d/%d",
                last_format_error,
                attempt + 1,
                attempts,
            )

    return _failed(
        last_format_error or "opencode returned non-JSON text",
        raw_text=last_raw,
        summary=last_summary,
    )


def _normalize_patch_path(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _capture_git_state(target_path: str) -> tuple[dict[str, str], str]:
    head = subprocess.run(
        ["git", "-C", target_path, "rev-parse", "HEAD"],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode != 0:
        return {}, f"failed to read target git HEAD: {(head.stderr or '').strip()}"
    status = subprocess.run(
        ["git", "-C", target_path, "status", "--porcelain"],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return {}, f"failed to read target git status: {(status.stderr or '').strip()}"
    return {
        "head": head.stdout.strip(),
        "status": status.stdout,
    }, ""


def _restore_if_opencode_changed_repo(target_path: str, before: dict[str, str]) -> str:
    after, error = _capture_git_state(target_path)
    if error:
        return error
    if after == before:
        return ""
    if before.get("status"):
        return (
            "opencode changed target repository, but it was already dirty before "
            "summary; skip automatic restore to avoid losing existing changes"
        )
    subprocess.run(
        ["git", "-C", target_path, "reset", "--hard", before["head"]],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["git", "-C", target_path, "clean", "-fd"],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    restored, restore_error = _capture_git_state(target_path)
    if restore_error:
        return restore_error
    if restored != before:
        return "opencode changed target repository and automatic restore did not return it to the original state"
    return ""


def _build_prompt(
    *,
    target_branch: str,
    touched_files: list[str],
    original_patch_path: str,
    backported_patch_path: str,
) -> str:
    files_text = "\n".join(f"- {path}" for path in touched_files) or "- unknown"
    return f"""你是一个 backport 补丁审查助手。

当前工作目录是目标仓库。
目标分支：{target_branch}

源补丁如果直接应用到这个目标分支会产生冲突。安全维护者已经把源补丁适配成
一份无冲突的目标分支补丁。请审查这份已解冲突补丁的质量：它是否正确解决了冲突，
是否保留了源补丁意图，以及是否可以正确应用到目标分支。

两份补丁已通过 --file 附加到本次 opencode 请求。
需要查看仓库上下文时，只检查这些补丁涉及的文件。
不要修改文件。不要运行网络命令。
你可以使用 git apply --check 验证补丁是否可应用，但不要真正应用补丁。

请为这份已解冲突补丁打分。
评分必须是 1 到 5 的数字；5 表示这份补丁很可能正确，1 表示这份补丁很可能错误。
reason 必须使用中文，简洁说明判断依据。
只返回一个 JSON 对象，不要输出 Markdown、解释文字或代码块。JSON 格式如下：
{{
  "score": 5,
  "reason": "中文原因"
}}

涉及文件：
{files_text}

原始补丁文件：
{original_patch_path}

已解冲突目标补丁文件：
{backported_patch_path}
"""


def _parse_model_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
        if match:
            stripped = match.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    json_object = _extract_first_json_object(stripped)
    if not json_object:
        return None
    try:
        return json.loads(json_object)
    except json.JSONDecodeError:
        return None


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return ""


def _summarize_opencode_output(stdout: str, stderr: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    type_counts: dict[str, int] = {}
    samples: list[str] = []
    non_json_lines = 0
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            non_json_lines += 1
            continue
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("type") or "<missing>")
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
        if len(samples) < 5:
            samples.append(f"type={event_type} keys={','.join(sorted(str(key) for key in item.keys()))}")
    parts = [
        f"stdout_lines={len(lines)}",
        f"stdout_chars={len(stdout)}",
        f"event_types={type_counts}",
        f"non_json_lines={non_json_lines}",
    ]
    if samples:
        parts.append(f"samples={samples}")
    stderr_tail = stderr.strip()[-1000:]
    if stderr_tail:
        parts.append(f"stderr_tail={stderr_tail}")
    return "; ".join(parts)


def _failed(message: str, *, raw_text: str = "", summary: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "failed",
        "provider": PROVIDER,
        "score": None,
        "reason": "",
        "error": message,
    }
    if raw_text:
        result["raw_text"] = raw_text[:MAX_RAW_TEXT_CHARS]
    if summary:
        result["summary"] = summary[:MAX_RAW_TEXT_CHARS]
    logger.warning("[backport-conflict-summary] %s", message)
    return result
