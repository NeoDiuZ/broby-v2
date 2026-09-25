#!/bin/sh
set -eu
python -c 'import runtime; runtime.validate()'
if [ "${BROBY_PROCESS_ROLE:-api}" = "worker" ]; then
  # Schema and accounts are prepared by the API; a worker never runs migrations.
  exec python worker.py
fi
python -m spine.migrate
if [ "${BROBY_SEED_DEMO:-0}" = "1" ]; then
  python -m spine.seed
fi
# Embedded remains the default. External mode starts no workers in the API.
exec python serve.py
