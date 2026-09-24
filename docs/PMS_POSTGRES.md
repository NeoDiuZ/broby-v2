# PostgreSQL PMS and guarded cutover

The PMS, accounts, sessions, owner grants, audit history, idempotency receipts,
assistant history and job/provider queues can now use PostgreSQL. They occupy a
dedicated `broby_pms` schema in the existing Broby New database; the normalized
clinical tables retain their existing schema. No V1 store or provider credentials
are used by this migration. SQLite remains supported for local development.

This consolidates the database service. It does not rename the generic PMS record
table into a fully normalized clinical model: existing records still project into
the typed clinical tables. Native clinical ingest retains its existing shared
action contract and deduplication. Files still require the backend volume, so the
deployment remains one API process/replica with its existing four worker loops.

## Transaction behavior

Values remain separately bound SQL parameters. SQLite-specific upserts, JSON
lookups, schema inspection and triggers have explicit PostgreSQL equivalents.
Record-history triggers and durable projection sequence triggers are installed in
the selected store. Floating-point lease timestamps use double precision.

PostgreSQL write transactions take a database advisory lock, preserving the
application's existing single-writer invariant while stock, invoice, idempotency,
permissions and audit changes commit together. This is not a throughput or
multi-replica claim. Ordinary reads see newly committed permission changes;
financial reports, transfer previews and projections request a consistent
snapshot explicitly. Clinic archives serialize with the mutation layer while
collecting record/history/file receipts. Their export is still not a replacement
for a complete service backup.

## Activation

Keep one backend instance and its existing file volume. Deploy the tested code
and use these backend settings at the stopped-service cutover:

```
BROBY_PMS_STORE=postgres
BROBY_PMS_SCHEMA=broby_pms
BROBY_PMS_MIGRATE=1
```

The PMS uses `BROBY_SPINE_URL` unless `BROBY_PMS_URL` is explicitly supplied. The
intended Railway deployment uses the same PostgreSQL database for both schemas.
The explicit migration flag is required when the old SQLite file exists. Startup
initializes and migrates before seeding, serving requests or starting workers.

The migration:

1. Locks the old SQLite database and refuses unknown tables/columns or a populated
   PostgreSQL destination. It never merges two live PMS stores.
2. Writes a private, durable local cutover marker and a complete SQLite snapshot
   under `/data/pms-cutover/<migration-id>/legacy.sqlite3`.
3. Adds database-level write-rejection triggers to the legacy tables. An obsolete
   open connection cannot resume writing after the copy. The backup predates this
   fence and retains the original data.
4. Copies every table in one PostgreSQL transaction, then compares ordered row
   counts and SHA-256 fingerprints of all values. Credentials, grants, claims,
   original record versions and histories are preserved without resetting them.
5. Restores projection triggers/sequence position and commits a migration receipt
   in `broby_pms.pms_migration`. A final local marker identifies that exact store.

Copy/verification failure rolls back PostgreSQL changes and fails startup. The
legacy fence remains, preventing accidental fallback. Correcting the cause and
restarting retries the same source/backup, rather than appending a second copy.
Changed source data, a different destination or a mismatched migration receipt
are rejected. A crash after the PostgreSQL commit only needs to finalize its
matching local marker. Later restarts never recopy stale SQLite data.

`/api/ready` returns `pms_store: postgres` and stores `postgresql, files` after
activation. Administrator operations status also names the current PMS store.
The marker/backup contain no new credentials; the backup itself contains existing
credentials/grants and is owner-readable only. Keep it private.

## Recovery boundary

Do not roll back to an old application image or merely remove the PostgreSQL
variable after cutover. That cannot roll back subsequent PostgreSQL writes.
Keep the database dump and file volume together. Restore to an isolated target,
validate records, histories, auth, queues and file bytes, then review the target
and local cutover marker before activating it. A marker mismatch deliberately
stops startup; never delete it just to suppress a failed check.

The local coordinated backup utility dumps the whole PostgreSQL database (both
schemas in one database snapshot) and copies the stopped API's data directory.
It refuses separately hosted PMS/clinical databases. Its version-2 manifest
describes the PostgreSQL dump, data directory and active PMS mode. The legacy
clinic-ZIP restore tool remains explicitly SQLite-only and rejects archives with
native clinical facts.

## Acceptance evidence

- The same 582 backend cases pass in SQLite mode and PostgreSQL PMS mode; the
  PostgreSQL run creates a disposable schema for each test. CI covers both modes.
- Dedicated database cases cover concurrent duplicate payment requests, version
  history, rollback of new files, JSON matching and precise lease timestamps.
- Nine migration cases cover all-table equality, preserved auth/session/claim
  data, explicit activation, failed-copy rollback/retry, unknown schemas, changed
  sources, database-level rejection of old writers and crash recovery.
- The isolated production-browser clinic migrated 35 PMS tables and 358 rows,
  including 125 records. Existing credentials, owner access, closed conversations,
  handovers and all 66 original seed records remained intact. New PostgreSQL
  conversation writes passed 19 API checks; ten persistence checks passed.
- A stopped-clinic backup of both PostgreSQL schemas was restored to a disposable
  local database. All 48 tables and 559 rows matched, with three copied files
  matching by hash. The disposable database was removed after verification.

Exact hosted revision, cutover and post-deployment verification are recorded in
the release receipt after execution. This local restore is not a Railway disaster
recovery drill, and three fixture files do not certify a large binary archive.
Independent workers, external file storage, clinic-scale load acceptance and
external operational alerts remain separate work.
