"""AnolisAdapter — 将 openEuler defconfig 变更适配到 Anolis 拆分配置格式。"""
import difflib
import logging
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .protocol import AdaptResult, TargetConfigLayout, LayoutError

logger = logging.getLogger(__name__)

# Anolis 支持的三个固定 level
_ANOLIS_LEVELS = ("L0-MANDATORY", "L1-RECOMMEND", "L2-OPTIONAL")

_DEFCONFIG_RE = re.compile(r"^arch/([^/]+)/configs/[^/]*defconfig$")
_CONFIG_SET_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(.+)$")
_CONFIG_UNSET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")


@dataclass(frozen=True)
class _ConfigChange:
    source_path: str
    arch: str
    symbol: str
    line: str
    action: str  # "set", "unset", "delete"


class AnolisAdapter:
    """Anolis 拆分配置布局适配器。

    将 openEuler 单片 defconfig 补丁转换为 anolis/configs/ 下的
    独立 CONFIG_* 文件格式。
    """

    @property
    def name(self) -> str:
        return "anolis"

    def detect(self, repo_path: str, target_ref: str) -> bool:
        try:
            object_type = _run_git(
                repo_path,
                ["cat-file", "-t", f"{target_ref}:anolis/configs"],
            ).strip()
            return object_type == "tree"
        except Exception:
            return False

    def adapt(
        self,
        source_patch: str,
        repo_path: str,
        target_ref: str,
        **options,
    ) -> AdaptResult:
        _require_anolis_configs(repo_path, target_ref)
        default_level = str(options.get("default_level", "L1-RECOMMEND"))
        if default_level not in _ANOLIS_LEVELS:
            from .protocol import ConfigError
            raise ConfigError(
                f"default_level 仅支持 {'/'.join(_ANOLIS_LEVELS)}，"
                f"当前值: {default_level!r}"
            )

        tree_paths = _list_tree_paths(repo_path, target_ref, "anolis/configs")
        changes = _extract_source_config_changes(source_patch)

        unresolved: list[dict] = []
        unresolved_paths: set[str] = set()

        # Pass 1: identify which defconfig files have unresolved changes
        for change in changes:
            candidates = _find_candidates(tree_paths, change.arch, change.symbol)
            if len(candidates) > 1:
                unresolved.append({
                    "source_file": change.source_path,
                    "arch": change.arch,
                    "config": change.symbol,
                    "reason": "multiple target candidates",
                    "candidates": candidates,
                })
                unresolved_paths.add(change.source_path)

        # Pass 2: generate config_patches, skipping files with any unresolved change
        config_blocks: list[str] = []
        resolved_paths: list[str] = []
        for change in changes:
            # Skip if this change is unresolved or its file has any unresolved change
            if change.source_path in unresolved_paths:
                continue

            candidates = _find_candidates(tree_paths, change.arch, change.symbol)

            if change.action == "delete":
                if candidates:
                    block = _build_deletion_block(repo_path, target_ref, candidates[0])
                    if block:
                        config_blocks.append(block)
                    resolved_paths.append(change.source_path)
                else:
                    resolved_paths.append(change.source_path)
                continue

            new_text = f"{change.line}\n"

            if candidates:
                target_path = candidates[0]
                old_text = _git_show_text(repo_path, target_ref, target_path)
            else:
                target_path = (
                    f"anolis/configs/{default_level}/{change.arch}/{change.symbol}"
                )
                old_text = None

            block = _build_unified_diff_block(target_path, old_text, new_text)
            if block:
                config_blocks.append(block)
            resolved_paths.append(change.source_path)

        handled_source_paths = _unique_in_order(resolved_paths)
        filtered_patch = _strip_defconfig_files(source_patch, handled_source_paths)

        return AdaptResult(
            filtered_patch=filtered_patch,
            config_patches="".join(config_blocks),
            unresolved=unresolved,
            handled_source_paths=handled_source_paths,
        )


# ---- 内部函数 ----

def _extract_source_config_changes(source_patch: str) -> list[_ConfigChange]:
    """从源 patch 中提取 defconfig 变更。"""
    current_path: str | None = None
    current_arch: str | None = None
    changes: dict[tuple[str, str], _ConfigChange] = {}

    for line in source_patch.splitlines():
        # 跟踪 diff 头部的文件路径
        if line.startswith("+++ "):
            path = _normalize_diff_path(line[4:].strip())
            match = _DEFCONFIG_RE.match(path) if path else None
            if match:
                current_path = path
                current_arch = match.group(1)
            else:
                current_path = None
                current_arch = None
            continue

        if line.startswith("--- "):
            path = _normalize_diff_path(line[4:].strip())
            match = _DEFCONFIG_RE.match(path) if path else None
            if match and not current_path:
                current_path = path
                current_arch = match.group(1)
            continue

        if not current_path or not current_arch:
            continue

        # 处理新增/修改行
        if line.startswith("+") and not line.startswith("+++"):
            config_line = line[1:]
            symbol = _config_symbol(config_line)
            if symbol:
                action = "unset" if config_line.startswith("# ") else "set"
                changes[(current_path, symbol)] = _ConfigChange(
                    source_path=current_path,
                    arch=current_arch,
                    symbol=symbol,
                    line=config_line,
                    action=action,
                )
            elif config_line.strip():
                logger.debug(
                    "忽略 defconfig 中无法解析的配置行: %s", config_line
                )

        # 处理删除行
        elif line.startswith("-") and not line.startswith("---"):
            config_line = line[1:]
            symbol = _config_symbol(config_line)
            if symbol:
                action = "unset" if config_line.startswith("# ") else "set"
                changes[(current_path, symbol)] = _ConfigChange(
                    source_path=current_path,
                    arch=current_arch,
                    symbol=symbol,
                    line=config_line,
                    action="delete",
                )
            elif config_line.strip():
                logger.debug(
                    "忽略 defconfig 中无法解析的删除行: %s", config_line
                )

    return list(changes.values())


def _config_symbol(line: str) -> str | None:
    set_match = _CONFIG_SET_RE.match(line)
    if set_match:
        return set_match.group(1)
    unset_match = _CONFIG_UNSET_RE.match(line)
    if unset_match:
        return unset_match.group(1)
    return None


def _find_candidates(
    tree_paths: list[str],
    arch: str,
    symbol: str,
) -> list[str]:
    """在 anolis/configs/ 中搜索匹配的 CONFIG 文件。

    搜索所有三个 level，优先 arch-specific 目录，其次 default。
    """
    candidates = []
    for path in tree_paths:
        parts = path.split("/")
        if len(parts) != 5:
            continue
        if parts[0] != "anolis" or parts[1] != "configs":
            continue
        if parts[2] not in _ANOLIS_LEVELS:
            continue
        if parts[3] not in (arch, "default"):
            continue
        if parts[4] == symbol:
            candidates.append(path)

    # 排序：arch-specific 优先
    candidates.sort(key=lambda p: "default" in p.split("/")[3])
    return candidates


def _strip_defconfig_files(
    source_patch: str,
    handled_paths: list[str],
) -> str:
    """从源 patch 中移除已被适配器处理的 defconfig 文件块。"""
    if not handled_paths:
        return source_patch

    handled_set = set(handled_paths)
    lines = source_patch.splitlines(True)
    result: list[str] = []
    skip = False
    current_file: str | None = None

    for i, line in enumerate(lines):
        if line.startswith("diff --git "):
            # 解析当前 diff 块涉及的文件
            parts = line.split()
            if len(parts) >= 4:
                a_path = parts[2][2:] if parts[2].startswith("a/") else parts[2]
                if a_path in handled_set:
                    skip = True
                    current_file = a_path
                else:
                    skip = False
                    current_file = None
        elif line.startswith("--- ") or line.startswith("+++ "):
            path = _normalize_diff_path(line[4:].strip())
            if path and path in handled_set:
                skip = True
                current_file = path
            elif path and path not in handled_set and current_file not in handled_set:
                skip = False

        if not skip:
            result.append(line)

    return "".join(result)


def _build_deletion_block(repo_path: str, target_ref: str, target_path: str) -> str:
    """生成文件删除的 diff block，使用仓库中的实际文件内容。"""
    old_text = _git_show_text(repo_path, target_ref, target_path)
    old_lines = _split_diff_lines(old_text)
    if not old_lines:
        return ""

    lines = [
        f"diff --git a/{target_path} b/{target_path}",
        "deleted file mode 100644",
        f"--- a/{target_path}",
        "+++ /dev/null",
        f"@@ -1,{len(old_lines)} +0,0 @@",
    ]
    for old_line in old_lines:
        lines.append(f"-{old_line}")
    lines.append("")

    return "\n".join(lines)


def _build_unified_diff_block(
    path: str,
    old_text: str | None,
    new_text: str,
) -> str:
    old_lines = _split_diff_lines(old_text)
    new_lines = _split_diff_lines(new_text)
    if old_text is not None and old_lines == new_lines:
        return ""

    headers = [f"diff --git a/{path} b/{path}"]
    if old_text is None:
        headers.append("new file mode 100644")

    diff_lines = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="/dev/null" if old_text is None else f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "\n".join([*headers, *diff_lines]) + "\n"


def _split_diff_lines(text: str | None) -> list[str]:
    if not text:
        return []
    return text.rstrip("\n").split("\n")


def _normalize_diff_path(raw_path: str) -> str | None:
    if raw_path == "/dev/null":
        return None
    if raw_path.startswith("a/") or raw_path.startswith("b/"):
        return raw_path[2:]
    return raw_path


def _require_anolis_configs(repo_path: str, target_ref: str) -> None:
    try:
        object_type = _run_git(
            repo_path,
            ["cat-file", "-t", f"{target_ref}:anolis/configs"],
        ).strip()
    except Exception as exc:
        raise LayoutError("目标仓库缺少 anolis/configs 目录") from exc
    if object_type != "tree":
        raise LayoutError("目标仓库缺少 anolis/configs 目录")


def _list_tree_paths(repo_path: str, target_ref: str, tree_path: str) -> list[str]:
    output = _run_git(
        repo_path,
        ["ls-tree", "-r", "--name-only", target_ref, "--", tree_path],
    )
    return sorted(path for path in output.splitlines() if path)


def _git_show_text(repo_path: str, target_ref: str, path: str) -> str:
    return _run_git(repo_path, ["show", f"{target_ref}:{path}"])


def _run_git(repo_path: str, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"git {' '.join(args)} 失败: {exc.stderr.strip()}"
        ) from exc
    return completed.stdout


def _unique_in_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result
