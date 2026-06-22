"""Migrate file-level C nodes outside Mystique's function pipeline.

This module owns includes, object-like and function-like defines, file-level
function prototypes, named struct definitions, file-scope comments, and
conservative single-variable global declarations. Function definitions remain
owned by the existing Mystique Joern and LLM pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class ExternalMigrationResult:
    code: str
    detected: list[ExternalChange]
    applied: list[ExternalChange]
    unresolved: list[UnresolvedChange]


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


def _inside_function(node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "function_definition":
            return True
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
            kind = "comment"
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
            key = content if content else None
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


def _prepare_insert_text(code: str, position: int, text: str) -> str:
    encoded = code.encode("utf-8")
    prepared = text
    if position > 0 and encoded[position - 1 : position] != b"\n":
        prepared = "\n" + prepared
    if position < len(encoded) and encoded[position : position + 1] == b"\n":
        return prepared
    return prepared if prepared.endswith("\n") else prepared + "\n"


def _find_add_position(
    code: str,
    post_node: ExternalNode,
    post_nodes: list[ExternalNode],
    target_nodes: list[ExternalNode],
) -> int | None:
    target_by_id = {node.identity: node for node in target_nodes}
    post_index = post_nodes.index(post_node)

    for neighbor in reversed(post_nodes[:post_index]):
        if neighbor.guard_context != post_node.guard_context:
            continue
        target_neighbor = target_by_id.get(neighbor.identity)
        if target_neighbor is not None:
            return target_neighbor.end_byte

    for neighbor in post_nodes[post_index + 1 :]:
        if neighbor.guard_context != post_node.guard_context:
            continue
        target_neighbor = target_by_id.get(neighbor.identity)
        if target_neighbor is not None:
            return target_neighbor.start_byte

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
    if len(matching) != 1 or len(candidate_nodes) != 1:
        logging.warning(
            "⚠️ 函数外冲突 LLM 结果身份校验失败: expected=(%s, %s), nodes=%s",
            expected.kind,
            expected.key,
            [(node.kind, node.key) for node in candidate_nodes],
        )
        return None
    return matching[0].text


def _resolve_conflict_with_llm(
    change: ExternalChange,
    target_node: ExternalNode,
) -> str | None:
    pre_text = change.pre_node.text if change.pre_node is not None else "<ABSENT>"
    post_text = change.post_node.text if change.post_node is not None else "<ABSENT>"
    expected = change.post_node or change.pre_node
    assert expected is not None

    prompt = f"""\
You are resolving one conflicting file-level C node during a three-way backport.

Node kind: {expected.kind}
Node name: {expected.key}
Patch action: {change.action}

[PRE]
{pre_text}

[POST]
{post_text}

[TARGET]
{target_node.text}

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


def migrate_external_changes(pre_code: str, post_code: str, target_code: str) -> ExternalMigrationResult:
    """Migrate supported file-level changes with conservative three-way rules."""
    changes, post_nodes = _detect_changes(pre_code, post_code)
    current = target_code
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
                merged = _resolve_conflict_with_llm(change, target_node)
                if merged is None:
                    unresolved.append(UnresolvedChange(change, "LLM failed to merge conflicting target node"))
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
            position = _find_add_position(current, change.post_node, post_nodes, target_nodes)
            if position is None:
                unresolved.append(UnresolvedChange(change, "target guard context is missing"))
                continue
            current = _replace_bytes(
                current,
                position,
                position,
                _prepare_insert_text(current, position, change.post_node.text),
            )
            applied.append(change)
            continue

        assert change.pre_node is not None
        if target_node is None:
            if change.action == "delete":
                continue
            unresolved.append(UnresolvedChange(change, "target node is missing"))
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
                merged = _resolve_conflict_with_llm(change, target_node)
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
            merged = _resolve_conflict_with_llm(change, target_node)
            if merged is None:
                unresolved.append(UnresolvedChange(change, "LLM failed to merge target diverged from pre and post"))
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
    )
