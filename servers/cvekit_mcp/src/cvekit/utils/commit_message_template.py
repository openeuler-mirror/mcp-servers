from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import git

from .apply_patch import extract_commit_message_from_patch

logger = logging.getLogger(__name__)

DEFAULT_COMMIT_MESSAGE_TEMPLATE = """{{subject}}

commit {{commit_id}} {{source}}

{{body}}

{{trailers}}"""

DEFAULT_LINUX_REPO_PATH = "~/Image/linux"

TRAILER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*-by:\s+.+")
VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
SHA_RE = re.compile(r"\b[0-9a-fA-F]{7,40}\b")

ALLOWED_TEMPLATE_VARIABLES = {
    "subject",
    "commit_id",
    "source",
    "body",
    "trailers",
    "reference",
    "upstream_commit_id",
    "openeuler_commit_id",
}


@dataclass
class ParsedCommitMessage:
    subject: str = ""
    body: str = ""
    trailers: str = ""
    upstream_commit_id: str = ""
    reference: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str]:
        return {
            "subject": self.subject,
            "body": self.body,
            "trailers": self.trailers,
            "upstream_commit_id": self.upstream_commit_id,
            "reference": self.reference,
        }


@dataclass
class SourceDetectionResult:
    source: str
    commit_id: str
    method: str
    warning: str = ""

    def to_dict(self) -> dict[str, str]:
        result = {
            "source": self.source,
            "commit_id": self.commit_id,
            "method": self.method,
        }
        if self.warning:
            result["warning"] = self.warning
        return result


class CommitMessageParser:
    def parse_patch_file(self, patch_path: str) -> ParsedCommitMessage:
        message, _ = extract_commit_message_from_patch(patch_path)
        return self.parse(message)

    def parse(self, raw_message: str) -> ParsedCommitMessage:
        text = (raw_message or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return ParsedCommitMessage()

        lines = text.split("\n")
        subject = lines[0].strip()
        rest = lines[1:]
        while rest and not rest[0].strip():
            rest.pop(0)

        metadata_lines, content_lines = self._split_metadata_block(rest)
        metadata = self._parse_metadata(metadata_lines)
        if not metadata.get("upstream_commit_id"):
            # 有些补丁不会把 upstream sha 放在 openEuler metadata block 里，
            # 而是作为正文里的 "[ Upstream commit ... ]" 或单独 "commit ..." 行出现。
            upstream_commit_id = self._extract_upstream_commit_from_text(text)
            if upstream_commit_id:
                metadata["upstream_commit_id"] = upstream_commit_id
        body, trailers = self._split_body_and_trailers(content_lines)

        return ParsedCommitMessage(
            subject=subject,
            body=body,
            trailers=trailers,
            upstream_commit_id=metadata.get("upstream_commit_id", ""),
            reference=metadata.get("reference", ""),
            metadata=metadata,
        )

    def _split_metadata_block(self, lines: list[str]) -> tuple[list[str], list[str]]:
        separator_idx = None
        for idx, line in enumerate(lines):
            if re.match(r"^-{8,}\s*$", line.strip()):
                separator_idx = idx
                break
        if separator_idx is not None:
            content = lines[separator_idx + 1 :]
            while content and not content[0].strip():
                content.pop(0)
            return lines[:separator_idx], content

        metadata: list[str] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if not line.strip():
                if metadata:
                    metadata.append(line)
                    idx += 1
                    continue
                break
            if not self._is_metadata_line(line):
                break
            metadata.append(line)
            idx += 1

        while metadata and not metadata[-1].strip():
            metadata.pop()
        content = lines[idx:]
        while content and not content[0].strip():
            content.pop(0)
        return metadata, content

    def _is_metadata_line(self, line: str) -> bool:
        stripped = line.strip()
        return bool(
            stripped in {"stable inclusion", "mainline inclusion"}
            or re.match(r"^from\s+(stable|mainline)(?:-|$)", stripped)
            or re.match(r"^commit\s+[0-9a-fA-F]{7,40}\s*$", stripped)
            or re.match(r"^Reference:\s*", stripped)
        )

    def _parse_metadata(self, lines: list[str]) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            commit_match = re.match(r"^commit\s+([0-9a-fA-F]{7,40})\s*$", stripped)
            if commit_match:
                metadata["upstream_commit_id"] = commit_match.group(1)
                continue
            reference_match = re.match(r"^Reference:\s*(.*)$", stripped)
            if reference_match:
                value = reference_match.group(1).strip()
                metadata["reference"] = value
                ref_commit = self._extract_commit_from_reference(value)
                if ref_commit:
                    metadata["upstream_commit_id"] = ref_commit
        return metadata

    def _extract_upstream_commit_from_text(self, text: str) -> str:
        for line in (text or "").splitlines():
            stripped = line.strip()
            upstream_match = re.match(r"^\[\s*Upstream commit ([0-9a-fA-F]{7,40})\s*\]$", stripped)
            if upstream_match:
                return upstream_match.group(1)
            commit_match = re.match(r"^commit\s+([0-9a-fA-F]{7,40})\s*$", stripped)
            if commit_match:
                return commit_match.group(1)
        return ""

    def _extract_commit_from_reference(self, reference: str) -> str:
        if "git.kernel.org" not in (reference or ""):
            return ""
        id_match = re.search(r"[?&]id=([0-9a-fA-F]{7,40})\b", reference)
        if id_match:
            return id_match.group(1)
        sha_match = SHA_RE.search(reference or "")
        return sha_match.group(0) if sha_match else ""

    def _split_body_and_trailers(self, lines: list[str]) -> tuple[str, str]:
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return "", ""

        idx = len(lines) - 1
        trailer_start = len(lines)
        while idx >= 0:
            line = lines[idx]
            if not line.strip():
                if trailer_start == len(lines):
                    idx -= 1
                    continue
                break
            if TRAILER_RE.match(line.strip()):
                trailer_start = idx
                idx -= 1
                continue
            break

        if trailer_start == len(lines):
            return "\n".join(lines).strip(), ""
        body_lines = lines[:trailer_start]
        trailer_lines = lines[trailer_start:]
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        return "\n".join(body_lines).strip(), "\n".join(trailer_lines).strip()


class SourceDetector:
    def __init__(self, linux_repo_path: str | None = None) -> None:
        self.linux_repo_path = os.path.expanduser(linux_repo_path or DEFAULT_LINUX_REPO_PATH)

    def detect(self, parsed: ParsedCommitMessage, openeuler_commit_id: str) -> SourceDetectionResult:
        openeuler_commit_id = str(openeuler_commit_id or "").strip()
        candidate = (parsed.upstream_commit_id or "").strip()
        if candidate:
            # candidate 可能来自 Reference、"[ Upstream commit ... ]" 或 "commit ..." 行；
            # 只有 Linux 仓库里能解析到它时，才把 commit message 渲染为 upstream 来源。
            if self._commit_exists(candidate):
                return SourceDetectionResult(
                    source="upstream",
                    commit_id=candidate,
                    method="reference_url",
                )
            logger.warning(
                "source detection: upstream candidate not found in linux repo: %s",
                candidate,
            )

        matches = self._find_commits_by_subject(parsed.subject)
        if len(matches) == 1:
            return SourceDetectionResult(
                source="upstream",
                commit_id=matches[0],
                method="subject_unique",
            )
        if len(matches) > 1:
            return SourceDetectionResult(
                source="openEuler",
                commit_id=openeuler_commit_id,
                method="fallback_openeuler",
                warning="未能唯一确认 upstream commit，已回退使用 openEuler commit。",
            )
        return SourceDetectionResult(
            source="openEuler",
            commit_id=openeuler_commit_id,
            method="fallback_openeuler",
            warning="未在 Linux 仓库中找到同标题 commit，使用 openEuler 源 commit。",
        )

    def _repo(self) -> git.Repo | None:
        if not self.linux_repo_path or not os.path.isdir(self.linux_repo_path):
            return None
        try:
            return git.Repo(self.linux_repo_path)
        except Exception as exc:
            logger.warning("source detection: invalid linux repo %s: %s", self.linux_repo_path, exc)
            return None

    def _commit_exists(self, commit_id: str) -> bool:
        repo = self._repo()
        if repo is None or not commit_id:
            return False
        try:
            repo.git.merge_base("--is-ancestor", commit_id, self._master_ref(repo))
            return True
        except Exception:
            return False

    def _master_ref(self, repo: git.Repo) -> str:
        for ref in ("origin/master", "upstream/master", "master"):
            try:
                repo.commit(ref)
                return ref
            except Exception:
                continue
        return "master"

    def _find_commits_by_subject(self, subject: str) -> list[str]:
        repo = self._repo()
        if repo is None or not subject:
            return []
        try:
            # commit message 的 upstream 判断只看 Linux master，避免其它分支/remote
            # 上的同标题 stable commit 把 source 判定扰乱。
            output = repo.git.log(
                self._master_ref(repo),
                "--format=%H%x00%s",
                "--fixed-strings",
                f"--grep={subject}",
            )
        except Exception as exc:
            logger.warning("source detection: subject search failed: %s", exc)
            return []
        matches: list[str] = []
        for line in output.splitlines():
            if "\x00" not in line:
                continue
            commit_id, found_subject = line.split("\x00", 1)
            if found_subject.strip() == subject.strip():
                matches.append(commit_id.strip())
        return list(dict.fromkeys(matches))


class CommitMessageRenderer:
    def validate_template(self, template: str) -> None:
        if not isinstance(template, str) or not template.strip():
            raise ValueError("commit message 模板不能为空")
        variables = set(VARIABLE_RE.findall(template))
        unknown = sorted(variables - ALLOWED_TEMPLATE_VARIABLES)
        if unknown:
            raise ValueError(f"模板变量 {{{{{unknown[0]}}}}} 不存在。")
        if "subject" not in variables:
            raise ValueError("commit message 模板必须包含 {{subject}}")

    def render(self, template: str, context: dict[str, Any]) -> str:
        self.validate_template(template)

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = context.get(key, "")
            return "" if value is None else str(value)

        rendered = VARIABLE_RE.sub(replace, template)
        rendered = self._normalize_blank_lines(rendered)
        if not rendered.strip():
            raise ValueError("渲染后的 commit message 不能为空")
        first_line = rendered.splitlines()[0].strip()
        if not first_line:
            raise ValueError("渲染后的 commit message 第一行不能为空")
        return rendered

    def _normalize_blank_lines(self, message: str) -> str:
        message = (message or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        message = re.sub(r"\n{3,}", "\n\n", message)
        return message + "\n"


def build_commit_message_preview(
    *,
    patch_path: str,
    openeuler_commit_id: str,
    template: str | None = None,
    linux_repo_path: str | None = None,
) -> dict[str, Any]:
    parser = CommitMessageParser()
    parsed = parser.parse_patch_file(patch_path)
    detection = SourceDetector(linux_repo_path).detect(parsed, openeuler_commit_id)
    context = {
        **parsed.to_dict(),
        "commit_id": detection.commit_id,
        "source": detection.source,
        "openeuler_commit_id": str(openeuler_commit_id or "").strip(),
    }
    rendered = CommitMessageRenderer().render(template or DEFAULT_COMMIT_MESSAGE_TEMPLATE, context)
    warnings = [detection.warning] if detection.warning else []
    return {
        "commit_message": rendered,
        "commit_message_preview": rendered,
        "commit_message_context": context,
        "source_detection": detection.to_dict(),
        "commit_message_warnings": warnings,
    }
