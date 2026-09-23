# Broby v2 — development handover

The patient-record foundation now uses **FastAPI, SQLAlchemy 2.0, Alembic and PostgreSQL**, with Next.js/React/TypeScript and Tailwind on the frontend. The original production checkout is untouched. This remains a local synthetic-data preview, not a production replacement.

Handover review: [PR #1](https://github.com/NeoDiuZ/broby-v2/pull/1). The complete source is on `codex/v2-handover` until that PR is merged; `main` initially contains only the repository scaffold. Clone with `git clone --branch codex/v2-handover https://github.com/NeoDiuZ/broby-v2.git`.

## Open

- [Workspace](http://127.0.0.1:3100/app) — Patients → Milo → Timeline / Observations
- [Preserved website](http://127.0.0.1:3100)
- [API reference](http://127.0.0.1:8100/docs)

Website and app now share port **3100**. `/` serves the preserved website, `/app` the clinic workspace, `/owner` the owner portal, and `/api/*` proxies the internal API on 8100. Port 3101 is no longer needed. `web/` is the active combined frontend; `website/` is retained as the original reference.

Start with [HANDOVER.md](HANDOVER.md), then [Railway deployment plan](docs/DEPLOYMENT.md) and [database migration plan](docs/DATABASE_HANDOVER.md). The target is a **new, isolated Railway project with Railway PostgreSQL**. Supabase and Sites are no longer deployment targets. No cloud deployment has been performed.

## Run and test

```sh
./scripts/setup.sh
./scripts/start-spine.sh
(cd api && ../.venv/bin/python -m spine.seed)
./scripts/build.sh
./scripts/start-local.sh
# Separate terminal:
.venv/bin/python scripts/simulate-lab.py
.venv/bin/python -m pytest -q
```

The local PostgreSQL runtime is installed on this Mac. A fresh machine needs PostgreSQL or the optional `scripts/install-local-postgres.sh` source build. See [first-build instructions](docs/FIRST_BUILD.md) for configuration and recovery.

## What changed and why

Lab results now enter an independent patient-scoped event, with one observation per measurement and a receipt on every supplied source. Clinic-wide dedupe prevents duplicate events across senders/retries. Missing sources are visibly flagged. Only laboratory-supplied ranges drive high/low flags; no AI judges results. Cursor-based APIs feed the patient directory, day-grouped timeline and reference-band chart. Chart points open their originating event and positioned source.

The [API contract](docs/V2_CONTRACT.md) is explicit and the first schema is a frozen Alembic migration. **51 tests pass**, including real PostgreSQL acceptance tests for all five required first-build behaviours. The unified frontend production build passes. The browser flow and PostgreSQL backup restoration were checked.

## Important transition boundary

Existing scheduling, billing, capture and other PMS workflows are preserved on SQLite while patient/clinical data is projected into the normalized spine. New v2 events are visible in the new record screens; older assistant, owner-sharing and reporting modules still need migration to consume them. This is not yet a single-store whole-product replacement. Exact mockup parity and handover review remain outstanding; the referenced mockup directory was unavailable. Mobile and the extension are deferred.

See [acceptance and remaining work](docs/FIRST_BUILD.md), [full-product status](docs/FEATURE_STATUS.md), and the [earlier workflow guide](docs/PREVIEW_GUIDE.md). For backups of both stores, stop the API and run `.venv/bin/python scripts/backup-local.py /new/backup/path`. The UI ZIP backs up legacy PMS data only.
