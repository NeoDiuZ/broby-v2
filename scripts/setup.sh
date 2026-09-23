#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if ! command -v node >/dev/null 2>&1; then export PATH="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH"; fi
if ! command -v pnpm >/dev/null 2>&1; then export PATH="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH"; fi
PYTHON="${BROBY_PYTHON:-python3}"
if [[ -x "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" && -z "${BROBY_PYTHON:-}" ]]; then PYTHON="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"; fi
[[ -x "$ROOT/.venv/bin/python" ]] || "$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/api/requirements.txt"
(cd "$ROOT/web" && pnpm install --frozen-lockfile)
