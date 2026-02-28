#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: run_manual_chain.sh --software-name <name> [--manual-path <path>] [--server-root <dir>] [--llm-provider <name>] [--api-key <key>] [--max-manual-chars <n>] [--debug] [--logdir <dir>]

Runs the MCP generation chain:
  1) fetch manual (if manual-path not provided)
  2) generate MCP server

Options:
  --software-name <name>    Software name (required)
  --manual-path <path>      Manual snippet path (optional)
  --server-root <dir>       Output servers root (optional)
  --llm-provider <name>     LLM provider (default: openai)
  --api-key <key>           LLM API key (optional; otherwise from env)
  --max-manual-chars <n>    Max manual chars (optional)
  --debug                   Enable debug logs
  --logdir <dir>            Logs/output dir (default: .logs)
  -h, --help                Show help
USAGE
}

software_name=""
manual_path=""
server_root=""
llm_provider=""
api_key=""
max_manual_chars=""
debug=false
logdir=".logs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --software-name)
      software_name="$2"
      shift 2
      ;;
    --manual-path)
      manual_path="$2"
      shift 2
      ;;
    --server-root)
      server_root="$2"
      shift 2
      ;;
    --llm-provider)
      llm_provider="$2"
      shift 2
      ;;
    --api-key)
      api_key="$2"
      shift 2
      ;;
    --max-manual-chars)
      max_manual_chars="$2"
      shift 2
      ;;
    --debug)
      debug=true
      shift
      ;;
    --logdir)
      logdir="$2"
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

if [[ -z "$software_name" ]]; then
  echo "--software-name is required" >&2
  usage >&2
  exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$script_dir"

mkdir -p "$logdir"

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

banner "Phase 1/1" "Generating MCP server..."
cmd=(python scripts/manual_mcp_generator.py --software-name "$software_name")
if [[ -n "$manual_path" ]]; then
  cmd+=(--manual-path "$manual_path")
fi
if [[ -n "$server_root" ]]; then
  cmd+=(--server-root "$server_root")
fi
if [[ -n "$llm_provider" ]]; then
  cmd+=(--llm-provider "$llm_provider")
fi
if [[ -n "$api_key" ]]; then
  cmd+=(--api-key "$api_key")
fi
if [[ -n "$max_manual_chars" ]]; then
  cmd+=(--max-manual-chars "$max_manual_chars")
fi
if [[ "$debug" == true ]]; then
  cmd+=(--debug)
fi

timestamp=$(date +"%Y%m%d_%H%M%S")
logfile="$logdir/manual_mcp_${software_name}_${timestamp}.log"
set +e
"${cmd[@]}" | tee "$logfile"
status=${PIPESTATUS[0]}
set -e
if [[ $status -ne 0 ]]; then
  echo "Failed. See log: $logfile" >&2
  exit "$status"
fi

echo "Done. Log: $logfile"