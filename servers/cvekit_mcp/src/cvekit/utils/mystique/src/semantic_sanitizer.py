"""检测并修复大模型输出中可确定判断的轻量语义损坏。

当前主要处理字符串字面量被错误换行的问题，并在修复后继续交由语法检查和
后续验证流程确认，避免把不确定的语义问题自动改写。
"""

from __future__ import annotations

import logging


def unescaped_newlines_in_strings(code: str) -> list[int]:
    """Return 1-based line numbers containing illegal newlines in strings."""
    lines: list[int] = []
    in_string = False
    escaped = False
    line = 1

    for char in code:
        if not in_string:
            if char == '"':
                in_string = True
                escaped = False
        elif char == "\n":
            if not escaped:
                lines.append(line)
            escaped = False
        elif escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = False

        if char == "\n":
            line += 1

    return lines


def repair_broken_string_newlines(code: str) -> str:
    """Repair an unescaped newline immediately before a closing string quote.

    This targets the common LLM corruption:

        pr_err("message
        ");

    and restores it to:

        pr_err("message\\n");

    Other multiline string damage is left untouched because its intent cannot
    be determined safely without additional context.
    """
    output: list[str] = []
    in_string = False
    escaped = False
    repairs = 0
    i = 0

    while i < len(code):
        char = code[i]

        if not in_string:
            output.append(char)
            if char == '"':
                in_string = True
                escaped = False
            i += 1
            continue

        if char == "\n" and not escaped:
            next_index = i + 1
            while next_index < len(code) and code[next_index] in " \t":
                next_index += 1
            if next_index < len(code) and code[next_index] == '"':
                output.append(r"\n")
                repairs += 1
                i = next_index
                continue

        output.append(char)
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = False
        i += 1

    if repairs:
        logging.warning(
            "Repaired %d newline-before-closing-quote string literal(s)",
            repairs,
        )
    return "".join(output)
