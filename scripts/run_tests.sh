#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "$PROJECT_ROOT"

echo "=== Running mystique unit tests (194 tests) ==="
/usr/bin/python3 -m pytest servers/cvekit_mcp/src/cvekit/utils/mystique/tests/ -q

echo ""
echo "=== Running cvekit entry tests ==="
/usr/bin/python3 -m pytest servers/cvekit_mcp/src/tests/test_cvekit_entry.py -q || true

echo ""
echo "=== Coverage report (mystique source modules) ==="
/usr/bin/python3 -m coverage run \
    --source="servers/cvekit_mcp/src/cvekit/utils/mystique/src" \
    -m pytest \
    servers/cvekit_mcp/src/cvekit/utils/mystique/tests/ \
    -q
/usr/bin/python3 -m coverage report -m --include="*/mystique/src/*"


