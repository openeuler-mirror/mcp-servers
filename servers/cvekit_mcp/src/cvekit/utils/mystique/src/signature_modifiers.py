"""恢复回移植过程中被大模型意外删除的目标函数签名修饰符。

本模块只处理目标函数原本存在、但回移植结果中缺失的已知内核修饰符，
避免因整函数重写丢失 ``__init``、``__exit``、``__user`` 等属性。
"""

import logging
import re


KERNEL_SIGNATURE_MODIFIERS = ("__init", "__exit", "__user")


def _modified_function_names(file_signatures: list[str] | None) -> set[str]:
    if not file_signatures:
        return set()
    return {sig.rsplit("#", 1)[-1] for sig in file_signatures}


def _signature_window(lines: list[str], line_index: int) -> str:
    start = line_index
    for idx in range(line_index - 1, max(-1, line_index - 6), -1):
        stripped = lines[idx].strip()
        if not stripped or stripped.endswith(";") or stripped.endswith("}"):
            break
        start = idx
        if "{" in stripped:
            break
    return " ".join(line.strip() for line in lines[start : line_index + 1])


def _target_function_modifiers(target_content: str, function_name: str) -> list[str]:
    lines = target_content.splitlines()
    pattern = re.compile(r"\b" + re.escape(function_name) + r"\s*\(")
    for idx, line in enumerate(lines):
        if not pattern.search(line):
            continue
        window = _signature_window(lines, idx)
        name_pos = window.find(function_name)
        if name_pos == -1:
            continue
        before_name = window[:name_pos]
        return [
            modifier
            for modifier in KERNEL_SIGNATURE_MODIFIERS
            if re.search(r"\b" + re.escape(modifier) + r"\b", before_name)
        ]
    return []


def restore_target_signature_modifiers(
    patched_code: str,
    target_content: str,
    file_signatures: list[str] | None,
) -> str:
    """Restore kernel function modifiers lost by analysis-only formatting."""
    function_names = _modified_function_names(file_signatures)
    if not function_names:
        return patched_code

    lines = patched_code.splitlines()
    changed = False

    for function_name in sorted(function_names):
        modifiers = _target_function_modifiers(target_content, function_name)
        if not modifiers:
            continue

        pattern = re.compile(r"\b" + re.escape(function_name) + r"\s*\(")
        for idx, line in enumerate(lines):
            if not pattern.search(line):
                continue

            window = _signature_window(lines, idx)
            missing = [
                modifier
                for modifier in modifiers
                if not re.search(r"\b" + re.escape(modifier) + r"\b", window)
            ]
            if not missing:
                break

            insert_pos = line.find(function_name)
            if insert_pos == -1:
                break
            prefix = line[:insert_pos].rstrip()
            suffix = line[insert_pos:]
            lines[idx] = f"{prefix} {' '.join(missing)} {suffix}"
            logging.info(
                "Restored kernel signature modifiers for %s: %s",
                function_name,
                " ".join(missing),
            )
            changed = True
            break

    if not changed:
        return patched_code
    return "\n".join(lines) + ("\n" if patched_code.endswith("\n") else "")
