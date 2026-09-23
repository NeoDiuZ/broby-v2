#!/bin/sh
set -eu
python -c 'import runtime; runtime.validate()'
python -m spine.migrate
if [ "${BROBY_SEED_DEMO:-0}" = "1" ]; then
  python -m spine.seed
fi
# One API process owns the durable SQLite job queue and the mounted data volume.
exec uvicorn main:app --host :: --port "${PORT:-8000}" --workers 1 --timeout-graceful-shutdown 30
