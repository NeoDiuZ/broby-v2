# Deployment plan — Railway only

Decision: use GitHub for source and a NEW Railway project for the combined frontend, FastAPI backend and NEW Railway PostgreSQL. Supabase and Sites are no longer targets. Nothing in the existing v1 Railway project, domains, database, Redis or volumes should change. This document is a plan; this checkout is not cloud-deployed or production-ready.

## Service layout

- Frontend: `web/` Next.js serves website `/`, app `/app`, owner `/owner`. Start on `0.0.0.0:$PORT`; the current local script binds loopback 3100 and must not be used unchanged in Railway.
- API: install `api/requirements.txt`, run Alembic migration once, serve FastAPI with uvicorn on `0.0.0.0:$PORT` from `api/`. Local script binds loopback 8100.
- PostgreSQL: a new v2 service. Set backend BROBY_SPINE_URL with the psycopg SQLAlchemy scheme. Read DATABASE_HANDOVER.md before connecting: the app still has SQLite dependencies.
- Worker/storage: finish durable queue/worker and file persistence. During any transitional single-instance demo SQLite/files require a persistent volume; never assume ephemeral container files survive deploys.
- One public v2 frontend URL with same-origin `/api/*` forwarding to the API. `web/next.config.ts` uses BROBY_API_ORIGIN at BUILD time and defaults to localhost:8100. Set a backend URL reachable by the deployed frontend and verify Railway networking at runtime. Do not point it to v1. Use a new Railway-generated domain first; no production DNS changes.

## Required changes before a shared deployment

1. Complete or explicitly agree the storage transition described in DATABASE_HANDOVER.md.
2. Replace demo identity headers with verified sessions and clinic membership authorization. Add the actual staging origin to a configured allowlist: `api/main.py` currently accepts only local origins (and the legacy extension prefix); remote browser mutations will otherwise be rejected. Review cookies, CSRF, read permissions and owner-grant boundaries.
3. Implement durable worker ownership/retries; currently the API lifespan starts a background thread.
4. Add reproducible build/start configuration and CI, provision isolated secrets in Railway, seed only synthetic data. The local setup has no validated Railway Dockerfile/railway.json deployment yet.
5. Test the public website, app, owner links, uploads/audio/PDFs, two-user conflicts, persistence after redeploy, access rejection and full restore. Health alone is not proof that both stores and all workflows work.

## Frontend preservation

`web/` is the active combined frontend. `website/` is a retained design reference, not a separate running service. `web/public/live/index.html` is the preserved homepage. Marketing pages load `web/public/marketing.css`, the prior website's compiled Tailwind 3 CSS; clinic pages use Tailwind 4. Regenerate that marketing asset if changing its source styles. Old root clinic hashes redirect to `/app`.

Keep credentials, local database files, recordings, `.local`, dependencies and build output out of Git. Do not paste secret values into issues or PRs. Railway should deploy only an explicitly reviewed v2 branch in the separate project. Creating this repository/PR does not authorize a production cutover.
