# Broby v2 — development handover

The patient-record foundation now uses **FastAPI, SQLAlchemy 2.0, Alembic and PostgreSQL**, with Next.js/React/TypeScript and Tailwind on the frontend. The original production checkout is untouched. An isolated, authenticated synthetic-data deployment is now running in Railway **Broby New**. It is not a replacement for V1.

The release source and Railway deployment branch are `main`. The handover and hosting changes are tracked in [PR #1](https://github.com/NeoDiuZ/broby-v2/pull/1) and [PR #2](https://github.com/NeoDiuZ/broby-v2/pull/2). Clone with `git clone https://github.com/NeoDiuZ/broby-v2.git`.

## Open

- [Live website](https://frontend-production-1283.up.railway.app) · [Live clinic](https://frontend-production-1283.up.railway.app/app)
- [Workspace](http://127.0.0.1:3100/app) — Patients → Milo → Timeline / Observations
- [Preserved website](http://127.0.0.1:3100)
- [API reference](http://127.0.0.1:8100/docs)

Website and app now share port **3100**. `/` serves the preserved website, `/app` the clinic workspace, `/owner` the owner portal, and `/api/*` proxies the internal API on 8100. Port 3101 is no longer needed. `web/` is the active combined frontend; `website/` is retained as the original reference.

Start with [HANDOVER.md](HANDOVER.md), then [Railway deployment plan](docs/DEPLOYMENT.md) and [database migration plan](docs/DATABASE_HANDOVER.md). The target is a **new, isolated Railway project with Railway PostgreSQL**. Supabase and Sites are no longer deployment targets. The deployed branch is `main`. See [backend setup and verification](docs/DEPLOYMENT.md) for the live URL, service configuration, test evidence, and remaining release boundaries.

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

The [API contract](docs/V2_CONTRACT.md) is explicit and the first schema is a frozen Alembic migration. **58 tests pass**, including real PostgreSQL acceptance tests for all five required first-build behaviours. The unified frontend production build passes. The browser flow and PostgreSQL backup restoration were checked.

## Important transition boundary

Scheduling, billing, capture, accounts and queues now use a separate PostgreSQL PMS schema in the hosted deployment; SQLite remains available for local development. PMS records project into the normalized clinical spine in the same database. Native clinical facts are consumed by the later assistant, owner-sharing and reporting releases. Files still use one backend volume, and the whole Google Doc vision is not complete. See [the current requirements audit](docs/FEATURE_STATUS.md) and [guarded database migration](docs/PMS_POSTGRES.md) for verification and remaining work. Exact mockup parity remains unverified because the referenced mockup directory was unavailable. Mobile and the extension are deferred.

See [acceptance and remaining work](docs/FIRST_BUILD.md), [full-product status](docs/FEATURE_STATUS.md), and the [earlier workflow guide](docs/PREVIEW_GUIDE.md). For backups of both stores, stop the API and run `.venv/bin/python scripts/backup-local.py /new/backup/path`. The UI ZIP backs up legacy PMS data only.
