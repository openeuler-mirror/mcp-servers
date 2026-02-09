#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: run_specchain.sh (--servers-dir <dir> | --server-dir <dir>) --work-dir <dir> [--rpmbuild-root <dir>]

Runs the MCP spec packaging chain:
  1) Generate spec + tar.gz via generate_mcp_spec_gitcode.py
  2) Copy outputs to rpmbuild tree
  3) Build each spec with rpmbuild -ba

Options:
  --servers-dir <dir>   Parent directory containing MCP server subdirectories
  --server-dir <dir>    Single MCP server directory
  --work-dir <dir>      Working directory for copy/build (required)
  --rpmbuild-root <dir> RPM build root (default: ~/rpmbuild)
  -h, --help            Show help
USAGE
}

servers_dir=""
server_dir=""
work_dir=""
rpmbuild_root="$HOME/rpmbuild"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --servers-dir)
      servers_dir="$2"
      shift 2
      ;;
    --server-dir)
      server_dir="$2"
      shift 2
      ;;
    --work-dir)
      work_dir="$2"
      shift 2
      ;;
    --rpmbuild-root)
      rpmbuild_root="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$work_dir" ]]; then
  echo "--work-dir is required" >&2
  usage >&2
  exit 1
fi

if [[ -n "$servers_dir" && -n "$server_dir" ]] || [[ -z "$servers_dir" && -z "$server_dir" ]]; then
  echo "Provide exactly one of --servers-dir or --server-dir" >&2
  usage >&2
  exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$script_dir"

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'
  RESET=$'\033[0m'
  CYAN=$'\033[36m'
  GREEN=$'\033[32m'
else
  BOLD=""
  RESET=""
  CYAN=""
  GREEN=""
fi

banner() {
  local label="$1"
  local step="$2"
  printf "\n${BOLD}${CYAN}╔══════════════════════════════════════╗${RESET}\n"
  printf "${BOLD}${CYAN}║ %-36s ║${RESET}\n" "$label"
  printf "${BOLD}${CYAN}╚══════════════════════════════════════╝${RESET}\n"
  printf "${BOLD}${GREEN}>>${RESET} ${BOLD}%s${RESET}\n\n" "$step"
}

banner "Phase 1/3" "Generating spec and tar.gz..."
cmd=(python scripts/generate_mcp_spec_gitcode.py --work-dir "$work_dir")
if [[ -n "$servers_dir" ]]; then
  cmd+=(--servers-dir "$servers_dir")
else
  cmd+=(--server-dir "$server_dir")
fi
"${cmd[@]}"

banner "Phase 2/3" "Copying outputs to rpmbuild tree..."
spec_dir="$rpmbuild_root/SPECS"
src_dir="$rpmbuild_root/SOURCES"
mkdir -p "$spec_dir" "$src_dir"

mapfile -t spec_files < <(find "$work_dir" -type f -name "*.spec" | sort)
if [[ ${#spec_files[@]} -eq 0 ]]; then
  echo "No .spec files found under $work_dir" >&2
  exit 2
fi

mapfile -t tar_files < <(find "$work_dir" -type f -name "*.tar.gz" | sort)
if [[ ${#tar_files[@]} -eq 0 ]]; then
  echo "No .tar.gz files found under $work_dir" >&2
  exit 3
fi

for spec in "${spec_files[@]}"; do
  cp -f "$spec" "$spec_dir/"
done
for tarball in "${tar_files[@]}"; do
  cp -f "$tarball" "$src_dir/"
done

banner "Phase 3/3" "Building rpms..."
for spec in "${spec_files[@]}"; do
  spec_name=$(basename "$spec")
  echo "- building: $spec_name"
  rpmbuild -ba "$spec_dir/$spec_name"
done

echo "Done."
