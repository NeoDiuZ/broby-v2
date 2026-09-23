#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG="$ROOT/.local/postgres/bin"
[[ -x "$PG/postgres" ]] || { echo 'Install PostgreSQL and set BROBY_SPINE_URL, or build the local runtime described in docs/FIRST_BUILD.md.'; exit 1; }
mkdir -p "$ROOT/.local/socket"
chmod 700 "$ROOT/.local" "$ROOT/.local/socket"
if [[ ! -f "$ROOT/.local/pgdata/PG_VERSION" ]]; then
 "$ROOT/.venv/bin/python" -c 'import secrets,pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_text(secrets.token_urlsafe(32)); p.chmod(0o600)' "$ROOT/.local/pg-password"
 "$PG/initdb" -D "$ROOT/.local/pgdata" -U broby --encoding=UTF8 --locale=C --auth-local=trust --auth-host=scram-sha-256 --pwfile="$ROOT/.local/pg-password" > "$ROOT/.local/pg-init.log"
fi
if ! "$PG/pg_ctl" -D "$ROOT/.local/pgdata" status >/dev/null 2>&1; then
 "$PG/pg_ctl" -D "$ROOT/.local/pgdata" -l "$ROOT/.local/postgres.log" -o "-h 127.0.0.1 -p 55432 -k $ROOT/.local/socket" start
fi
if ! "$PG/psql" -h "$ROOT/.local/socket" -p 55432 -U broby -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='broby_spine'" | grep -q 1; then
 "$PG/createdb" -h "$ROOT/.local/socket" -p 55432 -U broby broby_spine
fi
"$ROOT/.venv/bin/python" - "$ROOT" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1]);path=root/'.env';text=path.read_text() if path.exists() else ''
if 'BROBY_SPINE_URL=' not in text:
 password=(root/'.local/pg-password').read_text().strip()
 path.write_text(text+'\nBROBY_SPINE_URL=postgresql+psycopg://broby:'+password+'@127.0.0.1:55432/broby_spine\n');path.chmod(0o600)
PY
(cd "$ROOT/api" && ../.venv/bin/python -m spine.migrate)
