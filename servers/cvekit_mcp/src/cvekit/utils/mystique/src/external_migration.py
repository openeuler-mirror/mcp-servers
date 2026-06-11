"""Migrate file-level C nodes outside Mystique's function pipeline.

This module owns includes, object-like and function-like defines, and
file-level function prototypes. Function definitions remain owned by the
existing Mystique Joern and LLM pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from scubatrace.cpp.parser import CParser


EXTERNAL_QUERY = """
[
  (preproc_include)
  (preproc_def)
  (preproc_function_def)
  (declaration)
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


def extract_external_nodes(code: str) -> list[ExternalNode]:
    """Extract file-level nodes owned by the external migration pipeline."""
    parser = CParser()
    root = parser.parse(code)
    nodes: list[ExternalNode] = []

    for node in parser.query_all(root, EXTERNAL_QUERY):
        if _inside_function(node):
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
        elif node.type == "declaration":
            declarator = node.child_by_field_name("declarator")
            if declarator is None or declarator.type != "function_declarator":
                continue
            kind = "prototype"
            key = _declarator_name(declarator)
        else:
            continue

        if not key:
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

    return sorted(nodes, key=lambda item: item.start_byte)


def _normalized(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _detect_changes(pre_code: str, post_code: str) -> tuple[list[ExternalChange], list[ExternalNode]]:
    pre_nodes = extract_external_nodes(pre_code)
    post_nodes = extract_external_nodes(post_code)
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

    def sort_key(change: ExternalChange) -> tuple[int, int]:
        node = change.post_node or change.pre_node
        assert node is not None
        return (1 if change.action == "add" else 0, node.start_byte)

    return sorted(changes, key=sort_key), post_nodes


def _ensure_insert_text(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


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


def migrate_external_changes(pre_code: str, post_code: str, target_code: str) -> ExternalMigrationResult:
    """Migrate include, define and prototype changes with conservative three-way rules."""
    changes, post_nodes = _detect_changes(pre_code, post_code)
    current = target_code
    applied: list[ExternalChange] = []
    unresolved: list[UnresolvedChange] = []

    for change in changes:
        target_nodes = extract_external_nodes(current)
        target_by_id = {node.identity: node for node in target_nodes}
        target_node = target_by_id.get(change.identity)

        if change.action == "add":
            assert change.post_node is not None
            if target_node is not None:
                if _normalized(target_node.text) == _normalized(change.post_node.text):
                    continue
                unresolved.append(UnresolvedChange(change, "target already has a different node"))
                continue
            position = _find_add_position(current, change.post_node, post_nodes, target_nodes)
            if position is None:
                unresolved.append(UnresolvedChange(change, "target guard context is missing"))
                continue
            current = _replace_bytes(current, position, position, _ensure_insert_text(change.post_node.text))
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
                unresolved.append(UnresolvedChange(change, "target node diverged from pre"))
                continue
            current = _replace_bytes(current, target_node.start_byte, target_node.end_byte, "")
            applied.append(change)
            continue

        assert change.post_node is not None
        if _normalized(target_node.text) == _normalized(change.post_node.text):
            continue
        if _normalized(target_node.text) != _normalized(change.pre_node.text):
            unresolved.append(UnresolvedChange(change, "target node diverged from pre and post"))
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
