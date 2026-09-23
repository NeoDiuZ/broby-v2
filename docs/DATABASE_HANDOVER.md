# Database handover — Railway PostgreSQL target

## Current state: TWO stores, not one

| Store | Location/config | Owns |
|---|---|---|
| PostgreSQL | `BROBY_SPINE_URL`; local PG 18.6 on loopback 55432 | Normalized v2 patient spine, events, concepts, observations, positioned sources, clinic memberships and projection checkpoints |
| SQLite | `BROBY_DATA_DIR/broby.sqlite3`, default `api/data` | Existing PMS records/revisions, audits, idempotency, appointments, invoices/payments, stock, jobs, sessions, grants and capture metadata |
| Files | `BROBY_DATA_DIR` and browser IndexedDB | Uploaded files/recordings and browser-only unsent drafts/chunks |

Key code: `api/db.py`, `api/actions.py`, `api/auth.py`, `api/jobs.py`, `api/main.py`; normalized models/routes/ingest/projection under `api/spine/`; frozen migration `api/alembic/versions/0001_patient_spine.py`.

The SQLite change sequence/triggers in `spine/projection.py` project legacy patient facts into PostgreSQL before v2 reads. A per-clinic PostgreSQL transaction advisory lock and checkpoint serialize projection. Native v2 events stay in PostgreSQL. The bridge is not two-way synchronization: legacy reporting, assistant, owner-sharing and document source selectors do not automatically see all native v2 events. PostgreSQL-only patients have a record screen, but legacy PMS actions are restricted for them.

## Moving the existing spine to a NEW Railway database

1. Provision a PostgreSQL service in the new v2 Railway project, never the v1 service. Check the provider version against migrations/tests; local version is 18.6, but portability has not yet been validated on Railway.
2. Store the database URL only in Railway backend environment variables. SQLAlchemy uses psycopg 3: use the `postgresql+psycopg://` driver scheme, preserving credentials/host/options. Do not expose it via NEXT_PUBLIC variables or commit it. Use the provider's internal networking where appropriate and validate TLS requirements for any external connection.
3. From the API directory run `python -m spine.migrate` once as a controlled migration step, before serving traffic. Do not run the Mac-specific local PostgreSQL installer/start script in Railway.
4. For staging only, seed synthetic history with `python -m spine.seed`. Confirm the accompanying SQLite synthetic seed/projection is initialized; consult seed.py. Native v2 reads still depend on the legacy bridge at this stage.
5. Use a SEPARATE disposable test database via BROBY_TEST_SPINE_URL. Tests create/drop their own schemas and need suitable privileges. Never point destructive test tooling at a customer database.
6. Verify directory/timeline/observations/source lookups, repeated/concurrent lab delivery and clinic isolation. Rehearse backup restore into another empty database.

Changing BROBY_SPINE_URL moves ONLY the PostgreSQL portion. It does not migrate SQLite, files, jobs, auth, or browser drafts.

## Complete SQLite migration: required engineering

- Inventory every SQLite table, record kind, trigger and read/write call site, including authentication/grants/jobs/audits and projection.
- Add versioned PostgreSQL migrations for the remaining data. Preserve opaque IDs, clinic ownership, timestamps, record versions, source links and financial/stock history. Do not invent dates or clinical measurements.
- Replace SQLite-specific SQL, placeholders, JSON packing, transaction and uniqueness semantics. Preserve optimistic edits, clinic-scoped idempotency, exactly-once logical actions, integer-cent money and atomic stock checks.
- Migrate a synthetic fixture first and reconcile counts, links, sums, stock and histories. Add dual-actor concurrency and rollback tests before switching consumers.
- Move all writers AND readers to PostgreSQL, including legacy assistant, PDFs, reports and approved owner views. Remove the projection triggers/checkpoints only when no reader needs the bridge; leave a documented rollback route.
- Separate jobs into a durable worker with claims, retries and idempotency. `main.py` currently starts an in-process thread; scaling API instances requires redesign, not simply increasing replicas.

For a temporary single-instance staging build, SQLite/files could live on an isolated persistent Railway volume. This is a transitional option, not the desired all-PostgreSQL completion. No such volume or cloud service has been created.

## Files, identity and backups

PostgreSQL is not the file store. Choose private object storage or a deliberately managed Railway volume for recordings/uploads; implement authorized access and retention. Supabase Auth/Storage are not part of the new plan. Existing demo headers and optional local password sessions are not production-ready identity; complete authentication and verified clinic authorization separately.

The UI ZIP is a LEGACY PMS backup: it does NOT contain PostgreSQL. `scripts/backup-local.py` coordinates a local PostgreSQL dump plus SQLite/files with the API stopped. It is not a scheduled Railway backup system. A production plan must cover database, files, consistent restore points, retention and restore drills; browser-only unsent drafts are not in server backups.

No live v1 customer data is required for staging. If production migration is approved later, first map/reconcile a secured export in a separate environment, perform rehearsal and rollback planning, then authorize cutover separately.
