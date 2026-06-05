"""End-to-end test: call _joint_llm_fix for ctnetlink_alloc_expect and check output."""
import sys
import os
import logging
from types import SimpleNamespace

sys.path.insert(0, "src")
os.chdir("/home/liping/mystique")

import config
from cross_method import _joint_llm_fix, _build_joint_fix_prompt
from common import Language

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

METHOD_DIR = "cache/e7357ee9d5/method#1/ctnetlink_alloc_expect#2703#2760#3.target.c"
SIGNATURE = "3.target.c#ctnetlink_alloc_expect"


def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()


def count_braces(code: str) -> tuple[int, int]:
    """Count { and } ignoring comments, strings, char literals."""
    opens = closes = 0
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch == "/" and i + 1 < n and code[i + 1] == "/":
            i += 2
            while i < n and code[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and code[i + 1] == "*":
            i += 2
            while i + 1 < n and not (code[i] == "*" and code[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == '"':
            i += 1
            while i < n and code[i] != '"':
                if code[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if ch == "'":
            i += 1
            while i < n and code[i] != "'":
                if code[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if ch == "{":
            opens += 1
        elif ch == "}":
            closes += 1
        i += 1
    return opens, closes


def check_output(label: str, code: str) -> bool:
    """Print bracket balance and basic structure check for generated code."""
    print(f"\n--- {label} ---")
    opens, closes = count_braces(code)
    balanced = opens == closes
    print(f"  Braces: {{ = {opens}, }} = {closes} -> {'BALANCED' if balanced else 'EXTRA } MISMATCH!'}")
    if not balanced:
        print(f"  >>> DIFF: {closes - opens} extra closing brace(s) <<<")

    # Show the lines around any suspicious extra }
    lines = code.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "}" and i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].strip().startswith("/* PLACEHOLDER"):
            print(f"  [WARN] Line {i+1}: '}}' followed by code on line {i+2}: {lines[i+1].strip()[:80]}")

    # Print code for inspection
    print(f"  Code ({len(code)} chars, {len(lines)} lines):")
    for i, line in enumerate(lines):
        print(f"    {i+1:3d}: {line}")
    return balanced


def main():
    # Read input files
    pre_sliced = read_file(f"{METHOD_DIR}/1.pre@s.c")
    patch = read_file(f"{METHOD_DIR}/patch.diff")
    target_sp = read_file(f"{METHOD_DIR}/3.target@sp.c")
    # Read target slice lines from 3.target@s.c to understand the slice lines
    target_sliced = read_file(f"{METHOD_DIR}/3.target@s.c")

    # Calculate target_slice_lines from 3.target@s.c (the sliced target without placeholders)
    # Each non-blank, non-comment-only line in 3.target@s.c is a slice line
    target_slice_lines = set()
    for i, line in enumerate(target_sliced.splitlines()):
        stripped = line.strip()
        if stripped and stripped != "{":  # count actual code lines
            pass  # We'll use a simpler approach: just check if it's non-empty
    # target_slice_lines: just need to be non-empty for placeholder mode
    target_slice_lines = {1, 2, 3}  # minimal non-empty set to trigger placeholder path

    # Build minimal mock artifact with just the fields _build_joint_fix_prompt needs
    mock_artifact = SimpleNamespace(
        signature=SIGNATURE,
        method_dir=METHOD_DIR,
        file_suffix=".c",
        target_start_line=2703,
        target_end_line=2760,
        target_slice_lines=target_slice_lines,
        pre_sliced_code=pre_sliced,
        patch_code=patch,
        target_sliced_code=target_sliced,
        target_sliced_code_placeholder=target_sp,
        called_names=set(),
        identifiers=set(),
    )
    # target_method is needed by _repair_placeholder_mismatch via artifact.target_sliced_code_placeholder
    # We skip that by providing the placeholder code directly
    # target_method is NOT used by _build_joint_fix_prompt or _joint_llm_fix directly
    # BUT _repair_placeholder_mismatch uses it for artifact.target_sliced_code_placeholder (we have that)
    mock_artifact.target_method = None  # won't be used if we skip recover_placeholder

    artifacts = {SIGNATURE: mock_artifact}

    print("=" * 60)
    print("Calling _joint_llm_fix for ctnetlink_alloc_expect...")
    print(f"  pre@s.c: {len(pre_sliced)} chars")
    print(f"  patch.diff: {len(patch)} chars")
    print(f"  target@sp.c: {len(target_sp)} chars")
    print(f"  target@s.c (for slice_lines): {len(target_sliced)} chars")
    print("=" * 60)

    result = _joint_llm_fix(
        signatures=[SIGNATURE],
        artifacts_by_signature=artifacts,
        language=Language.C,
        new_defines=None,
    )

    if not result or SIGNATURE not in result:
        print("\nFAIL: _joint_llm_fix returned no result for the signature.")
        return 1

    llm_code = result[SIGNATURE]
    print(f"\nLLM returned code: {len(llm_code)} chars")

    ok = check_output("LLM generated code (5.ours@sp.c equivalent)", llm_code)

    # Also save to compare
    output_path = f"{METHOD_DIR}/test_ours@sp.c"
    with open(output_path, "w") as f:
        f.write(llm_code)
    print(f"\nSaved to: {output_path}")

    if ok:
        print("\nPASS: LLM output has balanced braces.")
    else:
        print("\nFAIL: LLM output still has unbalanced braces.")
        print("The prompt changes may need further refinement or the model needs retry.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
