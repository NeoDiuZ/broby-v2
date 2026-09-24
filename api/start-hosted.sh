#!/bin/sh
set -eu
python -c 'import runtime; runtime.validate()'
python -m spine.migrate
if [ "${BROBY_SEED_DEMO:-0}" = "1" ]; then
  python -m spine.seed
fi
# One API process owns the durable job queue and the mounted file volume.
exec python serve.py
