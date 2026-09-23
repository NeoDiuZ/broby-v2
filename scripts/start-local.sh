#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if ! command -v node >/dev/null 2>&1; then export PATH="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH"; fi
command -v node >/dev/null || { echo 'Node.js 20.9+ is required.'; exit 1; }
[[ -x "$ROOT/.venv/bin/python" && -f "$ROOT/web/.next/BUILD_ID" ]] || { echo 'Run scripts/setup.sh and scripts/build.sh first.'; exit 1; }
if [[ -x "$ROOT/.local/postgres/bin/postgres" ]]; then "$ROOT/scripts/start-spine.sh"; fi
pids=()
cleanup(){ if [[ ${#pids[@]} -gt 0 ]]; then for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; fi; }
trap cleanup EXIT INT TERM
if ! curl -fsS http://127.0.0.1:8100/api/health >/dev/null 2>&1; then
 (cd "$ROOT/api" && exec ../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8100) & pids+=("$!")
fi
if ! curl -fsS http://127.0.0.1:3100 >/dev/null 2>&1; then
 (cd "$ROOT/web" && exec node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3100) & pids+=("$!")
fi
echo 'Website:   http://127.0.0.1:3100'
echo 'Workspace: http://127.0.0.1:3100/app'
if [[ ${#pids[@]} -gt 0 ]]; then wait; else echo 'Local services are already running.'; fi
