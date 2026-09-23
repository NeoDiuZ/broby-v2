# Broby V2 backend setup and Railway deployment

Updated 23 September 2026. The implemented handover workflows are running in an isolated **Broby New** project under **cxlabyky's Projects**. This is an authenticated, synthetic-data staging deployment. Railway's environment is named `production`; that name does not mean the unfinished whole product is approved for customer production use.

- Website: https://frontend-production-1283.up.railway.app
- Clinic: https://frontend-production-1283.up.railway.app/app
- Railway: https://railway.com/project/ca389ebd-0186-4b7e-baec-8ddacdfc406b
- Repository: https://github.com/NeoDiuZ/broby-v2/tree/main
- Deploy branch: `main`. Merge reviewed changes into `main` to trigger Railway deployment for both application services. The original setup was developed on `codex/railway-setup`, based on `codex/v2-handover`.

The local initial account details are in `.local/hosted-access.json` (owner-readable, ignored by Git). Username: `kaushik`, linked to the synthetic East Coast administrator. That demo membership is displayed as Daniel Lim. Provider keys are held only in Railway. Do not put the access file or provider values in issues, PRs, screenshots, or Git.

## Services and routing

| Service | Source | Runtime and storage |
|---|---|---|
| Frontend | `/web`, `web/Dockerfile` | Next.js standalone, port 3000; public HTTPS website, clinic and owner pages |
| Backend | `/api`, `api/Dockerfile` | FastAPI, port 8000 on IPv4 and IPv6; private network only; one process and replica |
| Postgres | Railway PostgreSQL 18 SSL image | New database and persistent volume; private network only |

All three services run in Singapore (`asia-southeast1-eqsg3a`). The backend's `/data` volume stores SQLite PMS data, account/session records, durable job rows, audio chunks and uploads. PostgreSQL stores the normalized patient spine. Preserve both volumes. No V1 database, volume, DNS, deployment source, or running service was changed.

The browser uses one origin. Next.js forwards `/api/*` to `http://backend.railway.internal:8000/api/*`; the backend is not publicly exposed. `BROBY_API_ORIGIN` is a frontend **build-time** variable, so changing it requires rebuilding. The frontend Dockerfile explicitly accepts that build argument.

Railway service configuration uses root directories and Dockerfile detection in the dashboard. New services no longer accept `railway.json` Config as Code; do not add obsolete configuration files. The backend first validates hosted settings, applies Alembic migrations, idempotently seeds the synthetic clinic, then starts one API process. Both services use `/api/ready` as their deployment healthcheck (180 seconds). This checks PostgreSQL schema access, SQLite access, and writable file storage. `/api/health` is only liveness.

## Backend variables

| Variable | Current purpose |
|---|---|
| `BROBY_ENVIRONMENT=staging` | Enables hosted validation and disables public API documentation |
| `BROBY_AUTH_MODE=password` | Requires a session and verified clinic membership, ignoring demo actor headers |
| `BROBY_ALLOWED_ORIGINS` | Exact HTTPS frontend origin |
| `BROBY_DATA_DIR=/data` | Persistent backend volume |
| `BROBY_SPINE_URL=${{Postgres.DATABASE_URL}}` | New private PostgreSQL connection, normalized to psycopg |
| `BROBY_SEED_DEMO=1` | Repeatable synthetic seed; never imports customer records |
| `BROBY_ADMIN_USERNAME`, `BROBY_ADMIN_PASSWORD` | First-boot provisioning only; changing the variable does not reset an existing password |
| `BROBY_ENABLE_AI=1` | Enables configured providers |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Authorized V1 key, model `claude-sonnet-4-6` |
| `DEEPGRAM_API_KEY`, `DEEPGRAM_MODEL` | Authorized V1 key, model `nova-3` |
| `PORT=8000` | Backend listener |

Only the two provider keys required by this code were copied. V1 database, Redis, JWT, storage, RunPod, OpenAI and messaging keys were not needed. Shared provider keys share existing provider billing/quota. Both copied values were verified to match V1 without displaying them, and both providers completed real requests with synthetic inputs.

Staff sessions and saved owner cookies use Secure, HttpOnly and SameSite=Strict in hosted mode. Clinic reads and writes require membership. Foreign browser origins and cross-site mutations are rejected. Owner links remain revocable capabilities exposing approved content only. Staff invitations, password reset and MFA remain separate unfinished product work.

## Local development

From the repository root:

```sh
./scripts/setup.sh
./scripts/install-local-postgres.sh  # only if the bundled local runtime is absent
./scripts/start-spine.sh
(cd api && ../.venv/bin/python -m spine.seed)
./scripts/build.sh
./scripts/start-local.sh
```

Open `http://127.0.0.1:3100/app`. The API runs on `127.0.0.1:8100`, PostgreSQL on `127.0.0.1:55432`. Local defaults use demo identity and keep provider calls disabled. `.env` and `.local` are ignored by Git. Do not replace the local database URL with V1's connection string. Paths containing spaces are supported.

```sh
.venv/bin/python -m pytest -q
node web/node_modules/typescript/bin/tsc --project web/tsconfig.json --noEmit
./scripts/build.sh
```

CI runs the backend suite against disposable PostgreSQL 18, builds and starts the API container over IPv4, and typechecks/builds the active frontend. `website/` is a preserved reference, not a second deployed frontend.

## Verification performed

- 58 backend tests pass, including real PostgreSQL acceptance tests and hosted login, cookie, origin, clinic isolation and readiness regressions.
- TypeScript and production frontend build pass; GitHub CI also passed.
- 33 live same-origin workflow checks pass: website routes, readiness, anonymous/forged/cross-clinic rejection, login/logout, patient projection, action/lab deduplication, lab flags/charts/source receipts, uploads, consultation/invoice PDFs, owner visibility/intake/revocation, live Anthropic excerpts and live Deepgram transcription through the job queue.
- 17 live checks pass after backend redeployment, including SQLite patient, PostgreSQL lab, uploaded bytes and completed-job persistence.
- Chrome: signed-in clinic, patient directory, Milo timeline, observations, chart-to-event navigation and original source receipt.
- Verification records are visibly named `SYNTHETIC Deployment Test ...`; their invoice is voided. No messages, real payments or customer records were sent.

Repeat only against an isolated demo deployment. The first command creates synthetic records and optionally makes provider requests; the second verifies them after a redeploy:

```sh
.venv/bin/python scripts/smoke-hosted.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/hosted-smoke-state.json \
  --audio .local/synthetic-speech.wav
.venv/bin/python scripts/smoke-hosted.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/hosted-smoke-state.json --verify-only
```

## Storage, backups and release boundaries

Daily Railway volume backups are enabled for both stores, with six-day retention. Initial snapshots completed on 23 September 2026: backend at 18:08 SGT (798 MB), PostgreSQL at 18:14 SGT (862 MB). PostgreSQL point-in-time recovery is not enabled. Scheduled snapshots are independent and are not synchronized between the two stores.

One API process owns the in-process worker. Jobs persist in SQLite and running jobs are requeued at startup, but claims/retries are not designed for multiple workers. Do not increase replicas or worker count until the SQLite migration and independent worker design are complete. The mounted volume causes a short redeployment interruption.

Back up **both** PostgreSQL and the backend volume. The UI ZIP exports only legacy PMS data and files, not the PostgreSQL spine. Volume snapshots are separate recovery points; a consistent two-store restore requires stopping writes, choosing matching recovery points, and checking IDs, receipts, counts and job state. The local `scripts/backup-local.py` creates a coordinated backup only with the local API stopped. Redeploy persistence was verified; a complete cloud backup restoration drill remains outstanding.

Before real customer use: finish the two-store reader/writer migration, independent worker/retries, staff account lifecycle/MFA, retention/restore operations and provider language/device evaluation. WhatsApp delivery, payment gateways, external laboratory feeds, native mobile and other features marked unfinished in `FEATURE_STATUS.md` are not implemented by this deployment work. No production domain cutover or V1 customer migration has been performed.
