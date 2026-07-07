"""Helpers for deriving metadata from applied method replacements."""

from __future__ import annotations

import logging

from common import Language


def successful_target_names_from_replacements(
    replacements: list[tuple],
    artifacts_by_signature: dict,
    language: Language,
) -> set[str]:
    """Return every target function actually present in successful replacements."""
    names: set[str] = set()
    parse_c_functions = None
    if language == Language.C:
        from func_parser import parse_functions

        parse_c_functions = parse_functions

    for replacement in replacements:
        signature = replacement[0]
        replacement_code = replacement[3]
        artifact = artifacts_by_signature.get(signature)
        target_method = getattr(artifact, "target_method", None) if artifact else None
        target_name = getattr(target_method, "name", None)
        if target_name:
            names.add(target_name)
        else:
            names.add(signature.rsplit("#", 1)[-1])

        if parse_c_functions is None:
            continue
        try:
            replacement_functions = parse_c_functions(replacement_code)
        except Exception as exc:  # pragma: no cover - parser fallback is best-effort metadata.
            logging.debug("解析 replacement 函数名失败: signature=%s error=%s", signature, exc)
            continue
        for function in replacement_functions:
            names.add(function.name)

    return names
