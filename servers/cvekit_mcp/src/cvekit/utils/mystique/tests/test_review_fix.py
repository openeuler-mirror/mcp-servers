#!/usr/bin/env python3
"""Test _review_and_fix_patch on the nf_conntrack_netlink.c CVE-2026-31414 case.

The generated patch incorrectly deletes ``#if IS_ENABLED(CONFIG_NF_NAT)``
and ``#endif`` because Joern cannot handle preprocessor directives.
"""

import logging
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import config
import joern
import log
from common import Language
from main import _extract_file_patch, _review_and_fix_patch

log.init_logger(logging.getLogger(), logging.DEBUG, "test_review_log")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

PATCHED_OUTPUT = os.path.join(os.path.dirname(__file__), "patched_output")
COMBINED_PATCH = os.path.join(PATCHED_OUTPUT, "backported_CVE-2026-31414_e7ccaa0a62a8.patch")
NORMALIZED_FILE = os.path.join(PATCHED_OUTPUT, "3_normalized_net_netfilter_nf_conntrack_netlink_c.c")

SOURCE_REPO = "/home/liping/Image/linux-old1"
TARGET_REPO = "/home/liping/Image/test-kernel1"
COMMIT = "e7ccaa0a62a8ff2be5d521299ce79390c318d306"
FILE_NAME = "net/netfilter/nf_conntrack_netlink.c"
TARGET_FILE = os.path.join(TARGET_REPO, FILE_NAME)


def extract_file_section(combined: str, file_path: str) -> str | None:
    marker = f"diff --git a/{file_path} b/{file_path}\n"
    idx = combined.find(marker)
    if idx == -1:
        return None
    rest = combined[idx + len(marker):]
    next_idx = rest.find("\ndiff --git ")
    tail_idx = rest.find("\n-- \n")
    end = next_idx if next_idx != -1 else (tail_idx if tail_idx != -1 else len(rest))
    return marker + rest[:end] + "\n"


def deletions(diff: str) -> set[str]:
    return {l[1:].strip() for l in diff.splitlines()
            if l.startswith("-") and not l.startswith("---") and l[1:].strip()}


def main():
    print("=" * 70)
    print("Test _review_and_fix_patch — nf_conntrack_netlink.c")
    print("=" * 70)

    # 1. Get original file_patch from source repo
    print("\n[1] Getting original file_patch from source repo...")
    import git
    repo = git.Repo(SOURCE_REPO)
    patch_text = repo.git.format_patch("-1", COMMIT, stdout=True)
    file_patch = _extract_file_patch(patch_text, FILE_NAME)
    if not file_patch:
        print("ERROR: could not extract file_patch")
        return 1
    print(f"    file_patch: {len(file_patch)} chars")

    # 2. Read patched_code & target_content & generated patch_diff
    print("\n[2] Reading inputs...")
    with open(NORMALIZED_FILE) as f:
        patched_code = f.read()
    with open(TARGET_FILE) as f:
        target_content = f.read()
    with open(COMBINED_PATCH) as f:
        patch_diff = extract_file_section(f.read(), FILE_NAME)
    if not patch_diff:
        print("ERROR: could not extract patch_diff")
        return 1
    print(f"    target_content: {len(target_content)} chars, {len(target_content.splitlines())} lines")
    print(f"    patched_code:   {len(patched_code)} chars, {len(patched_code.splitlines())} lines")
    print(f"    patch_diff:     {len(patch_diff)} chars")

    # 3. Compare: spurious preprocessor/comment deletions
    print("\n[3] Finding spurious deletions...")
    orig_del = deletions(file_patch)
    gen_del = deletions(patch_diff)
    spurious = {l for l in gen_del
                if (l.startswith("#") or l.startswith("//") or l.startswith("/*"))
                and l not in orig_del}
    print(f"    Original deletions:  {len(orig_del)}")
    print(f"    Generated deletions: {len(gen_del)}")
    print(f"    Spurious (preprocessor in gen but NOT in orig): {len(spurious)}")
    for s in sorted(spurious):
        print(f"      -{s}")

    if not spurious:
        print("\n    No spurious deletions — nothing to test.")
        return 0

    # 4. Call _review_and_fix_patch
    print("\n[4] Calling _review_and_fix_patch (LLM agent with viewcode tool)...")

    fixed_code, fixed_diff = _review_and_fix_patch(
        file_patch=file_patch,
        patch_diff=patch_diff,
        patched_code=patched_code,
        target_content=target_content,
        target_path=TARGET_REPO,
        target_ref="HEAD",
        target_file_path=FILE_NAME,
        language=Language.C,
    )

    # 5. Verify — check regenerated diff's deletions, not whole-file string search
    print("\n[5] Verifying (checking regenerated diff)...")

    fixed_del = deletions(fixed_diff)
    new_gen_del = deletions(patch_diff)

    still_spurious = [s for s in spurious if s in fixed_del]
    restored = [s for s in spurious if s not in fixed_del]

    print(f"    Resolved (no longer deleted): {len(restored)}/{len(spurious)}")
    for r in sorted(restored):
        print(f"      ✓ {r} — no longer appears as deletion")
    if still_spurious:
        print(f"    Still spurious in fixed diff: {len(still_spurious)}")
        for s in still_spurious:
            print(f"      ✗ {s}")
    else:
        print("    ✅ No spurious deletions in fixed diff!")

    out_f = os.path.join(PATCHED_OUTPUT, "6_review_fixed_nf_conntrack_netlink.c")
    out_d = os.path.join(PATCHED_OUTPUT, "6_review_fixed_nf_conntrack_netlink.diff")
    with open(out_f, "w") as f:
        f.write(fixed_code)
    with open(out_d, "w") as f:
        f.write(fixed_diff)
    print(f"\n    Outputs: {out_f}, {out_d}")

    print("\n" + "=" * 70)
    if restored and not still_spurious:
        print("TEST PASSED ✅")
        return 0
    else:
        print("TEST FAILED ❌")
        return 1


if __name__ == "__main__":
    sys.exit(main())
