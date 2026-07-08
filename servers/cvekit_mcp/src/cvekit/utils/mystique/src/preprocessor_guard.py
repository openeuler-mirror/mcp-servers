"""Preserve target-side preprocessor guards during whole-function replacement."""

from collections import Counter, defaultdict
import re


_PREPROCESSOR_PREFIXES = (
    "#if",
    "#ifdef",
    "#ifndef",
    "#elif",
    "#else",
    "#endif",
)


def _is_preprocessor_guard(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(prefix) for prefix in _PREPROCESSOR_PREFIXES)


def _line_key(line: str) -> str:
    stripped = line.strip()
    if not stripped or _is_preprocessor_guard(line):
        return ""
    return "".join(stripped.split())


def _call_names(line: str) -> set[str]:
    """Return likely function-like call names from a C line."""
    return {
        match.group(1)
        for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", line)
        if match.group(1) not in {"if", "for", "while", "switch", "return", "sizeof"}
    }


def _occurrence_before(target_keys: list[str], index: int, key: str) -> int:
    """Count how many times `key` appears in target_keys[:index] (exclusive)."""
    count = 0
    for i in range(index):
        if target_keys[i] == key:
            count += 1
    return count


def _occurrence_after(target_keys: list[str], index: int, key: str) -> int:
    """Count how many times `key` appears in target_keys[index+1:]."""
    count = 0
    for i in range(index + 1, len(target_keys)):
        if target_keys[i] == key:
            count += 1
    return count


def _nearest_previous_anchor(target_keys: list[str], repl_positions: dict[str, list[int]], index: int) -> int | None:
    for cursor in range(index - 1, -1, -1):
        key = target_keys[cursor]
        if key and key in repl_positions:
            candidates = repl_positions[key]
            if len(candidates) == 1:
                return candidates[0]
            # This line at `cursor` is the (n_prev+1)-th occurrence of `key`
            # in target (0-indexed: n_prev). Match the same ordinal in replacement.
            n_prev = _occurrence_before(target_keys, cursor, key)
            if n_prev < len(candidates):
                return candidates[n_prev]
            return candidates[-1]
    return None


def _nearest_next_anchor(target_keys: list[str], repl_positions: dict[str, list[int]], index: int) -> int | None:
    for cursor in range(index + 1, len(target_keys)):
        key = target_keys[cursor]
        if key and key in repl_positions:
            candidates = repl_positions[key]
            if len(candidates) == 1:
                return candidates[0]
            # Match by occurrence counting from the end.
            # This line at `cursor` is the (n_after+1)-th occurrence of `key`
            # from the end in target. Match the same ordinal from the end.
            n_after = _occurrence_after(target_keys, cursor, key)
            idx = len(candidates) - 1 - n_after
            if idx >= 0:
                return candidates[idx]
            return candidates[0]
    return None


def _find_matching_opening(target_lines: list[str], endif_index: int) -> tuple[int, str] | None:
    """Find the matching #if/#ifdef/#ifndef for an #endif at target_lines[endif_index]."""
    depth = 1
    for i in range(endif_index - 1, -1, -1):
        stripped = target_lines[i].strip()
        if stripped.startswith("#endif"):
            depth += 1
        elif any(stripped.startswith(p) for p in ("#if", "#ifdef", "#ifndef")):
            depth -= 1
            if depth == 0:
                return i, stripped
    return None


def restore_lost_preprocessor_guards(target_function: str, replacement_function: str) -> str:
    """Restore preprocessor guard lines that a full-function replacement dropped.

    The recovery is intentionally conservative: only target guard lines missing
    from the replacement are restored, and only when a nearby non-preprocessor
    anchor line still exists in the replacement.
    """
    target_lines = target_function.splitlines(keepends=True)
    replacement_lines = replacement_function.splitlines(keepends=True)

    target_guard_counts = Counter(line.strip() for line in target_lines if _is_preprocessor_guard(line))
    if target_guard_counts:
        replacement_lines = [
            line
            for line in replacement_lines
            if not (
                _is_preprocessor_guard(line)
                and line.strip() in target_guard_counts
            )
        ]
    replacement_guard_counts = Counter(line.strip() for line in replacement_lines if _is_preprocessor_guard(line))
    missing_guard_counts = target_guard_counts - replacement_guard_counts
    if not missing_guard_counts:
        return replacement_function

    target_keys = [_line_key(line) for line in target_lines]
    repl_positions: dict[str, list[int]] = defaultdict(list)
    for index, line in enumerate(replacement_lines):
        key = _line_key(line)
        if key:
            repl_positions[key].append(index)

    # Pre-scan: when both an #endif and its matching opening guard are missing
    # AND the entire non-guard content between them is absent from the replacement,
    # the whole guarded block was intentionally removed — skip restoring either.
    #
    # Without this check, the guard restoration places the opening and closing
    # guards at unrelated positions, breaking compilation.
    _skip_restore: set[int] = set()
    _restore_pair_around_replacement: dict[tuple[int, int], tuple[int, int]] = {}
    replacement_call_names_by_line = [
        _call_names(line)
        for line in replacement_lines
    ]
    replacement_call_names = set().union(*replacement_call_names_by_line) if replacement_call_names_by_line else set()
    for i, line in enumerate(target_lines):
        stripped = line.strip()
        if not stripped.startswith("#endif"):
            continue
        if missing_guard_counts.get(stripped, 0) <= 0:
            continue
        pair = _find_matching_opening(target_lines, i)
        if pair is None:
            continue
        pair_idx, pair_stripped = pair
        if missing_guard_counts.get(pair_stripped, 0) <= 0:
            continue

        # Both opening and closing guards are missing.
        has_content = any(
            _line_key(target_lines[j]) and _line_key(target_lines[j]) in repl_positions
            for j in range(pair_idx + 1, i)
            if not _is_preprocessor_guard(target_lines[j])
        )
        if not has_content:
            guarded_call_names = set().union(*(
                _call_names(target_lines[j])
                for j in range(pair_idx + 1, i)
                if not _is_preprocessor_guard(target_lines[j])
            ))
            matching_call_names = guarded_call_names & replacement_call_names
            matching_repl_lines = [
                repl_index
                for repl_index, call_names in enumerate(replacement_call_names_by_line)
                if call_names & matching_call_names
            ]
            has_content = bool(matching_repl_lines)
            if matching_repl_lines:
                _restore_pair_around_replacement[(pair_idx, i)] = (
                    matching_repl_lines[0],
                    matching_repl_lines[-1],
                )
        if not has_content:
            has_content = any(
                _call_names(target_lines[j]) & replacement_call_names
                for j in range(pair_idx + 1, i)
                if not _is_preprocessor_guard(target_lines[j])
            )
        if not has_content:
            _skip_restore.add(pair_idx)
            _skip_restore.add(i)

    before: dict[int, list[str]] = defaultdict(list)
    after: dict[int, list[str]] = defaultdict(list)

    for (open_index, close_index), (first_repl, last_repl) in _restore_pair_around_replacement.items():
        open_guard = target_lines[open_index].strip()
        close_guard = target_lines[close_index].strip()
        if missing_guard_counts.get(open_guard, 0) > 0:
            before[first_repl].append(target_lines[open_index])
            missing_guard_counts[open_guard] -= 1
        if missing_guard_counts.get(close_guard, 0) > 0:
            after[last_repl].append(target_lines[close_index])
            missing_guard_counts[close_guard] -= 1

    for index, line in enumerate(target_lines):
        guard = line.strip()
        if not guard or missing_guard_counts.get(guard, 0) <= 0:
            continue
        if index in _skip_restore:
            missing_guard_counts[guard] -= 1
            continue

        if guard.startswith(("#if", "#ifdef", "#ifndef")):
            anchor = _nearest_next_anchor(target_keys, repl_positions, index)
            if anchor is not None:
                before[anchor].append(line)
                missing_guard_counts[guard] -= 1
            continue

        anchor = _nearest_previous_anchor(target_keys, repl_positions, index)
        if anchor is not None:
            after[anchor].append(line)
            missing_guard_counts[guard] -= 1

    restored: list[str] = []
    for index, line in enumerate(replacement_lines):
        restored.extend(before.get(index, []))
        restored.append(line)
        restored.extend(after.get(index, []))

    return "".join(restored)
