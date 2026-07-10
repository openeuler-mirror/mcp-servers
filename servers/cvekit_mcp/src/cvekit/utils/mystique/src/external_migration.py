"""Migrate file-level C nodes outside Mystique's function pipeline.

This module owns includes, object-like and function-like defines, file-level
function prototypes, named struct definitions, file-scope comments, file-level
macro-style calls, and conservative single-variable global declarations.
Function definitions remain owned by the existing Mystique Joern and LLM
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re

import llm
from scubatrace.cpp.parser import CParser


EXTERNAL_QUERY = """
[
  (preproc_include)
  (preproc_def)
  (preproc_function_def)
  (declaration)
  (struct_specifier)
  (expression_statement)
  (comment)
] @node
"""

GUARD_TYPES = {
    "preproc_if",
    "preproc_ifdef",
    "preproc_elif",
    "preproc_else",
}


@dataclass(frozen=True)
class ExternalNode:
    kind: str
    key: str
    text: str
    start_byte: int
    end_byte: int
    guard_context: tuple[str, ...]

    @property
    def identity(self) -> tuple[str, str, tuple[str, ...]]:
        return self.kind, self.key, self.guard_context


@dataclass(frozen=True)
class ExternalChange:
    action: str
    pre_node: ExternalNode | None
    post_node: ExternalNode | None

    @property
    def identity(self) -> tuple[str, str, tuple[str, ...]]:
        node = self.post_node or self.pre_node
        assert node is not None
        return node.identity


@dataclass(frozen=True)
class UnresolvedChange:
    change: ExternalChange
    reason: str


@dataclass(frozen=True)
class StructField:
    name: str
    type_text: str
    index: int


@dataclass
class ExternalMigrationResult:
    code: str
    detected: list[ExternalChange]
    applied: list[ExternalChange]
    unresolved: list[UnresolvedChange]
    missing_coverage: list[ExternalChange] = field(default_factory=list)


def _signature_symbol(signature: str) -> str | None:
    if "#" not in signature:
        return None
    symbol = signature.rsplit("#", 1)[-1].strip()
    return symbol or None


def _static_inline_symbols(code: str) -> set[str]:
    return set(
        re.findall(
            r"\bstatic\s+(?:__always_)?inline\b[\s\S]*?\b([A-Za-z_]\w*)\s*\(",
            code,
        )
    )


def _contains_symbol(code: str, symbol: str) -> bool:
    return re.search(rf"\b{re.escape(symbol)}\s*\(", code) is not None


def filter_header_prototype_signatures(
    target_file: str,
    signatures: list[str],
    pre_code: str,
    post_code: str,
) -> list[str]:
    if not target_file.endswith(".h") or not signatures:
        return signatures

    prototype_symbols = {
        node.key
        for node in extract_external_nodes(pre_code) + extract_external_nodes(post_code)
        if node.kind == "prototype"
    }
    if not prototype_symbols:
        return signatures

    filtered = [
        signature
        for signature in signatures
        if _signature_symbol(signature) not in prototype_symbols
    ]
    removed = sorted(set(signatures) - set(filtered))
    if removed:
        # prototype 没有函数体，应交给 external migration 处理。
        logging.info("Header prototype signatures will use external migration: %s", removed)
    return filtered

# target-missing static inline 判定为soft skip而不是直接判定整个patch失败
def split_source_only_header_inline_failures(
    target_file: str,
    failed_signatures: list[str],
    result: ExternalMigrationResult,
    pre_code: str,
    post_code: str,
    target_code: str,
) -> tuple[list[str], list[str]]:

    if not target_file.endswith(".h") or result.unresolved:
        return sorted(set(failed_signatures)), []

    source_static_inline_symbols = _static_inline_symbols(pre_code) | _static_inline_symbols(post_code)

    hard_failures: list[str] = []
    soft_skips: list[str] = []
    for signature in failed_signatures:
        symbol = _signature_symbol(signature)
        if not symbol:
            hard_failures.append(signature)
            continue

        # target 没有该 static inline，通常是 source-only header hunk。
        if symbol in source_static_inline_symbols and not _contains_symbol(target_code, symbol):
            soft_skips.append(signature)
            continue

        hard_failures.append(signature)

    if soft_skips:
        logging.warning(
            "Source-only header inline failures were downgraded to soft skips: %s",
            sorted(set(soft_skips)),
        )
    return sorted(set(hard_failures)), sorted(set(soft_skips))


DELETE_MARKER = "<<<DELETE>>>"


def _node_text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _guard_context(node) -> tuple[str, ...]:
    guards: list[str] = []
    parent = node.parent
    while parent is not None:
        if parent.type in GUARD_TYPES:
            header = _node_text(parent).splitlines()[0].strip()
            guards.append(f"{parent.type}:{header}")
        parent = parent.parent
    guards.reverse()
    return tuple(guards)


def _guard_identity(node) -> tuple[str, ...]:
    return _guard_context(node) + (f"{node.type}:{_node_text(node).splitlines()[0].strip()}",)


def _declarator_name(node) -> str | None:
    current = node
    while current is not None:
        if current.type in {"identifier", "field_identifier"}:
            return _node_text(current)
        current = current.child_by_field_name("declarator")
    return None


def _function_definition_name(node) -> str | None:
    declarator = node.child_by_field_name("declarator")
    if declarator is None:
        return None
    return _declarator_name(declarator)


def _attached_comment_key(code: str, comment_node, root) -> str | None:
    """如果是紧贴在函数/结构体之前的注释，将该注释与函数/结构体绑定在一起"""
    siblings = getattr(root, "named_children", [])
    next_node = None
    for sibling in siblings:
        if sibling.start_byte <= comment_node.start_byte:
            continue
        next_node = sibling
        break

    if next_node is None:
        return None

    if next_node.type == "comment":
        return None

    gap = code.encode("utf-8")[comment_node.end_byte:next_node.start_byte]
    if gap.strip():
        return None
    if gap.decode("utf-8", errors="replace").count("\n") > 1:
        return None

    if next_node.type == "function_definition":
        name = _function_definition_name(next_node)
        if name:
            return f"function:{name}"

    if next_node.type == "struct_specifier":
        name = next_node.child_by_field_name("name")
        if name is not None:
            return f"struct:{_node_text(name).strip()}"

    return None


def _inside_function(node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "function_definition":
            return True
        parent = parent.parent
    return False


def _inside_struct_body(node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "field_declaration_list":
            return True
        if parent.type == "function_definition":
            return False
        parent = parent.parent
    return False


def _declaration_declarators(node) -> list:
    return [
        child
        for child in node.named_children
        if child.type
        in {
            "identifier",
            "init_declarator",
            "pointer_declarator",
            "array_declarator",
            "function_declarator",
        }
    ]


def _has_storage_class(node, storage_class: str) -> bool:
    return any(
        child.type == "storage_class_specifier"
        and _node_text(child).strip() == storage_class
        for child in node.named_children
    )


def _struct_definition_span(code: str, node) -> tuple[int, int] | None:
    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")
    if name is None or body is None:
        return None

    parent = node.parent
    if parent is None or parent.type not in GUARD_TYPES | {"translation_unit"}:
        return None

    encoded = code.encode("utf-8")
    end = node.end_byte
    while end < len(encoded) and encoded[end : end + 1] in b" \t\r\n":
        end += 1
    if encoded[end : end + 1] != b";":
        return None
    return node.start_byte, end + 1


def _macro_call_identity_key(expression_statement) -> str | None:
    if len(expression_statement.named_children) != 1:
        return None
    call = expression_statement.named_children[0]
    if call.type != "call_expression":
        return None

    function = call.child_by_field_name("function")
    arguments = call.child_by_field_name("arguments")
    if function is None:
        return None

    function_name = _node_text(function).strip()
    if not function_name:
        return None

    if arguments is None:
        return function_name
    argument_key = re.sub(r"\s+", "", _node_text(arguments))
    return f"{function_name}{argument_key}"


def extract_external_nodes(code: str, label: str = "") -> list[ExternalNode]:
    """Extract file-level nodes owned by the external migration pipeline."""
    _label = f" [{label}]" if label else ""
    parser = CParser()
    root = parser.parse(code)
    nodes: list[ExternalNode] = []
    skipped_inside_func: list[tuple[str, str]] = []
    skipped_empty_key: list[str] = []

    for node in parser.query_all(root, EXTERNAL_QUERY):
        if _inside_function(node):
            if node.type == "comment":
                raw_first_line = _node_text(node).splitlines()[0].strip() if _node_text(node).splitlines() else ""
                skipped_inside_func.append((node.type, raw_first_line[:80]))
            continue
        kind: str
        key: str | None = None

        if node.type == "preproc_include":
            kind = "include"
            path = node.child_by_field_name("path")
            key = _node_text(path).strip() if path is not None else None
        elif node.type in {"preproc_def", "preproc_function_def"}:
            kind = "define"
            name = node.child_by_field_name("name")
            key = _node_text(name).strip() if name is not None else None
        elif node.type == "struct_specifier":
            span = _struct_definition_span(code, node)
            if span is None:
                continue
            kind = "struct"
            name = node.child_by_field_name("name")
            key = _node_text(name).strip() if name is not None else None
            start_byte, end_byte = span
            text = code.encode("utf-8")[start_byte:end_byte].decode("utf-8")
            nodes.append(
                ExternalNode(
                    kind=kind,
                    key=key,
                    text=text,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    guard_context=_guard_context(node),
                )
            )
            continue
        elif node.type == "comment":
            if _inside_struct_body(node):
                continue
            raw = _node_text(node).strip()
            if raw.startswith("//"):
                content = raw[2:].strip()
            elif raw.startswith("/*"):
                inner = raw[2:]
                if inner.endswith("*/"):
                    inner = inner[:-2]
                lines = inner.splitlines()
                meaningful: list[str] = []
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("*"):
                        stripped = stripped[1:].strip()
                    if stripped.endswith("*/"):
                        stripped = stripped[:-2].strip()
                    if stripped:
                        meaningful.append(stripped)
                content = meaningful[0] if meaningful else ""
                # Kernel-doc comments use "func_name - description" format.
                # The func_name may differ across kernel forks (e.g. af_alg_ vs aead_),
                # so use only the description part as the identity key.
                if " - " in content:
                    content = content.split(" - ", 1)[1]
            else:
                content = ""
            attached_key = _attached_comment_key(code, node, root)
            if attached_key is not None:
                kind = "attached_comment"
                key = f"{attached_key}:{content}" if content else attached_key
            else:
                kind = "comment"
                key = content if content else None
        elif node.type == "expression_statement":
            kind = "macro_call"
            key = _macro_call_identity_key(node)
        elif node.type == "declaration":
            declarators = _declaration_declarators(node)
            if len(declarators) != 1:
                continue
            declarator = declarators[0]
            if declarator.type == "function_declarator":
                kind = "prototype"
            else:
                if _has_storage_class(node, "extern"):
                    continue
                kind = "global"
            key = _declarator_name(declarator)
        else:
            continue

        if not key:
            if node.type == "comment":
                skipped_empty_key.append(_node_text(node)[:80])
            continue
        nodes.append(
            ExternalNode(
                kind=kind,
                key=key,
                text=_node_text(node),
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                guard_context=_guard_context(node),
            )
        )

    # ── debug: summary counts ──
    kind_counts: dict[str, int] = {}
    for n in nodes:
        kind_counts[n.kind] = kind_counts.get(n.kind, 0) + 1
    comment_keys = [(n.key, n.start_byte, n.end_byte, n.guard_context) for n in nodes if n.kind == "comment"]
    logging.debug("extract_external_nodes%s: total=%d by_kind=%s", _label, len(nodes), kind_counts)
    if comment_keys:
        logging.debug("extract_external_nodes%s: comment keys=%s", _label, comment_keys)
    if skipped_inside_func:
        logging.debug("extract_external_nodes%s: skipped (inside function)=%s", _label, skipped_inside_func)
    if skipped_empty_key:
        logging.debug("extract_external_nodes%s: skipped (empty key)=%s", _label, skipped_empty_key)

    return sorted(nodes, key=lambda item: item.start_byte)


def _normalized(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _strip_inline_comments(line: str) -> str:
    line = re.sub(r"/\*.*?\*/", " ", line)
    return line.split("//", 1)[0]


def _normalize_field_type(type_text: str) -> str:
    type_text = type_text.replace("*", " * ")
    return re.sub(r"\s+", " ", type_text).strip()


def _extract_simple_struct_fields(struct_text: str) -> dict[str, StructField]:
    """Extract only simple one-name C struct fields.

    Complex fields are intentionally ignored so coverage checks only fire for
    high-confidence field swaps like "struct foo *bar;".
    """
    body_match = re.search(r"\{(?P<body>.*)\}\s*;?\s*$", struct_text, re.DOTALL)
    if body_match is None:
        return {}

    fields: dict[str, StructField] = {}
    for index, raw_line in enumerate(body_match.group("body").splitlines()):
        line = _strip_inline_comments(raw_line).strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line or "}" in line or "(" in line or "," in line:
            continue
        if not line.endswith(";"):
            continue
        line = line[:-1].strip()
        if not line or ":" in line:
            continue
        match = re.match(
            r"(?P<type>.+?[\s\*])(?P<name>[A-Za-z_]\w*)(?:\s*\[[^\]]*\])*$",
            line,
        )
        if match is None:
            continue
        field_type = _normalize_field_type(match.group("type"))
        if field_type:
            name = match.group("name")
            fields[name] = StructField(name=name, type_text=field_type, index=index)
    return fields


def _struct_field_coverage_reason(change: ExternalChange, merged_text: str) -> str | None:
    if change.action != "modify" or change.pre_node is None or change.post_node is None:
        return None
    if change.pre_node.kind != "struct" or change.post_node.kind != "struct":
        return None

    pre_fields = _extract_simple_struct_fields(change.pre_node.text)
    post_fields = _extract_simple_struct_fields(change.post_node.text)
    merged_fields = _extract_simple_struct_fields(merged_text)
    if not pre_fields or not post_fields or not merged_fields:
        return None

    added = set(post_fields) - set(pre_fields)
    deleted = set(pre_fields) - set(post_fields)
    missing_added = sorted(name for name in added if name not in merged_fields)
    stale_deleted = sorted(name for name in deleted if name in merged_fields)
    if not missing_added or not stale_deleted:
        return None

    return (
        "high-confidence struct field coverage failed: "
        f"identity={change.identity}, missing_fields={missing_added}, "
        f"stale_fields={stale_deleted}"
    )


def _struct_field_migration_checklist(change: ExternalChange, target_node: ExternalNode) -> str:
    if change.action != "modify" or change.pre_node is None or change.post_node is None:
        return ""
    if change.pre_node.kind != "struct" or change.post_node.kind != "struct":
        return ""

    pre_fields = _extract_simple_struct_fields(change.pre_node.text)
    post_fields = _extract_simple_struct_fields(change.post_node.text)
    target_fields = _extract_simple_struct_fields(target_node.text)
    if not pre_fields or not post_fields or not target_fields:
        return ""

    added = sorted(set(post_fields) - set(pre_fields), key=lambda name: post_fields[name].index)
    deleted = sorted(set(pre_fields) - set(post_fields), key=lambda name: pre_fields[name].index)
    target_only = sorted(set(target_fields) - set(pre_fields), key=lambda name: target_fields[name].index)
    if not added and not deleted and not target_only:
        return ""

    lines = [
        "[STRUCT_FIELD_MIGRATION_CHECKLIST]",
        "Apply these field-level constraints when merging this struct:",
    ]
    if added:
        lines.append("- MUST include POST-added fields: " + ", ".join(added))
    if deleted:
        lines.append("- MUST remove PRE-deleted fields unless TARGET independently changed their meaning: " + ", ".join(deleted))
    if target_only:
        lines.append("- Preserve TARGET-only fields unless they conflict with POST: " + ", ".join(target_only))
    return "\n".join(lines)


def _symbol_hints_for_external_node(
    symbol_compat_hints: str,
    expected: ExternalNode,
) -> str:
    if expected.kind == "struct":
        return ""
    return symbol_compat_hints


def _detect_changes(pre_code: str, post_code: str) -> tuple[list[ExternalChange], list[ExternalNode]]:
    pre_nodes = extract_external_nodes(pre_code, label="pre")
    post_nodes = extract_external_nodes(post_code, label="post")
    pre_by_id = {node.identity: node for node in pre_nodes}
    post_by_id = {node.identity: node for node in post_nodes}

    changes: list[ExternalChange] = []
    for identity in pre_by_id.keys() | post_by_id.keys():
        pre_node = pre_by_id.get(identity)
        post_node = post_by_id.get(identity)
        if pre_node is None:
            changes.append(ExternalChange("add", None, post_node))
        elif post_node is None:
            changes.append(ExternalChange("delete", pre_node, None))
        elif _normalized(pre_node.text) != _normalized(post_node.text):
            changes.append(ExternalChange("modify", pre_node, post_node))

    # ── debug: summary of detected changes ──
    comment_changes = [c for c in changes if (c.post_node or c.pre_node).kind == "comment"]
    logging.debug(
        "_detect_changes: total=%d comment_changes=%d",
        len(changes), len(comment_changes),
    )
    for c in comment_changes:
        node = c.post_node or c.pre_node
        logging.debug(
            "  comment change: action=%s identity=%s pre_text_head=%s post_text_head=%s",
            c.action,
            c.identity,
            (c.pre_node.text[:120].replace('\n','\\n') if c.pre_node else None),
            (c.post_node.text[:120].replace('\n','\\n') if c.post_node else None),
        )

    def sort_key(change: ExternalChange) -> tuple[int, int]:
        node = change.post_node or change.pre_node
        assert node is not None
        return (1 if change.action == "add" else 0, node.start_byte)

    return sorted(changes, key=sort_key), post_nodes


def _missing_added_coverage(
    changes: list[ExternalChange],
    final_code: str,
) -> list[ExternalChange]:
    final_by_id = {
        node.identity: node
        for node in extract_external_nodes(final_code, label="final")
    }
    missing: list[ExternalChange] = []
    for change in changes:
        if change.action != "add" or change.post_node is None:
            continue
        if change.post_node.kind in {"comment", "attached_comment"}:
            continue
        if change.identity not in final_by_id:
            missing.append(change)
    return missing


def _prepare_insert_text(code: str, position: int, text: str) -> str:
    encoded = code.encode("utf-8")
    prepared = text
    if position > 0 and encoded[position - 1 : position] != b"\n":
        prepared = "\n" + prepared
    if position < len(encoded) and encoded[position : position + 1] == b"\n":
        return prepared
    return prepared if prepared.endswith("\n") else prepared + "\n"


def _struct_body_ranges(
    code: str, nodes: list[ExternalNode],
) -> list[tuple[int, int]]:
    """Return (open_brace, close_brace) byte ranges for struct bodies in target."""
    ranges: list[tuple[int, int]] = []
    encoded = code.encode("utf-8")
    for node in nodes:
        if node.kind != "struct":
            continue
        brace = encoded.find(b"{", node.start_byte, node.end_byte)
        if brace < 0:
            continue
        depth = 1
        pos = brace + 1
        while pos < node.end_byte and depth > 0:
            if encoded[pos:pos+1] == b"{":
                depth += 1
            elif encoded[pos:pos+1] == b"}":
                depth -= 1
            pos += 1
        ranges.append((brace, pos))
    return ranges


def _inside_any_struct_body(ranges: list[tuple[int, int]], byte_pos: int) -> bool:
    return any(start < byte_pos < end for start, end in ranges)


def _attached_comment_target(node: ExternalNode) -> tuple[str, str] | None:
    if node.kind != "attached_comment":
        return None
    parts = node.key.split(":", 2)
    if len(parts) < 2:
        return None
    anchor_kind, anchor_name = parts[0], parts[1]
    if anchor_kind not in {"function", "struct"} or not anchor_name:
        return None
    return anchor_kind, anchor_name


def _find_attached_comment_position(
    code: str,
    node: ExternalNode,
    function_anchor_map: dict[str, str],
) -> int | None:
    """新增 external node 时，如果发现 node kind 是 attached_comment
    找到锚点超入到位置前"""
    target = _attached_comment_target(node)
    if target is None:
        return None

    anchor_kind, anchor_name = target
    parser = CParser()
    root = parser.parse(code)

    if anchor_kind == "function":
        anchor_name = function_anchor_map.get(anchor_name, anchor_name)
        for candidate in parser.query_all(root, "(function_definition) @function"):
            if _function_definition_name(candidate) == anchor_name:
                return candidate.start_byte
        return None

    for candidate in parser.query_all(root, "(struct_specifier) @struct"):
        name = candidate.child_by_field_name("name")
        if name is not None and _node_text(name).strip() == anchor_name:
            span = _struct_definition_span(code, candidate)
            if span is not None:
                return span[0]
    return None


def _find_add_position(
    code: str,
    post_node: ExternalNode,
    post_nodes: list[ExternalNode],
    target_nodes: list[ExternalNode],
    post_in_struct: bool = False,
    function_anchor_map: dict[str, str] | None = None,
) -> int | None:
    if post_node.kind == "attached_comment":
        position = _find_attached_comment_position(
            code,
            post_node,
            function_anchor_map or {},
        )
        if position is not None:
            return position

    target_by_id = {node.identity: node for node in target_nodes}
    post_index = post_nodes.index(post_node)

    # Precompute struct body ranges in target to avoid re-parsing per loop.
    target_struct_bodies = _struct_body_ranges(code, target_nodes)

    for neighbor in reversed(post_nodes[:post_index]):
        if neighbor.guard_context != post_node.guard_context:
            continue
        target_neighbor = target_by_id.get(neighbor.identity)
        if target_neighbor is not None:
            candidate = target_neighbor.end_byte
            if post_in_struct or not _inside_any_struct_body(target_struct_bodies, candidate):
                return candidate

    for neighbor in post_nodes[post_index + 1 :]:
        if neighbor.guard_context != post_node.guard_context:
            continue
        target_neighbor = target_by_id.get(neighbor.identity)
        if target_neighbor is not None:
            candidate = target_neighbor.start_byte
            if post_in_struct or not _inside_any_struct_body(target_struct_bodies, candidate):
                return candidate

    parser = CParser()
    root = parser.parse(code)
    if post_node.guard_context:
        guard_query = """
        [
          (preproc_if)
          (preproc_ifdef)
          (preproc_elif)
          (preproc_else)
        ] @guard
        """
        for guard in parser.query_all(root, guard_query):
            if _guard_identity(guard) != post_node.guard_context:
                continue
            guard_bytes = code.encode("utf-8")[guard.start_byte : guard.end_byte]
            endif_offset = guard_bytes.rfind(b"#endif")
            if endif_offset >= 0:
                return guard.start_byte + endif_offset
        return None

    first_function = parser.query_oneshot(root, "(function_definition) @function")
    if first_function is not None:
        return first_function.start_byte
    return len(code.encode("utf-8"))


def _replace_bytes(code: str, start: int, end: int, replacement: str) -> str:
    encoded = code.encode("utf-8")
    return (encoded[:start] + replacement.encode("utf-8") + encoded[end:]).decode("utf-8")


def _delete_end(code: str, node: ExternalNode) -> int:
    encoded = code.encode("utf-8")
    end = node.end_byte
    if end < len(encoded) and encoded[end : end + 1] == b"\n":
        return end + 1
    return end


def _clean_llm_node_output(output: str) -> str:
    cleaned = output.strip()
    fenced = re.search(r"```(?:c|C)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if fenced is not None:
        cleaned = fenced.group(1).strip()
    return cleaned


def _validate_llm_node(
    candidate: str,
    expected: ExternalNode,
) -> str | None:
    if candidate == DELETE_MARKER:
        return candidate

    syntax_error = llm.compile_check.invoke({"code": candidate, "language": "C"})
    if syntax_error:
        logging.warning("⚠️ 函数外冲突 LLM 结果语法校验失败: %s", syntax_error)
        return None

    candidate_nodes = extract_external_nodes(candidate)
    matching = [
        node
        for node in candidate_nodes
        if node.kind == expected.kind and node.key == expected.key
    ]
    if len(matching) == 1:
        matched_node = matching[0]
        extra_nodes = [node for node in candidate_nodes if node is not matched_node]
        if all(
            node.kind == "comment"
            and matched_node.start_byte <= node.start_byte
            and node.end_byte <= matched_node.end_byte
            for node in extra_nodes
        ):
            return matched_node.text

    if len(matching) != 1:
        logging.warning(
            "⚠️ 函数外冲突 LLM 结果身份校验失败: expected=(%s, %s), nodes=%s",
            expected.kind,
            expected.key,
            [(node.kind, node.key) for node in candidate_nodes],
        )
        return None
    logging.warning(
        "⚠️ 函数外冲突 LLM 结果包含目标节点外的额外节点: expected=(%s, %s), nodes=%s",
        expected.kind,
        expected.key,
        [(node.kind, node.key) for node in candidate_nodes],
    )
    return None


def _resolve_conflict_with_llm(
    change: ExternalChange,
    target_node: ExternalNode,
    symbol_compat_hints: str = "",
) -> str | None:
    pre_text = change.pre_node.text if change.pre_node is not None else "<ABSENT>"
    post_text = change.post_node.text if change.post_node is not None else "<ABSENT>"
    expected = change.post_node or change.pre_node
    assert expected is not None
    node_symbol_hints = _symbol_hints_for_external_node(symbol_compat_hints, expected)
    struct_checklist = _struct_field_migration_checklist(change, target_node)

    compat_section = symbol_compat_hints + "\n" if symbol_compat_hints else ""
    nl = "\n"
    struct_checklist_line = struct_checklist + nl if struct_checklist else ""
    node_symbol_hints_line = node_symbol_hints + nl if node_symbol_hints else ""

    prompt = f"""\
You are adapting one file-level C node during a three-way backport.
The node may be a true textual conflict, or it may require target-branch
API/header compatibility adaptation even when the original patch applies cleanly.

Node kind: {expected.kind}
Node name: {expected.key}
Patch action: {change.action}

[PRE]
{pre_text}

[POST]
{post_text}

[TARGET]
{target_node.text}

{struct_checklist_line}
{node_symbol_hints_line}

Merge the semantic intent of POST into TARGET while preserving TARGET-only
adaptations that do not conflict with the patch. This result will be reviewed
manually, but it must still be syntactically valid.

Output exactly one complete C node with the same kind and name. Do not output
markdown or explanations. If the correct merged result is deletion, output
exactly {DELETE_MARKER}.
"""
    logging.info(
        "🤖 函数外节点冲突交给 LLM 合并: action=%s identity=%s",
        change.action,
        change.identity,
    )
    output = llm.llm_generate(prompt, temperature=0)
    if output is None:
        return None
    return _validate_llm_node(_clean_llm_node_output(output), expected)


_ALREADY_EXISTS = -1  # sentinel: node already present, skip insertion


def _kind_anchor(kind: str, target_nodes: list[ExternalNode]) -> int:
    """Return a byte offset for window anchoring based on node kind."""
    same_kind = [n for n in target_nodes if n.kind == kind]
    if same_kind:
        return same_kind[-1].end_byte
    return 0


_WINDOW_CONTEXT_LINES = 35


def _extract_window(
    current: str, center_byte: int,
) -> tuple[int, int, str]:
    """Extract a window of +/- _WINDOW_CONTEXT_LINES around center_byte."""
    lines = current.splitlines(keepends=True)
    byte_offsets = []
    offset = 0
    for line in lines:
        byte_offsets.append(offset)
        offset += len(line.encode("utf-8"))

    center_line = 0
    for i, bo in enumerate(byte_offsets):
        if bo <= center_byte < bo + len(lines[i].encode("utf-8")):
            center_line = i
            break
        center_line = i

    start_line = max(0, center_line - _WINDOW_CONTEXT_LINES)
    end_line = min(len(lines), center_line + _WINDOW_CONTEXT_LINES + 1)

    window_start = byte_offsets[start_line]
    window_end = (byte_offsets[end_line - 1] + len(lines[end_line - 1].encode("utf-8"))
                  if end_line > start_line else byte_offsets[start_line])
    window_text = "".join(lines[start_line:end_line])
    return window_start, window_end, window_text


def _resolve_insert_with_llm(
    current: str,
    post_node: ExternalNode,
    change: ExternalChange,
    target_nodes: list[ExternalNode],
    symbol_compat_hints: str = "",
) -> tuple[int, int, str] | int | None:
    """Use LLM to insert post_node into a target code window.

    Returns (window_start, window_end, modified_window_text) on success,
    _ALREADY_EXISTS if already present, or None if LLM considers it unsafe.
    """
    anchor_byte = _kind_anchor(post_node.kind, target_nodes)
    window_start, window_end, window_text = _extract_window(current, anchor_byte)

    # Collect existing same-kind nodes in window for context
    same_kind_nodes = [n for n in target_nodes if n.kind == post_node.kind]
    existing_list = "\n".join(
        f"  - {n.key}" for n in same_kind_nodes
    ) if same_kind_nodes else "  (none)"
    node_symbol_hints = _symbol_hints_for_external_node(symbol_compat_hints, post_node)

    prompt = f"""\
You are inserting one C-level node into a target file during a kernel backport.

Node kind: {post_node.kind}
Node name: {post_node.key}

Node to insert:
```
{post_node.text}
```

Existing {post_node.kind} nodes in target:
{existing_list}

{node_symbol_hints}

Target window (the section of the file where this node should be inserted):
```
{window_text}
```

Rules:
- If a node with the same kind and name already exists in the target (compatible content), output exactly:
  ALREADY_EXISTS
- If the node can be safely inserted into this window, output the COMPLETE modified window with the new node inserted at an appropriate position. Preserve all existing code exactly.
- If inserting the node would create broken references (depends on symbols not present in target), output exactly:
  CANNOT_INSERT

Output ONLY the modified window text, ALREADY_EXISTS, or CANNOT_INSERT. No other text.
"""
    output = llm.llm_generate(prompt, temperature=0)
    if output is None:
        return None

    stripped = _clean_llm_node_output(output)
    if stripped == "ALREADY_EXISTS":
        return _ALREADY_EXISTS
    if stripped == "CANNOT_INSERT":
        logging.warning(
            "LLM 判断节点不可插入: kind=%s key=%s",
            post_node.kind, post_node.key,
        )
        return None

    # Validate: the modified window must not drop existing content.
    original_line_count = len(window_text.splitlines())
    modified_line_count = len(stripped.splitlines())
    MIN_LINE_RATIO = 0.6
    if modified_line_count < original_line_count * MIN_LINE_RATIO:
        logging.warning(
            "LLM 修改后的窗口行数(%d)远少于原始窗口(%d), 可能丢失了代码: kind=%s key=%s",
            modified_line_count, original_line_count,
            post_node.kind, post_node.key,
        )
        return None

    # Validate: the inserted node's key must appear in the output.
    if post_node.key not in stripped:
        logging.warning(
            "LLM 输出中未找到插入节点的 key '%s', 可能插入失败: kind=%s",
            post_node.key, post_node.kind,
        )
        return None

    # Treat LLM output as the modified window
    return window_start, window_end, stripped


def migrate_external_changes(
    pre_code: str,
    post_code: str,
    target_code: str,
    symbol_compat_hints: str = "",
    function_anchor_map: dict[str, str] | None = None,
) -> ExternalMigrationResult:
    """Migrate supported file-level changes with conservative three-way rules."""
    changes, post_nodes = _detect_changes(pre_code, post_code)
    post_struct_body_ranges = _struct_body_ranges(post_code, post_nodes)
    current = target_code
    function_anchor_map = function_anchor_map or {}
    applied: list[ExternalChange] = []
    unresolved: list[UnresolvedChange] = []

    for change in changes:
        target_nodes = extract_external_nodes(current, label="target")
        target_by_id = {node.identity: node for node in target_nodes}
        target_node = target_by_id.get(change.identity)

        # ── debug: diagnose missing target node for modify/delete ──
        if target_node is None and change.action in ("modify", "delete"):
            node = change.pre_node or change.post_node
            assert node is not None
            # Collect all comments in target that could be close matches
            target_comments = [
                (n.identity, n.text[:120].replace('\n', '\\n'))
                for n in target_nodes if n.kind == "comment"
            ]
            # Search for the comment key in target to show surrounding code
            target_snippet = ""
            target_encoded = current.encode("utf-8")
            search_key = node.key if node.key else ""
            if search_key:
                pos = target_encoded.find(search_key.encode("utf-8"))
                if pos >= 0:
                    snippet_start = max(0, pos - 400)
                    snippet_end = min(len(target_encoded), pos + 200)
                    target_snippet = target_encoded[snippet_start:snippet_end].decode("utf-8", errors="replace")
            logging.warning(
                "🔍 目标节点缺失: action=%s identity=%s\n"
                "  目标代码中的 comment 节点: %s\n"
                "  搜索 key='%s' 附近的代码片段(byte %d-%d):\n"
                ">>> %s <<<",
                change.action, change.identity,
                target_comments,
                search_key,
                max(0, pos - 400) if search_key and pos >= 0 else 0,
                min(len(target_encoded), pos + 200) if search_key and pos >= 0 else 0,
                target_snippet.replace('\n', '\\n') if target_snippet else "<not found>",
            )

        if change.action == "add":
            assert change.post_node is not None
            if target_node is not None:
                if _normalized(target_node.text) == _normalized(change.post_node.text):
                    continue
                merged = _resolve_conflict_with_llm(
                    change,
                    target_node,
                    symbol_compat_hints=symbol_compat_hints,
                )
                if merged is None:
                    unresolved.append(UnresolvedChange(change, "LLM failed to merge conflicting target node"))
                    continue
                coverage_reason = _struct_field_coverage_reason(change, merged)
                if coverage_reason:
                    unresolved.append(UnresolvedChange(change, coverage_reason))
                    continue
                if merged == DELETE_MARKER:
                    current = _replace_bytes(
                        current,
                        target_node.start_byte,
                        _delete_end(current, target_node),
                        "",
                    )
                else:
                    current = _replace_bytes(
                        current,
                        target_node.start_byte,
                        target_node.end_byte,
                        merged,
                    )
                applied.append(change)
                continue
            post_node = change.post_node
            position = _find_add_position(
                current, change.post_node, post_nodes, target_nodes,
                post_in_struct=_inside_any_struct_body(post_struct_body_ranges, change.post_node.start_byte),
                function_anchor_map=function_anchor_map,
            )
            if position is None:
                result = _resolve_insert_with_llm(
                    current, change.post_node, change, target_nodes,
                    symbol_compat_hints=symbol_compat_hints,
                )
                if result == _ALREADY_EXISTS:
                    applied.append(change)
                    continue
                if result is None:
                    unresolved.append(UnresolvedChange(change, "target guard context is missing"))
                    continue
                window_start, window_end, new_text = result
                current = _replace_bytes(current, window_start, window_end, new_text)
                applied.append(change)
                continue
            current = _replace_bytes(
                current,
                position,
                position,
                _prepare_insert_text(current, position, post_node.text),
            )
            applied.append(change)
            continue

        assert change.pre_node is not None
        if target_node is None:
            if change.action == "delete":
                continue
            # Treat modify as add when target node is missing
            assert change.post_node is not None
            post_node = change.post_node
            position = _find_add_position(
                current, post_node, post_nodes, target_nodes,
                post_in_struct=_inside_any_struct_body(post_struct_body_ranges, post_node.start_byte),
                function_anchor_map=function_anchor_map,
            )
            if position is None:
                result = _resolve_insert_with_llm(
                    current, post_node, change, target_nodes,
                    symbol_compat_hints=symbol_compat_hints,
                )
                if result == _ALREADY_EXISTS:
                    applied.append(change)
                    continue
                if result is None:
                    unresolved.append(UnresolvedChange(change, "target node is missing"))
                    continue
                window_start, window_end, new_text = result
                current = _replace_bytes(current, window_start, window_end, new_text)
                applied.append(change)
                continue
            current = _replace_bytes(
                current,
                position,
                position,
                _prepare_insert_text(current, position, post_node.text),
            )
            applied.append(change)
            continue

        if change.action == "delete":
            if _normalized(target_node.text) != _normalized(change.pre_node.text):
                # For comments, directly delete — don't let LLM guess whether
                # a diverged comment should be partially kept.
                if change.pre_node.kind == "comment":
                    current = _replace_bytes(
                        current,
                        target_node.start_byte,
                        _delete_end(current, target_node),
                        "",
                    )
                    applied.append(change)
                    continue
                merged = _resolve_conflict_with_llm(
                    change,
                    target_node,
                    symbol_compat_hints=symbol_compat_hints,
                )
                if merged is None:
                    unresolved.append(UnresolvedChange(change, "LLM failed to merge delete conflict"))
                    continue
                if merged == DELETE_MARKER:
                    current = _replace_bytes(
                        current,
                        target_node.start_byte,
                        _delete_end(current, target_node),
                        "",
                    )
                else:
                    current = _replace_bytes(
                        current,
                        target_node.start_byte,
                        target_node.end_byte,
                        merged,
                    )
                applied.append(change)
                continue
            current = _replace_bytes(
                current,
                target_node.start_byte,
                _delete_end(current, target_node),
                "",
            )
            applied.append(change)
            continue

        assert change.post_node is not None
        if _normalized(target_node.text) == _normalized(change.post_node.text):
            continue
        # For comments, directly apply POST instead of LLM merge.
        # Comments are documentation, not logic — target-specific modifications
        # to comments (e.g. aead_ vs af_alg_ prefix bugs) are not worth preserving.
        # LLM merge often produces incorrect results when the target comment has
        # formatting differences from both pre and post.
        if change.pre_node is not None and change.pre_node.kind == "comment":
            current = _replace_bytes(
                current,
                target_node.start_byte,
                target_node.end_byte,
                change.post_node.text,
            )
            applied.append(change)
            continue
        if _normalized(target_node.text) != _normalized(change.pre_node.text):
            merged = _resolve_conflict_with_llm(
                change,
                target_node,
                symbol_compat_hints=symbol_compat_hints,
            )
            if merged is None:
                unresolved.append(UnresolvedChange(change, "LLM failed to merge target diverged from pre and post"))
                continue
            coverage_reason = _struct_field_coverage_reason(change, merged)
            if coverage_reason:
                unresolved.append(UnresolvedChange(change, coverage_reason))
                continue
            if merged == DELETE_MARKER:
                current = _replace_bytes(
                    current,
                    target_node.start_byte,
                    _delete_end(current, target_node),
                    "",
                )
            else:
                current = _replace_bytes(
                    current,
                    target_node.start_byte,
                    target_node.end_byte,
                    merged,
                )
            applied.append(change)
            continue
        current = _replace_bytes(
            current,
            target_node.start_byte,
            target_node.end_byte,
            change.post_node.text,
        )
        applied.append(change)

    return ExternalMigrationResult(
        code=current,
        detected=changes,
        applied=applied,
        unresolved=unresolved,
        missing_coverage=_missing_added_coverage(changes, current),
    )
