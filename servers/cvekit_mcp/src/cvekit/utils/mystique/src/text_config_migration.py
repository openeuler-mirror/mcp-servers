"""这个模块处理一些文本文件Makefile/Kbuild/Kconfig
Kconfig 可以按 config xxx scope。
Makefile 可以按 obj-$(CONFIG_...) += ... 这类赋值行。

其余普通文本文件暂时不支持
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
from typing import Callable, Literal

from scubatrace.differ import AddHunk, DelHunk, ModHunk, diff_hunks


TextConfigKind = Literal["kconfig", "makefile", "text"]
ReadTextFile = Callable[[str], str | None]


@dataclass(frozen=True)
class TextConfigChange:
    action: str
    start_line: int
    end_line: int
    old_text: str
    new_text: str
    scope: str | None = None

    @property
    def identity(self) -> tuple[str, int, int, str | None]:
        return self.action, self.start_line, self.end_line, self.scope


@dataclass(frozen=True)
class UnresolvedTextChange:
    change: TextConfigChange
    reason: str


@dataclass
class TextConfigMigrationResult:
    code: str
    detected: list[TextConfigChange]
    applied: list[TextConfigChange]
    unresolved: list[UnresolvedTextChange]


KCONFIG_HEADER_RE = re.compile(
    r"^\s*(?:(?:menu)?config\s+\S+|choice\b|menu\s+.+|if\s+.+)\s*$"
)
KCONFIG_END_RE = re.compile(r"^\s*(?:endchoice|endmenu|endif)\b")
MAKE_ANCHOR_RE = re.compile(
    r"^\s*(?:[-.\w${}()]+)\s*(?::=|\+=|-=|\?=|=|:)"
)


def is_text_config_path(path: str) -> bool:
    basename = os.path.basename(path)
    return (
        basename == "Kconfig"
        or basename.startswith("Kconfig.")
        or basename == "Makefile"
        or basename.startswith("Makefile.")
        or basename == "Kbuild"
        or basename.endswith(".mk")
    )


def detect_text_config_kind(path: str) -> TextConfigKind:
    basename = os.path.basename(path)
    if basename == "Kconfig" or basename.startswith("Kconfig."):
        return "kconfig"
    if (
        basename == "Makefile"
        or basename.startswith("Makefile.")
        or basename == "Kbuild"
        or basename.endswith(".mk")
    ):
        return "makefile"
    return "text"


def _split_lines(text: str) -> list[str]:
    return text.splitlines()


def _render_lines(lines: list[str], template: str) -> str:
    rendered = "\n".join(lines)
    if template.endswith("\n"):
        rendered += "\n"
    return rendered


def _slice_content(lines: list[str], start_line: int, end_line: int) -> str:
    if start_line <= 0 or end_line < start_line:
        return ""
    return "\n".join(lines[start_line - 1 : end_line])


def _line_key(line: str) -> str:
    return line.strip()


def _find_normalized_sequence(
    lines: list[str],
    needle: list[str],
    start: int = 0,
    end: int | None = None,
) -> list[int]:
    if not needle:
        return []
    end = len(lines) if end is None else min(end, len(lines))
    keys = [_line_key(line) for line in lines]
    needle_keys = [_line_key(line) for line in needle]
    size = len(needle_keys)
    matches: list[int] = []
    for idx in range(start, end - size + 1):
        if keys[idx : idx + size] == needle_keys:
            matches.append(idx)
    return matches


def _find_unique_normalized_line(
    lines: list[str],
    target: str,
    start: int = 0,
    end: int | None = None,
) -> int | None:
    end = len(lines) if end is None else min(end, len(lines))
    target_key = _line_key(target)
    matches = [idx for idx in range(start, end) if _line_key(lines[idx]) == target_key]
    if len(matches) == 1:
        return matches[0]
    return None


def _kconfig_scope_at(lines: list[str], line_number: int) -> str | None:
    idx = max(0, min(line_number - 1, len(lines) - 1))
    for pos in range(idx, -1, -1):
        stripped = lines[pos].strip()
        if KCONFIG_HEADER_RE.match(lines[pos]):
            return stripped
    return None


def _kconfig_scope_bounds(lines: list[str], scope: str) -> tuple[int, int] | None:
    starts = [idx for idx, line in enumerate(lines) if line.strip() == scope]
    if len(starts) != 1:
        return None
    start = starts[0]
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        if KCONFIG_HEADER_RE.match(line) or KCONFIG_END_RE.match(line):
            return start, idx
    return start, len(lines)


def has_unique_kconfig_scope(code: str, scope: str) -> bool:
    """Return whether one Kconfig file contains a unique scope.

    Keep this check aligned with the actual migration anchoring logic so callers
    do not retry relocation on a scope that migrate_text_config_changes would
    still consider missing or ambiguous.
    """
    return _kconfig_scope_bounds(_split_lines(code), scope) is not None


def _parent_kconfig_candidates(source_path: str) -> list[str]:
    """Return conservative parent Kconfig candidates for relocated symbols.

    Some kernel branches move a symbol such as "config DRM_AMDGPU" from a
    driver-local Kconfig into a parent Kconfig.  We only walk upward through
    parent directories here; sibling directories and whole-tree scans are
    intentionally excluded to avoid migrating changes into an unrelated symbol.
    """
    candidates: list[str] = []
    directory = os.path.dirname(source_path)
    parent = os.path.dirname(directory)
    while parent and parent != "." and parent != os.path.dirname(parent):
        candidate = os.path.join(parent, "Kconfig")
        if candidate not in candidates and candidate != source_path:
            candidates.append(candidate)
        parent = os.path.dirname(parent)
    return candidates


def _unresolved_kconfig_scopes(result: dict) -> list[str]:
    scopes: list[str] = []
    for item in result.get("unresolved") or []:
        identity = item.get("identity")
        reason = item.get("reason") or ""
        if (
            isinstance(identity, (list, tuple))
            and len(identity) >= 4
            and isinstance(identity[3], str)
            and reason.startswith("Kconfig scope not found or ambiguous:")
            and identity[3] not in scopes
        ):
            scopes.append(identity[3])
    return scopes


def find_parent_kconfig_relocation(
    *,
    source_path: str,
    unresolved_result: dict,
    read_file: ReadTextFile,
) -> tuple[str, str] | tuple[None, None]:
    """Find a unique parent Kconfig that contains all unresolved scopes.

    This intentionally does not scan sibling directories or the whole Kconfig
    tree.  The caller supplies read_file so this module stays independent from
    git/ref handling while keeping the relocation policy near the text config
    migration code.
    """
    scopes = _unresolved_kconfig_scopes(unresolved_result)
    if not scopes:
        return None, None

    matches: list[tuple[str, str]] = []
    for candidate in _parent_kconfig_candidates(source_path):
        content = read_file(candidate)
        if not content:
            continue
        if all(has_unique_kconfig_scope(content, scope) for scope in scopes):
            matches.append((candidate, content))

    # Relocate only when the upward search gives exactly one safe target.  If
    # multiple parent Kconfigs define all scopes, failing closed is preferable
    # to emitting a plausible but wrong config patch.
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logging.warning(
            "Kconfig scope relocation ambiguous for %s scopes=%s candidates=%s",
            source_path,
            scopes,
            [path for path, _ in matches],
        )
    return None, None


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _adapt_kconfig_insert_lines(add_lines: list[str], target_lines: list[str], insert_after: int | None) -> list[str]:
    indent = None
    if insert_after is not None and 0 <= insert_after < len(target_lines):
        anchor = target_lines[insert_after]
        if anchor.strip():
            indent = _leading_ws(anchor)
    if indent is None:
        for line in target_lines:
            if line.strip().startswith(("select ", "depends on ", "default ", "imply ")):
                indent = _leading_ws(line)
                break
    if indent is None:
        indent = "\t"

    adapted: list[str] = []
    for line in add_lines:
        if line.strip():
            adapted.append(indent + line.strip())
        else:
            adapted.append(line)
    return adapted


def _apply_delete(
    current: list[str],
    change: TextConfigChange,
    kind: TextConfigKind,
) -> tuple[list[str], bool, str | None]:
    old_lines = _split_lines(change.old_text)
    if not old_lines:
        return current, True, None

    search_start = 0
    search_end = len(current)
    if kind == "kconfig" and change.scope:
        bounds = _kconfig_scope_bounds(current, change.scope)
        if bounds is None:
            if not _find_normalized_sequence(current, old_lines):
                return current, True, None
            return current, False, f"Kconfig scope not found or ambiguous: {change.scope}"
        search_start, search_end = bounds

    matches = _find_normalized_sequence(current, old_lines, search_start, search_end)
    if len(matches) == 1:
        idx = matches[0]
        del current[idx : idx + len(old_lines)]
        return current, True, None
    if len(matches) == 0:
        return current, True, None
    return current, False, "delete target matched multiple locations"


def _apply_modify(
    current: list[str],
    change: TextConfigChange,
    kind: TextConfigKind,
) -> tuple[list[str], bool, str | None]:
    old_lines = _split_lines(change.old_text)
    new_lines = _split_lines(change.new_text)
    if not old_lines:
        return current, False, "modify hunk has no old content"

    search_start = 0
    search_end = len(current)
    if kind == "kconfig" and change.scope:
        bounds = _kconfig_scope_bounds(current, change.scope)
        if bounds is None:
            if _find_normalized_sequence(current, new_lines):
                return current, True, None
            return current, False, f"Kconfig scope not found or ambiguous: {change.scope}"
        search_start, search_end = bounds

    if _find_normalized_sequence(current, new_lines, search_start, search_end):
        return current, True, None

    matches = _find_normalized_sequence(current, old_lines, search_start, search_end)
    if len(matches) == 1:
        idx = matches[0]
        current[idx : idx + len(old_lines)] = new_lines
        return current, True, None
    if len(matches) == 0:
        return current, False, "modify source block not found in target"
    return current, False, "modify source block matched multiple locations"


def _find_insert_position_by_context(
    current: list[str],
    pre_lines: list[str],
    insert_line: int,
    search_start: int,
    search_end: int,
) -> int | None:
    before_idx = insert_line - 1
    for pos in range(before_idx, max(-1, before_idx - 8), -1):
        if 0 <= pos < len(pre_lines) and pre_lines[pos].strip():
            match = _find_unique_normalized_line(current, pre_lines[pos], search_start, search_end)
            if match is not None:
                return match + 1

    after_idx = insert_line
    for pos in range(after_idx, min(len(pre_lines), after_idx + 8)):
        if pre_lines[pos].strip():
            match = _find_unique_normalized_line(current, pre_lines[pos], search_start, search_end)
            if match is not None:
                return match

    return None


def _apply_add(
    current: list[str],
    pre_lines: list[str],
    change: TextConfigChange,
    kind: TextConfigKind,
) -> tuple[list[str], bool, str | None]:
    add_lines = _split_lines(change.new_text)
    if not add_lines:
        return current, True, None

    search_start = 0
    search_end = len(current)
    if kind == "kconfig" and change.scope:
        bounds = _kconfig_scope_bounds(current, change.scope)
        if bounds is None:
            if _find_normalized_sequence(current, add_lines):
                return current, True, None
            return current, False, f"Kconfig scope not found or ambiguous: {change.scope}"
        search_start, search_end = bounds

    if _find_normalized_sequence(current, add_lines, search_start, search_end):
        return current, True, None

    insert_pos = _find_insert_position_by_context(
        current,
        pre_lines,
        change.start_line,
        search_start,
        search_end,
    )
    if insert_pos is None:
        return current, False, "insert anchor not found in target"

    if kind == "kconfig":
        add_lines = _adapt_kconfig_insert_lines(add_lines, current[search_start:search_end], insert_pos - search_start - 1)

    current[insert_pos:insert_pos] = add_lines
    return current, True, None


def _changes_from_diff(pre_code: str, post_code: str, kind: TextConfigKind) -> list[TextConfigChange]:
    pre_lines = _split_lines(pre_code)
    post_lines = _split_lines(post_code)
    del_hunks, add_hunks, mod_hunks = diff_hunks(pre_code, post_code)
    changes: list[TextConfigChange] = []

    for hunk in del_hunks:
        assert isinstance(hunk, DelHunk)
        scope = _kconfig_scope_at(pre_lines, hunk.a_startline) if kind == "kconfig" else _make_scope(pre_lines, hunk.a_startline)
        changes.append(
            TextConfigChange(
                "delete",
                hunk.a_startline,
                hunk.a_endline,
                _slice_content(pre_lines, hunk.a_startline, hunk.a_endline),
                "",
                scope,
            )
        )
    for hunk in mod_hunks:
        assert isinstance(hunk, ModHunk)
        scope = _kconfig_scope_at(pre_lines, hunk.a_startline) if kind == "kconfig" else _make_scope(pre_lines, hunk.a_startline)
        changes.append(
            TextConfigChange(
                "modify",
                hunk.a_startline,
                hunk.a_endline,
                _slice_content(pre_lines, hunk.a_startline, hunk.a_endline),
                _slice_content(post_lines, hunk.b_startline, hunk.b_endline),
                scope,
            )
        )
    for hunk in add_hunks:
        assert isinstance(hunk, AddHunk)
        scope = _kconfig_scope_at(pre_lines, hunk.insert_line) if kind == "kconfig" else _make_scope(pre_lines, hunk.insert_line)
        changes.append(
            TextConfigChange(
                "add",
                hunk.insert_line,
                hunk.insert_line,
                "",
                _slice_content(post_lines, hunk.b_startline, hunk.b_endline),
                scope,
            )
        )

    def sort_key(change: TextConfigChange) -> tuple[int, int]:
        action_order = {"delete": 0, "modify": 1, "add": 2}
        return change.start_line, action_order.get(change.action, 9)

    return sorted(changes, key=sort_key)


def _make_scope(lines: list[str], line_number: int) -> str | None:
    idx = max(0, min(line_number - 1, len(lines) - 1))
    for pos in range(idx, -1, -1):
        line = lines[pos]
        if MAKE_ANCHOR_RE.match(line):
            return line.strip()
    return None


def migrate_text_config_changes(
    pre_code: str,
    post_code: str,
    target_code: str,
    file_path: str,
) -> TextConfigMigrationResult:
    """Migrate Makefile/Kconfig style text changes with deterministic anchors."""
    kind = detect_text_config_kind(file_path)
    pre_lines = _split_lines(pre_code)
    current = _split_lines(target_code)
    changes = _changes_from_diff(pre_code, post_code, kind)
    applied: list[TextConfigChange] = []
    unresolved: list[UnresolvedTextChange] = []

    for change in changes:
        if change.action == "add":
            current, ok, reason = _apply_add(current, pre_lines, change, kind)
        elif change.action == "delete":
            current, ok, reason = _apply_delete(current, change, kind)
        elif change.action == "modify":
            current, ok, reason = _apply_modify(current, change, kind)
        else:
            ok = False
            reason = f"unsupported text config action: {change.action}"

        if ok:
            applied.append(change)
        else:
            unresolved.append(UnresolvedTextChange(change, reason or "unresolved"))

    logging.info(
        "Text config migration %s: kind=%s detected=%d applied=%d unresolved=%d",
        file_path,
        kind,
        len(changes),
        len(applied),
        len(unresolved),
    )
    for item in unresolved:
        logging.warning(
            "Text config change unresolved: file=%s identity=%s reason=%s",
            file_path,
            item.change.identity,
            item.reason,
        )

    return TextConfigMigrationResult(
        code=_render_lines(current, target_code),
        detected=changes,
        applied=applied,
        unresolved=unresolved,
    )


def migrate_text_config_file(
    *,
    pre_content: str,
    post_content: str,
    target_content: str,
    source_path: str,
    target_file_path: str,
    result_dir: str,
    generate_patch: Callable[[str], str | None],
) -> tuple[dict, str | None, bool]:
    """Migrate one text config file and build the main_from_repo result item."""
    logging.info("开始迁移 text config 文件: %s", source_path)
    text_result = migrate_text_config_changes(
        pre_content,
        post_content,
        target_content,
        source_path,
    )

    if text_result.unresolved:
        logging.warning(
            "text config 文件 %s 存在未解决 hunk，跳过导出该文件 diff",
            source_path,
        )
        return (
            {
                "source_file": source_path,
                "target_file": target_file_path,
                "patched_file": None,
                "language": "text_config",
                "status": "unresolved",
                "unresolved": [
                    {
                        "identity": item.change.identity,
                        "reason": item.reason,
                    }
                    for item in text_result.unresolved
                ],
            },
            None,
            True,
        )

    if text_result.code == target_content:
        logging.info("text config 文件 %s 无需移植 (need not ported)", source_path)
        return (
            {
                "source_file": source_path,
                "target_file": target_file_path,
                "patched_file": None,
                "language": "text_config",
                "status": "need_not_ported",
            },
            None,
            False,
        )

    safe_name = source_path.replace("/", "_").replace(".", "_")
    result_path = os.path.join(result_dir, f"2_patched_{safe_name}")
    with open(result_path, "w") as f:
        f.write(text_result.code)

    patch_diff = generate_patch(text_result.code)
    if patch_diff:
        logging.info("text config 文件 %s 迁移完成，已生成 diff", source_path)
        return (
            {
                "source_file": source_path,
                "target_file": target_file_path,
                "patched_file": result_path,
                "language": "text_config",
                "status": "ported",
            },
            patch_diff,
            False,
        )

    logging.warning("text config 文件 %s 迁移完成，但无法生成 diff", source_path)
    return (
        {
            "source_file": source_path,
            "target_file": target_file_path,
            "patched_file": result_path,
            "language": "text_config",
            "status": "unresolved",
            "unresolved": [
                {
                    "identity": ("generate_diff", 0, 0, source_path),
                    "reason": "unable to generate unified diff",
                }
            ],
        },
        None,
        True,
    )
