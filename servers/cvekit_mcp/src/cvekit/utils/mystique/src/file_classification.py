"""Classify non-code files before Mystique chooses a migration strategy."""

from __future__ import annotations

import os

from text_config_migration import is_text_config_path


SUPPORTED_MIGRATE = "supported_migrate"
DIRECT_APPLY_OPTIONAL = "direct_apply_optional"
NEED_HUMAN = "need_human"


def is_code_path(path: str) -> bool:
    return path.endswith((".c", ".h", ".java"))


def is_direct_apply_optional_path(path: str) -> bool:
    basename = os.path.basename(path)
    if path.startswith("Documentation/") or path.endswith((".rst", ".md", ".txt")):
        return True
    if basename.startswith(("README", "TODO", "NOTES", "ChangeLog")):
        return True
    if basename in {
        "COPYING",
        "CREDITS",
        "MAINTAINERS",
        ".gitignore",
        ".mailmap",
        ".gitattributes",
        ".cocciconfig",
        ".clang-format",
    }:
        return True
    if basename.startswith(("LICENSE", "LICENCE")):
        return True
    return False


def is_need_human_path(path: str) -> bool:
    basename = os.path.basename(path)
    if basename.endswith("defconfig") or basename.startswith("config.") or basename.endswith(".config"):
        return True
    if (
        path.startswith("include/uapi/")
        or path.startswith("include/dt-bindings/")
        or "/uapi/" in path
        or "/dt-bindings/" in path
    ):
        return True
    if path.endswith((".dts", ".dtsi", ".dtso", ".lds", ".lds.S", ".S", ".s")):
        return True
    if basename in {"cpucaps", "sysreg", "mach-types", "syscall.tbl"}:
        return True
    if path.startswith("scripts/") or "/scripts/" in path:
        return path.endswith((".awk", ".sh", ".pl", ".py"))
    if path.startswith("tools/") or "/tools/" in path:
        return path.endswith((".awk", ".sh", ".pl", ".py")) or "." not in basename
    return False


def classify_commit_file(path: str) -> str:
    if is_text_config_path(path):
        return SUPPORTED_MIGRATE
    if is_direct_apply_optional_path(path):
        return DIRECT_APPLY_OPTIONAL
    if is_need_human_path(path):
        return NEED_HUMAN
    if is_code_path(path):
        return SUPPORTED_MIGRATE
    return NEED_HUMAN


def optional_direct_apply_issue_result(source_path: str, target_path: str) -> dict:
    reason = "documentation direct apply failed; skipped optional documentation/metadata file"
    return {
        "source_file": source_path,
        "target_file": target_path,
        "patched_file": None,
        "language": "documentation",
        "status": "skipped",
        "reason": reason,
        # 文档/元数据失败不阻塞代码补丁输出，只汇总到 warning/error。
        "issues": [{
            "kind": "doc_direct_apply_failed",
            "reason": reason,
            "blocks_patch": False,
        }],
        "warning": f"{reason}: {source_path}",
    }
