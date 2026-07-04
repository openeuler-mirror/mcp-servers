"""解析 C 补丁新增代码在目标分支上的兼容性风险：即新增代码在目标分支上不存在，找到可能的改名候选

除安全的 include provider rewrite 外，本模块保持只读决策。
对于函数、宏和类型，只生成 prompt hint，把语义适配交给 Mystique 的 LLM 流程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import difflib
import logging
import os
import re
import subprocess
import tempfile

from ast_parser import ASTParser
from common import Language


SYSTEM_INCLUDE_RE = re.compile(r"^(?P<prefix>\s*#\s*include\s*)<(?P<header>[^>]+)>(?P<suffix>.*)$")
ADDED_SYSTEM_INCLUDE_RE = re.compile(r"^(?P<prefix>\+\s*#\s*include\s*)<(?P<header>[^>]+)>(?P<suffix>.*)$")
ADDED_SYSTEM_INCLUDE_SEARCH_RE = re.compile(r"^\+\s*#\s*include\s*<", re.MULTILINE)
INCLUDE_RE = re.compile(r"^\s*#\s*include\s*(?P<quote>[<\"])(?P<header>[^>\"]+)[>\"]")
C_NON_CODE_TOKEN_RE = re.compile(
    r"""
    //[^\n]*              # line comment
    | /\*.*?\*/           # block comment
    | "(?:\\.|[^"\\])*"   # string literal
    | '(?:\\.|[^'\\])*'   # char literal
    """,
    re.DOTALL | re.VERBOSE,
)

_CALL_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "container_of",
}


@dataclass(frozen=True)
class SymbolLocation:
    symbol: str
    path: str
    line: int
    kind: str = ""


@dataclass(frozen=True)
class SymbolCandidate:
    symbol: str
    path: str
    line: int
    kind: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SymbolCompatibilityHint:
    missing_symbol: str
    kind: str
    candidates: tuple[SymbolCandidate, ...] = ()

    def format_for_prompt(self) -> str:
        lines = [f"Missing symbol: {self.missing_symbol} ({self.kind})"]
        if self.candidates:
            lines.append("Candidate target symbols:")
            for candidate in self.candidates:
                reason = f", reason={candidate.reason}" if candidate.reason else ""
                lines.append(
                    f"- {candidate.symbol} at {candidate.path}:{candidate.line}{reason}"
                )
        else:
            lines.append("Candidate target symbols: <none found in target scope>")
        return "\n".join(lines)


@dataclass
class SymbolCompatibilityResult:
    hints: list[SymbolCompatibilityHint] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hints

    def format_for_prompt(self) -> str:
        if not self.hints:
            return ""
        body = "\n\n".join(hint.format_for_prompt() for hint in self.hints)
        return (
            "[TARGET_SYMBOL_COMPATIBILITY_HINTS]\n"
            "The patch references symbols that were not found in the scanned target scope.\n"
            "These are weak compatibility hints, not required rewrites.\n\n"
            f"{body}\n\n"
            "Use candidates only if they preserve the patch intent and target API contract.\n"
            "Do not mechanically rename symbols."
        )


@dataclass
class FastPathSymbolCompatibility:
    ok: bool = True
    hints: str = ""
    reason: str = ""


@dataclass
class IncludeResolution:
    resolved_text: str | None = None
    provider_header: str | None = None
    changed: bool = False
    reason: str = ""
    symbols: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.resolved_text is not None


@dataclass
class PatchIncludeResolution:
    patch_text: str
    changed: bool = False
    unresolved: list[str] = field(default_factory=list)
    resolved: list[IncludeResolution] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unresolved


def _target_header_exists(target_repo_path: str, header: str) -> bool:
    return os.path.isfile(os.path.join(target_repo_path, "include", header))


def _header_from_repo_path(path: str) -> str | None:
    norm = path.replace(os.sep, "/")
    if norm.startswith("./"):
        norm = norm[2:]
    if norm.startswith("include/"):
        return norm[len("include/") :]
    return None


def _select_scopes(target_repo_path: str, missing_header: str, current_file_path: str | None = None) -> list[str]:
    scopes: list[str] = []
    # 通过在include文件夹范围内查找新增结构体，反查可能变更的宏名，此函数限定查找范围
    def add_scope(rel: str) -> None:
        path = os.path.join(target_repo_path, rel)
        if os.path.isdir(path) and rel not in scopes:
            scopes.append(rel)

    parts = missing_header.split("/")
    if parts:
        top = parts[0]
        add_scope(os.path.join("include", top))
        #用户态会加uapi
        add_scope(os.path.join("include", "uapi", top))
        if top == "asm":
            # 是给 kernel 里的 #include <asm/...> 做一个常见兜底
            add_scope("include/asm-generic")

    if current_file_path:
        current_dir = os.path.dirname(current_file_path)
        add_scope(current_dir)
        parent = os.path.dirname(current_dir)
        if parent and parent != current_dir:
            add_scope(parent)

    return scopes


def _extract_system_includes_from_patch(file_patch: str) -> list[str]:
    headers: list[str] = []
    for line in file_patch.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        match = ADDED_SYSTEM_INCLUDE_RE.match(line)
        if match is not None:
            headers.append(match.group("header"))
    return headers


def _resolve_include_path(
    target_repo_path: str,
    include_header: str,
    quote: str,
    including_file_path: str | None,
) -> str | None:
    candidates: list[str] = []
    if quote == "<":
        candidates.append(os.path.join("include", include_header))
    elif including_file_path:
        candidates.append(os.path.join(os.path.dirname(including_file_path), include_header))

    if quote == "\"":
        candidates.append(include_header)
        candidates.append(os.path.join("include", include_header))

    for candidate in candidates:
        norm = os.path.normpath(candidate).replace(os.sep, "/")
        full_path = os.path.join(target_repo_path, norm)
        if os.path.isfile(full_path):
            return norm
    return None


def _collect_reachable_include_files(
    target_repo_path: str,
    current_file_path: str | None,
    patch_headers: list[str],
    max_depth: int = 2,
) -> list[str]:
    include_files: list[str] = []
    seen: set[str] = set()
    queue: list[tuple[str, int]] = []

    def add_file(path: str | None, depth: int) -> None:
        if path is None or path in seen:
            return
        seen.add(path)
        include_files.append(path)
        if depth < max_depth:
            queue.append((path, depth))

    if current_file_path:
        add_file(current_file_path, 0)
    for header in patch_headers:
        add_file(_resolve_include_path(target_repo_path, header, "<", current_file_path), 0)

    while queue:
        source_path, depth = queue.pop(0)
        try:
            with open(os.path.join(target_repo_path, source_path), encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except OSError:
            continue

        for line in source.splitlines():
            match = INCLUDE_RE.match(line)
            if match is None:
                continue
            include_path = _resolve_include_path(
                target_repo_path,
                match.group("header"),
                match.group("quote"),
                source_path,
            )
            add_file(include_path, depth + 1)

    return include_files


def _select_symbol_scopes(
    target_repo_path: str,
    file_patch: str,
    current_file_path: str | None,
) -> list[str]:
    scopes: list[str] = []

    def add_scope(rel: str) -> None:
        path = os.path.join(target_repo_path, rel)
        if (os.path.isdir(path) or os.path.isfile(path)) and rel not in scopes:
            scopes.append(rel)

    if current_file_path:
        current_dir = os.path.dirname(current_file_path)
        add_scope(current_dir)
        parent = os.path.dirname(current_dir)
        if parent and parent != current_dir:
            add_scope(parent)

    patch_headers = _extract_system_includes_from_patch(file_patch)
    for header in patch_headers:
        for scope in _select_scopes(target_repo_path, header, current_file_path):
            add_scope(scope)

    for include_file in _collect_reachable_include_files(
        target_repo_path,
        current_file_path,
        patch_headers,
    ):
        add_scope(include_file)

    return scopes


def _extract_added_code_from_patch(file_patch: str) -> str:
    lines: list[str] = []
    for line in file_patch.splitlines():
        if not line.startswith("+") or line.startswith("+++") or line.startswith("+#"):
            continue
        lines.append(line[1:])
    return "\n".join(lines)


def _is_added_file_patch(file_patch: str) -> bool:
    return (
        "\nnew file mode " in file_patch
        or "\n--- /dev/null\n" in file_patch
        or file_patch.startswith("--- /dev/null\n")
    )


def _extract_added_symbols(code: str) -> list[str]:
    code = C_NON_CODE_TOKEN_RE.sub(
        lambda match: re.sub(r"[^\n]", " ", match.group(0)),
        code,
    )
    symbols: set[str] = set()
    for pattern in (
        r"\b(?:struct|enum|union)\s+([A-Za-z_]\w*)",
        r"\b([A-Za-z_]\w*)\s*\(",
        r"\b([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b",
    ):
        for match in re.finditer(pattern, code):
            symbol = match.group(1)
            if symbol not in _CALL_KEYWORDS:
                symbols.add(symbol)
    return sorted(symbols)


def _extract_symbol_details(code: str) -> dict[str, str]:
    code = C_NON_CODE_TOKEN_RE.sub(
        lambda match: re.sub(r"[^\n]", " ", match.group(0)),
        code,
    )
    details: dict[str, str] = {}
    for match in re.finditer(r"\b(?:struct|enum|union)\s+([A-Za-z_]\w*)", code):
        details.setdefault(match.group(1), "type")
    for match in re.finditer(r"\b([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b", code):
        details.setdefault(match.group(1), "macro")
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", code):
        symbol = match.group(1)
        if symbol not in _CALL_KEYWORDS:
            details.setdefault(symbol, "function")
    for symbol in _extract_defined_symbols(code):
        details.pop(symbol, None)
    return details


def _extract_changed_symbol_details_from_patch(file_patch: str) -> tuple[dict[str, str], dict[str, str]]:
    introduced: dict[str, str] = {}
    removed: dict[str, str] = {}
    hunk_added: list[str] = []
    hunk_deleted: list[str] = []

    def flush_hunk() -> None:
        added_symbols = _extract_symbol_details("\n".join(hunk_added))
        deleted_symbols = _extract_symbol_details("\n".join(hunk_deleted))

        for symbol, kind in added_symbols.items():
            if symbol not in deleted_symbols:
                introduced.setdefault(symbol, kind)
        for symbol, kind in deleted_symbols.items():
            if symbol not in added_symbols:
                removed.setdefault(symbol, kind)

        hunk_added.clear()
        hunk_deleted.clear()

    for line in file_patch.splitlines():
        if line.startswith("@@"):
            flush_hunk()
            continue
        if line.startswith("+") and not line.startswith("+++") and not line.startswith("+#"):
            hunk_added.append(line[1:])
            continue
        if line.startswith("-") and not line.startswith("---") and not line.startswith("-#"):
            hunk_deleted.append(line[1:])

    flush_hunk()
    return introduced, removed


def _extract_defined_symbols(code: str) -> set[str]:
    defined: set[str] = set()
    for match in re.finditer(r"^\s*#\s*define\s+([A-Za-z_]\w*)", code, re.MULTILINE):
        defined.add(match.group(1))
    for match in re.finditer(
        r"^\s*(?:typedef\s+)?(?:struct|enum|union)\s+([A-Za-z_]\w*)\s*\{",
        code,
        re.MULTILINE,
    ):
        defined.add(match.group(1))
    func_pattern = re.compile(
        r"^\s*(?:static\s+)?(?:inline\s+)?[\w\s]+[*\s]+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{",
        re.MULTILINE,
    )
    for match in func_pattern.finditer(code):
        defined.add(match.group(1))
    return defined


def _node_text(node) -> str:
    return node.text.decode("utf-8", errors="ignore") if node.text is not None else ""


def _has_named_child(node, child_type: str) -> bool:
    for child in node.named_children:
        if child.type == child_type:
            return True
    return False


def _first_identifier_node(node):
    cursor = node.walk()
    visited_children = False
    while True:
        if not visited_children:
            if cursor.node.type == "identifier":
                return cursor.node
            if not cursor.goto_first_child():
                visited_children = True
        elif cursor.goto_next_sibling():
            visited_children = False
        elif not cursor.goto_parent():
            break
    return None


def _definition_name_node(node):
    if node.type == "function_definition":
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            return None
        return _first_identifier_node(declarator)
    if node.type in {"preproc_def", "preproc_function_def", "struct_specifier", "enum_specifier", "union_specifier"}:
        return node.child_by_field_name("name")
    return None


def _definition_symbol_from_node(node) -> str | None:
    if node.type == "function_definition":
        name_node = _definition_name_node(node)
        return _node_text(name_node).strip() if name_node is not None else None
    if node.type in {"preproc_def", "preproc_function_def"}:
        name_node = _definition_name_node(node)
        return _node_text(name_node).strip() if name_node is not None else None
    if node.type in {"struct_specifier", "union_specifier"}:
        if not _has_named_child(node, "field_declaration_list"):
            return None
        name_node = _definition_name_node(node)
        return _node_text(name_node).strip() if name_node is not None else None
    if node.type == "enum_specifier":
        if not _has_named_child(node, "enumerator_list"):
            return None
        name_node = _definition_name_node(node)
        return _node_text(name_node).strip() if name_node is not None else None
    return None


def _definition_touches_added_declaration_line(node, post_changed_lines: set[int]) -> bool:
    if not post_changed_lines:
        return False
    if node.start_point[0] + 1 in post_changed_lines:
        return True
    name_node = _definition_name_node(node)
    if name_node is None:
        return False
    return name_node.start_point[0] + 1 in post_changed_lines


def collect_patch_defined_symbols_from_post_files(
    post_files: dict[str, str],
    file_hunk_ranges: dict[str, tuple[set[int], set[int]]],
) -> set[str]:
    defined_symbols: set[str] = set()
    definition_node_types = {
        "function_definition",
        "preproc_def",
        "preproc_function_def",
        "struct_specifier",
        "enum_specifier",
        "union_specifier",
    }

    for file_path, post_content in post_files.items():
        if not file_path.endswith((".c", ".h")):
            continue
        _pre_changed, post_changed = file_hunk_ranges.get(file_path, (set(), set()))
        if not post_changed:
            continue
        try:
            parser = ASTParser(post_content, Language.C)
        except Exception as exc:
            logging.debug("patch-local definition parse failed for %s: %s", file_path, exc)
            continue
        for node in parser.traverse_tree():
            if node.type not in definition_node_types:
                continue
            if not _definition_touches_added_declaration_line(node, post_changed):
                continue
            symbol = _definition_symbol_from_node(node)
            if symbol:
                defined_symbols.add(symbol)
    return defined_symbols


def _run_ctags(target_repo_path: str, scopes: list[str]) -> list[SymbolLocation]:
    if not scopes:
        return []
    with tempfile.NamedTemporaryFile(prefix="mystique-ctags-", suffix=".tags", delete=False) as f:
        tags_path = f.name
    try:
        cmd = [
            "ctags",
            "--excmd=number",
            "-R",
            "--languages=C,C++",
            "--c-kinds=+p+d+t+s+e",
            "--c++-kinds=+p",
            "--extras=+q",
            "-f",
            tags_path,
            *scopes,
        ]
        proc = subprocess.run(
            cmd,
            cwd=target_repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0 and (not os.path.exists(tags_path) or os.path.getsize(tags_path) == 0):
            logging.warning(
                "include provider ctags failed: rc=%s stderr=%s",
                proc.returncode,
                (proc.stderr or "").strip()[:500],
            )
            return []
        return _parse_ctags_file(tags_path)
    finally:
        try:
            os.unlink(tags_path)
        except OSError:
            pass


def _parse_ctags_file(tags_path: str) -> list[SymbolLocation]:
    locations: list[SymbolLocation] = []
    with open(tags_path, "rb") as f:
        for raw in f:
            text = raw.decode("utf-8", errors="ignore").strip()
            if not text or text.startswith("!_TAG_"):
                continue
            try:
                before, after = text.split(';"', 1)
                symbol, path, line_text = before.split("\t")[:3]
                kind = after.lstrip("\t").split("\t", 1)[0]
                locations.append(
                    SymbolLocation(
                        symbol=symbol,
                        path=path,
                        line=int(line_text),
                        kind=kind,
                    )
                )
            except Exception:
                continue
    return locations


def _find_unique_provider(
    target_repo_path: str,
    missing_header: str,
    current_file_path: str | None,
    symbols: list[str],
) -> tuple[str | None, list[str]]:
    scopes = _select_scopes(target_repo_path, missing_header, current_file_path)
    # 用 ctags 扫 target 的相关 include 目录，找哪个 header 提供这个符号
    locations = _run_ctags(target_repo_path, scopes)
    wanted = set(symbols)
    providers: dict[str, set[str]] = {}
    for loc in locations:
        if loc.symbol not in wanted:
            continue
        header = _header_from_repo_path(loc.path)
        if header is None:
            continue
        if os.path.basename(header) != os.path.basename(missing_header):
            continue
        providers.setdefault(header, set()).add(loc.symbol)

    if not providers:
        return None, []

    best_count = max(len(items) for items in providers.values())
    best = sorted(header for header, items in providers.items() if len(items) == best_count)
    if len(best) == 1 and best_count >= 2:
        return best[0], sorted(providers)
    return None, sorted(providers)


def _common_prefix_score(left: str, right: str) -> int:
    score = 0
    for a, b in zip(left, right):
        if a != b:
            break
        score += 1
    return score


def _candidate_reason(missing: str, candidate: SymbolLocation) -> str:
    reasons: list[str] = []
    if missing.split("_", 1)[0] == candidate.symbol.split("_", 1)[0]:
        reasons.append("same prefix")
    ratio = difflib.SequenceMatcher(None, missing, candidate.symbol).ratio()
    if ratio >= 0.55:
        reasons.append("similar name")
    if os.path.dirname(candidate.path):
        reasons.append("target scope")
    return " and ".join(reasons)


def _location_kind_matches(missing_kind: str, location_kind: str) -> bool:
    kind = location_kind.lower()
    if missing_kind == "function":
        return kind in {"f", "p", "function", "prototype"}
    if missing_kind == "macro":
        return kind in {"d", "macro", "define"}
    if missing_kind == "type":
        return kind in {"s", "t", "e", "u", "struct", "typedef", "enum", "union"}
    return False


def _is_high_confidence_candidate(missing: str, missing_kind: str, candidate: SymbolLocation) -> tuple[bool, float, int]:
    if not _location_kind_matches(missing_kind, candidate.kind):
        return False, 0.0, 0

    ratio = difflib.SequenceMatcher(None, missing, candidate.symbol).ratio()
    prefix = _common_prefix_score(missing, candidate.symbol)
    missing_head = missing.split("_", 1)[0]
    candidate_head = candidate.symbol.split("_", 1)[0]
    same_head = len(missing_head) >= 3 and missing_head == candidate_head

    if missing_kind == "macro":
        return ratio >= 0.86 and (prefix >= 4 or same_head), ratio, prefix
    return ratio >= 0.78 and (prefix >= 4 or same_head), ratio, prefix


def _rank_candidates(
    missing: str,
    missing_kind: str,
    locations: list[SymbolLocation],
    limit: int = 3,
) -> tuple[SymbolCandidate, ...]:
    scored: list[tuple[float, int, SymbolLocation]] = []
    for loc in locations:
        if loc.symbol == missing:
            continue
        high_confidence, ratio, prefix = _is_high_confidence_candidate(missing, missing_kind, loc)
        if not high_confidence:
            continue
        scored.append((ratio, prefix, loc))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].path, item[2].symbol))
    candidates: list[SymbolCandidate] = []
    seen: set[tuple[str, str]] = set()
    for _, _, loc in scored:
        key = (loc.symbol, loc.path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            SymbolCandidate(
                symbol=loc.symbol,
                path=loc.path,
                line=loc.line,
                kind=loc.kind,
                reason=_candidate_reason(missing, loc),
            )
        )
        if len(candidates) >= limit:
            break
    return tuple(candidates)


def check_patch_symbol_compatibility(
    file_patch: str,
    target_repo_path: str | None,
    current_file_path: str | None = None,
    patch_defined_symbols: set[str] | None = None,
) -> SymbolCompatibilityResult:
    if not target_repo_path:
        return SymbolCompatibilityResult()
    symbols, _removed_symbols = _extract_changed_symbol_details_from_patch(file_patch)
    if patch_defined_symbols:
        for symbol in patch_defined_symbols:
            symbols.pop(symbol, None)
    if not symbols:
        return SymbolCompatibilityResult()

    scopes = _select_symbol_scopes(target_repo_path, file_patch, current_file_path)
    if not scopes:
        logging.debug("symbol compatibility skipped: no target scopes for %s", current_file_path)
        return SymbolCompatibilityResult()

    locations = _run_ctags(target_repo_path, scopes)
    by_symbol: dict[str, list[SymbolLocation]] = {}
    for loc in locations:
        by_symbol.setdefault(loc.symbol, []).append(loc)

    hints: list[SymbolCompatibilityHint] = []
    all_locations = list(locations)
    for symbol, kind in sorted(symbols.items()):
        if symbol in by_symbol:
            continue
        candidates = _rank_candidates(symbol, kind, all_locations)
        if not candidates:
            logging.debug(
                "symbol compatibility hint suppressed due to no high-confidence candidates: %s (%s)",
                symbol,
                kind,
            )
            continue
        hints.append(
            SymbolCompatibilityHint(
                missing_symbol=symbol,
                kind=kind,
                candidates=candidates,
            )
        )
    return SymbolCompatibilityResult(hints)


def format_symbol_compatibility_hints(
    file_patch: str | None,
    target_repo_path: str | None,
    current_file_path: str | None = None,
    patch_defined_symbols: set[str] | None = None,
) -> str:
    if not file_patch:
        return ""
    symbol_result = check_patch_symbol_compatibility(
        file_patch,
        target_repo_path,
        current_file_path,
        patch_defined_symbols,
    )
    if symbol_result.ok:
        return ""
    return symbol_result.format_for_prompt()


def check_fast_path_symbol_compatibility(
    file_patch: str,
    target_repo_path: str | None,
    current_file_path: str | None = None,
    patch_defined_symbols: set[str] | None = None,
) -> FastPathSymbolCompatibility:
    hint_text = format_symbol_compatibility_hints(
        file_patch,
        target_repo_path,
        current_file_path,
        patch_defined_symbols,
    )
    if not hint_text:
        return FastPathSymbolCompatibility()

    reason = "target symbol compatibility hints found"
    logging.warning(
        "  ⚠️ git apply --check 成功但存在新增符号兼容提示，仅记录 warning: %s",
        current_file_path or "<unknown>",
    )
    logging.info(hint_text)
    return FastPathSymbolCompatibility(True, hint_text, reason)


def resolve_include_text(
    include_text: str,
    target_repo_path: str | None,
    current_file_path: str | None,
    added_code: str,
) -> IncludeResolution:
    #处理单条include
    match = SYSTEM_INCLUDE_RE.match(include_text)
    if match is None:
        return IncludeResolution(resolved_text=include_text, reason="not a system include")

    header = match.group("header")
    if not target_repo_path:
        return IncludeResolution(resolved_text=include_text, reason="target repo unavailable")
    if _target_header_exists(target_repo_path, header):
        return IncludeResolution(resolved_text=include_text, reason="target header exists")

    symbols = _extract_added_symbols(added_code)
    if not symbols:
        return IncludeResolution(
            reason=f"missing target header <{header}> and no added symbols were found"
        )

    provider, candidates = _find_unique_provider(
        target_repo_path,
        header,
        current_file_path,
        symbols,
    )
    if provider is None:
        return IncludeResolution(
            reason=f"missing target header <{header}> and no unique provider was found",
            symbols=symbols,
            candidates=candidates,
        )

    resolved = f"{match.group('prefix')}<{provider}>{match.group('suffix')}"
    return IncludeResolution(
        resolved_text=resolved,
        provider_header=provider,
        changed=provider != header,
        reason=f"resolved <{header}> via target provider <{provider}>",
        symbols=symbols,
        candidates=candidates,
    )


def resolve_patch_includes(
    file_patch: str,
    target_repo_path: str,
    current_file_path: str | None = None,
) -> PatchIncludeResolution:
    # 处理整个 file patch 里的新增 include
    if not ADDED_SYSTEM_INCLUDE_SEARCH_RE.search(file_patch):
        return PatchIncludeResolution(patch_text=file_patch)

    added_code = _extract_added_code_from_patch(file_patch)
    changed = False
    unresolved: list[str] = []
    resolved: list[IncludeResolution] = []
    output_lines: list[str] = []

    for line in file_patch.splitlines():
        match = ADDED_SYSTEM_INCLUDE_RE.match(line)
        if match is None:
            output_lines.append(line)
            continue

        include_text = f"{match.group('prefix')[1:]}<{match.group('header')}>{match.group('suffix')}"
        result = resolve_include_text(
            include_text,
            target_repo_path,
            current_file_path,
            added_code,
        )
        if not result.ok:
            unresolved.append(result.reason)
            output_lines.append(line)
            continue

        resolved.append(result)
        if result.changed and result.resolved_text is not None:
            output_lines.append("+" + result.resolved_text)
            changed = True
        else:
            output_lines.append(line)

    suffix = "\n" if file_patch.endswith("\n") else ""
    return PatchIncludeResolution(
        patch_text="\n".join(output_lines) + suffix,
        changed=changed,
        unresolved=unresolved,
        resolved=resolved,
    )
