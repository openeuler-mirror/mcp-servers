"""Test format normalization with validate_formatting tool and generate diff."""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

from common import Language
from main import _normalize_patched_formatting, _generate_unified_patch

patched_path = "patched_output/0_raw_crypto_algif_aead_c.c"
target_path = "/home/liping/Image/test-kernel1/crypto/algif_aead.c"
output_path = "patched_output/4_tooltest_crypto_algif_aead_c.c"

patched_code = open(patched_path).read()
target_content = open(target_path).read()
file_signatures = ["_aead_recvmsg", "aead_sock_destruct"]

logging.info("patched=%d chars, target=%d chars", len(patched_code), len(target_content))

result = _normalize_patched_formatting(
    patched_code, target_content, Language.C, file_signatures,
)

logging.info("result=%d chars", len(result))
open(output_path, "w").write(result)

# Compare with old normalized
old = open("patched_output/3_normalized_crypto_algif_aead_c.c").read()
logging.info("old normalized=%d chars, same=%s", len(old), result == old)

# Generate unified diffs
target_file_path = "crypto/algif_aead.c"
# Diff: target vs raw patched (before normalization)
diff_before = _generate_unified_patch(
    ".", "HEAD", target_file_path, patched_code,
    simplified_target=target_content,
)
# Diff: target vs normalized result (after normalization)
diff_after = _generate_unified_patch(
    ".", "HEAD", target_file_path, result,
    simplified_target=target_content,
)

print("\n" + "=" * 60)
print("BEFORE normalization (target vs raw patched):")
print("=" * 60)
if diff_before:
    print(diff_before[:4000])
else:
    print("(no diff)")

print("\n" + "=" * 60)
print("AFTER normalization (target vs normalized):")
print("=" * 60)
if diff_after:
    print(diff_after[:4000])
else:
    print("(no diff)")
