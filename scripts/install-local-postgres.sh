#!/usr/bin/env bash
# Optional self-contained runtime for this Mac; no system service or sudo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=18.6
mkdir -p "$ROOT/.local/src"
cd "$ROOT/.local/src"
curl -fL "https://ftp.postgresql.org/pub/source/v$VERSION/postgresql-$VERSION.tar.bz2" -o postgresql.tar.bz2
curl -fL "https://ftp.postgresql.org/pub/source/v$VERSION/postgresql-$VERSION.tar.bz2.sha256" -o postgresql.sha256
"$ROOT/.venv/bin/python" - <<'PY'
from pathlib import Path
import hashlib
assert hashlib.sha256(Path('postgresql.tar.bz2').read_bytes()).hexdigest()==Path('postgresql.sha256').read_text().split()[0], 'Checksum mismatch'
PY
tar -xjf postgresql.tar.bz2
cd "postgresql-$VERSION"
./configure --prefix="$ROOT/.local/postgres" --without-icu --without-readline --without-zlib
make -j6
make install
"$ROOT/scripts/start-spine.sh"
