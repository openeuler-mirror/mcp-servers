"""Regex-based C function boundary parser.

Used as the primary function detector for C code because tree-sitter
frequently misparses Linux kernel code containing complex macros
(get_random_once, __aligned, __init, etc.), causing single functions
to be identified as spanning hundreds of lines.

This parser handles the common kernel code patterns:
- Multi-line function signatures (parameters spanning multiple lines)
- Kernel type qualifiers (static, inline, __init, __always_inline, etc.)
- Complex return types (const struct foo *, unsigned long, etc.)
"""

import logging
import re
from dataclasses import dataclass


@dataclass
class FuncInfo:
    name: str       # function name only
    start_line: int  # 1-based, line with return type
    end_line: int    # 1-based, closing brace line


# Control flow / block keywords that contain (...) { but are not functions
_CONTROL_KEYWORDS = frozenset({
    "if", "else", "while", "for", "switch", "do", "catch",
    "typeof", "typeof_member", "__typeof__",
})

# Matches C function definitions.
# Group "ret": return type (one or more word chars/qualifiers followed by space)
# Group "sig": function_name(params...)
# Group "name": the actual function name
_FUNC_RE = re.compile(
    r"^(?P<ret>(?:[\w\*]+\s+)+)"      # return type: word(s) + space(s)
    r"(?P<sig>(?P<name>\w+)\s*\([^;]*)",  # func_name( ... )
)


def parse_functions(source: str) -> list[FuncInfo]:
    """Find C function boundaries using regex + balanced brace matching.

    Handles kernel code patterns that tree-sitter struggles with:
    - Multi-line function signatures
    - Complex type qualifiers and macros
    - Nested braces in parameters (e.g., function pointer params)

    Returns list of FuncInfo with 1-based line numbers.
    """
    lines = source.split("\n")
    n = len(lines)
    functions: list[FuncInfo] = []

    i = 0
    while i < n:
        line = lines[i]
        stripped = line.lstrip()

        # Skip preprocessor directives, empty lines, lone braces, and comment lines
        if stripped.startswith("#") or stripped in ("{", "}", "") or stripped.startswith("//"):
            i += 1
            continue

        # Skip comment blocks /* ... */ or /** ... */
        if stripped.startswith("/*"):
            # Single-line comment: /* ... */ on one line
            if "*/" in stripped:
                i += 1
                continue
            # Multi-line comment: skip to end of comment block
            i += 1
            while i < n:
                if "*/" in lines[i]:
                    i += 1
                    break
                i += 1
            continue

        # Skip kernel doc continuation lines (* description)
        if stripped.startswith("*"):
            i += 1
            continue

        # --- Step 1: collect signature lines until we see '{' after balanced parens ---
        sig_start = i
        paren_depth = 0
        has_paren = False
        sig_lines: list[str] = []
        brace_line: int | None = None
        stop_at: int | None = None  # line to jump to if this isn't a function

        j = i
        while j < n:
            cur = lines[j]
            cur_stripped = cur.lstrip()

            if cur_stripped.startswith("#"):
                if not sig_lines:
                    i = j + 1
                    break
                j += 1
                continue

            # Skip over kernel doc comment blocks (/** ... */).
            # These contain parentheses like @param (description) which
            # would otherwise confuse the parenthesis counter.
            if cur_stripped.startswith("/**"):
                if sig_lines:
                    # Comment block mid-signature - unlikely to be a function
                    break
                # Single-line kernel-doc comment: /** ... */ on one line
                if "*/" in cur_stripped:
                    j += 1
                    i = j
                    continue
                # Skip to end of multi-line comment block
                j += 1
                while j < n:
                    if "*/" in lines[j]:
                        j += 1
                        break
                    j += 1
                i = j
                continue

            sig_lines.append(cur)

            # Track parentheses
            for ch in cur:
                if ch == "(":
                    paren_depth += 1
                    has_paren = True
                elif ch == ")":
                    paren_depth -= 1

            # ';' without '{' → declaration, not definition
            if ";" in cur and "{" not in cur:
                stop_at = j + 1
                break

            # Found '{' after balanced parens with at least one pair of parens
            if has_paren and paren_depth == 0 and "{" in cur:
                brace_line = j
                stop_at = j + 1  # if regex fails, skip past the '{'
                break

            # ')' found but no '{' on this line — check next line
            if has_paren and paren_depth == 0 and ")" in cur:
                if j + 1 < n and lines[j + 1].lstrip().startswith("{"):
                    sig_lines.append(lines[j + 1])
                    brace_line = j + 1
                    stop_at = j + 2  # if regex fails, skip past the '{'
                    break
                else:
                    stop_at = j + 1
                    break

            # Safety: if paren goes negative, reset
            if paren_depth < 0:
                stop_at = j + 1
                break

            j += 1
        else:
            # Reached end of file
            i = n
            continue

        # If we didn't reach the break point, advance
        if brace_line is None:
            i = stop_at if stop_at is not None else j + 1
            continue

        # --- Step 2: try to match as a function definition ---
        full_sig = "\n".join(sig_lines).strip()

        # Must have parens and end with '{'
        if "(" not in full_sig or not full_sig.endswith("{"):
            i = stop_at
            continue

        # Filter out kernel doc comment lines (/** ... */) that precede the
        # function signature, so full_sig starts with the return type.
        # This handles cases like:
        #   /**
        #    * func_name - description
        #    */
        #   return_type func_name(...) {
        sig_lines_filtered: list[str] = []
        in_comment = False
        for line in sig_lines:
            stripped = line.lstrip()
            # Detect start/end of comment blocks
            if stripped.startswith("/**"):
                in_comment = True
                continue
            if in_comment and stripped.startswith("*/"):
                in_comment = False
                continue
            if in_comment:
                continue
            sig_lines_filtered.append(line)

        full_sig = "\n".join(sig_lines_filtered).strip()
        if "(" not in full_sig or not full_sig.endswith("{"):
            i = stop_at
            continue

        m = _FUNC_RE.match(full_sig)
        if not m:
            i = stop_at
            continue

        name = m.group("name")
        if name in _CONTROL_KEYWORDS:
            i = stop_at
            continue

        ret = m.group("ret").strip()
        if not ret:
            i = stop_at
            continue

        # --- Step 3: find function end via balanced brace counting ---
        brace_count = 0
        end_idx = brace_line
        for k in range(brace_line, n):
            for ch in lines[k]:
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
            if brace_count == 0:
                end_idx = k
                break

        if brace_count == 0:
            functions.append(FuncInfo(
                name=name,
                start_line=sig_start + 1,
                end_line=end_idx + 1,
            ))

        i = brace_line + 1

    return functions


def parse_functions_with_tree_sitter(source: str) -> list[FuncInfo]:
    """使用正则主解析器，并通过 Tree-sitter 补充遗漏的 C 函数定义。"""
    functions = parse_functions(source)
    confirmed_ranges = [
        (function.start_line, function.end_line)
        for function in functions
    ]
    known_names = {function.name for function in functions}

    try:
        import ast_parser
        from common import Language

        parser = ast_parser.ASTParser(source, Language.C)
    except Exception as exc:
        logging.warning("tree-sitter parse failed: %s", exc)
        return functions

    candidates: list[FuncInfo] = []
    for node in parser.query_all(ast_parser.TS_C_METHOD):
        if node.end_point[0] - node.start_point[0] > 300:
            continue

        name_node = node.child_by_field_name("declarator")
        while name_node is not None and name_node.type != "identifier":
            nested_declarator = name_node.child_by_field_name("declarator")
            if nested_declarator is not None:
                name_node = nested_declarator
                continue
            name_node = next(
                (child for child in name_node.named_children if child.type == "identifier"),
                None,
            )

        if name_node is None or name_node.type != "identifier":
            continue

        text = node.text.decode()
        if text.lstrip().startswith(".") and "=" in text.split("{", 1)[0]:
            continue

        candidates.append(
            FuncInfo(
                name=name_node.text.decode(),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            )
        )

    # 外层函数先处理，避免把未展开宏产生的内部候选当成真实函数。
    candidates.sort(key=lambda function: (function.start_line, -function.end_line))
    for candidate in candidates:
        if candidate.name in known_names:
            continue
        if any(
            start <= candidate.start_line
            and candidate.end_line <= end
            and (start < candidate.start_line or candidate.end_line < end)
            for start, end in confirmed_ranges
        ):
            continue
        functions.append(candidate)
        confirmed_ranges.append((candidate.start_line, candidate.end_line))
        known_names.add(candidate.name)

    functions.sort(key=lambda function: function.start_line)
    return functions
