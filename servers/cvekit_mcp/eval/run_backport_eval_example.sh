#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Copy this script or override these example values before running.
EVAL_NAME="${EVAL_NAME:-my_backport_eval}"
SOURCE_REPO="${SOURCE_REPO:-/path/to/source-kernel}"
SOURCE_BRANCH="${SOURCE_BRANCH:-origin/main}"
SOURCE_EXCEL="${SOURCE_EXCEL:-/path/to/source-commits.xlsx}"
TARGET_REPO="${TARGET_REPO:-/path/to/target-kernel}"
PR_URL="${PR_URL:-https://example.com/org/repo/pulls/123}"
FIRST_PR_COMMIT="${FIRST_PR_COMMIT:-FIRST_MANUAL_PR_COMMIT_SHA}"
LAST_PR_COMMIT="${LAST_PR_COMMIT:-LAST_MANUAL_PR_COMMIT_SHA}"
TEMP_BRANCH="${TEMP_BRANCH:-eval/my-backport-eval}"
CVEKIT="${CVEKIT:-/path/to/cvekit}"
CVEKIT_WORKDIR="${CVEKIT_WORKDIR:-/path/to/cvekit/workdir}"
OUTPUT_DIR="${OUTPUT_DIR:-/path/to/output-dir}"
LOG_ROOT="${LOG_ROOT:-$REPO_ROOT/logs}"

python3 "$REPO_ROOT/backport_eval.py" \
  --eval-name "$EVAL_NAME" \
  --source-repo "$SOURCE_REPO" \
  --source-branch "$SOURCE_BRANCH" \
  --source-excel "$SOURCE_EXCEL" \
  --target-repo "$TARGET_REPO" \
  --pr-url "$PR_URL" \
  --first-pr-commit "$FIRST_PR_COMMIT" \
  --last-pr-commit "$LAST_PR_COMMIT" \
  --temp-branch "$TEMP_BRANCH" \
  --cvekit "$CVEKIT" \
  --cvekit-workdir "$CVEKIT_WORKDIR" \
  --output-dir "$OUTPUT_DIR" \
  --log-root "$LOG_ROOT" \
  "$@"
