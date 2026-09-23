# First-build acceptance and remaining work

Updated 23 September 2026. Scope: deterministic patient spine, exact v2 read contract, lab ingestion and three patient screens, with the broader existing web preview preserved. Mobile and the extension remain deferred.

## Implemented and verified

- Real PostgreSQL 18.6 running only on loopback port 55432; SQLAlchemy 2.0; frozen Alembic migration `0001` tested in fresh PostgreSQL schemas.
- Normalized patients, owners, owner-patient links, clinics, people, memberships, events (JSONB), observations, concepts and positioned sources. Date of birth is nullable; unknown dates are not inferred from old age labels.
- The three `/api/v2` read contracts, cursor paging, owner-name search, mixed timeline, concept filtering and original source resolution. Additive response fields include receipt IDs, inline observations and patient counts.
- Atomic lab ingestion without a consultation, clinic-wide dedupe across actors and concurrent requests, conflict detection for changed payloads, automatic missing-source and numerical range flags. Custom event types require no schema migration.
- Patient directory; timeline grouped by day with loading-more sentinel and explicit fallback button; inline results and provenance; chart with laboratory reference bands, actual sample timestamps and clickable/keyboard-accessible event points. Loading, empty and retryable error states are implemented.
- Central design tokens: specified fonts, 13px body, 9px mono labels, 140px sidebar, 6px active-item translation without highlight background, 6/8px controls/cards and subtle card shadow. Tailwind/PostCSS is configured without resetting the older screens.
- Repeatable four-month synthetic lab-history seed; a separate simulator POSTs a new result twice and verifies one event. No AI or provider calls in the first-build path.
- 51 tests pass: 39 prior workflow tests plus 12 PostgreSQL acceptance/integration tests. The five mandatory behaviours are covered, along with concurrency, clinic/source boundaries, memberships, cursor paging, invalid-input rollback and projection updates.
- Browser verified directory, timeline, lab flags, potassium reference band and point → event → document/page receipt. Production builds pass. PostgreSQL dump restored to a temporary database with all four seeded lab events present; temporary restore database removed after verification.

## Run / reproduce

```sh
./scripts/setup.sh
./scripts/start-spine.sh
(cd api && ../.venv/bin/python -m spine.seed)
./scripts/build.sh
./scripts/start-local.sh
# In another terminal while the API runs:
.venv/bin/python scripts/simulate-lab.py
.venv/bin/python -m pytest -q
```

Open Patients → Milo → Timeline / Observations. Simulation is local, synthetic and requires the default demo mode. For password mode use a signed-in session when exercising the API.

This Mac's PostgreSQL was built from official source and checksum-verified using `scripts/install-local-postgres.sh`. No Docker/Homebrew/system PostgreSQL existed. The runtime and data are ignored under `.local/`. For another deployment set `BROBY_SPINE_URL`, then run `(cd api && ../.venv/bin/python -m spine.migrate)`; do not silently reuse the local demo database. Tests create isolated schemas and need a PostgreSQL role allowed to create/drop its own test schemas; a separate `BROBY_TEST_SPINE_URL` is supported. Tests fail rather than skip when PostgreSQL is absent.

Patients that exist only in PostgreSQL also have a standalone record screen; preserved PMS actions are shown only for legacy-backed patients.

## Explicit remaining boundaries

1. **Transition, not a completed whole-product migration.** Existing PMS data still writes to SQLite; a durable change sequence projects relevant records into PostgreSQL before v2 reads. Native v2 lab events currently appear in the new timeline/chart, but older AI chat, owner sharing, reporting and document-generation source pickers do not yet consume them. Move these readers/writers to the normalized spine before claiming one unified product. Historical SQLite IDs remain opaque strings; there has been no production identity reconciliation.
2. **Visual parity cannot be fully signed off.** `~/broby-v2-mockups` was not present. Implemented the document's numeric tokens and layout behaviours, but screens 01/02 still need side-by-side comparison with those files. Qualitative legacy observations remain available as timeline text; the new chart is deliberately numeric.
3. **Real lab integration remains external.** The deterministic incoming endpoint and simulator work. Actual analyser/vendor authentication, payload mapping, document acquisition and delivery contracts still need vendor access. A source receipt may include inline report text; external source IDs without an attached local binary display their provenance, not an invented/downloaded document.
4. **No PR published.** The API contract and implementation are versioned in the separate local repository on branch `codex/v2-patient-spine`. A destination repository/branch and authenticated GitHub access are needed to publish the PR. The first-build contract was written before this implementation; earlier preview work predates it.
5. **Production work remains.** Full source completeness audits, large-dataset/load tests, deployment-grade access control and ingest service credentials, backup retention/restore drills, security review and actual v1 migration. This build is not an internet-facing clinic deployment.

## Backups and shutdown

The UI's clinic ZIP is now explicitly labeled **legacy PMS backup**; it does not include PostgreSQL. Stop the API, then run `.venv/bin/python scripts/backup-local.py /new/backup/path` to capture the PostgreSQL dump plus legacy SQLite data/files. Whole-workspace backups contain local auth/grants; protect them. Restore PostgreSQL with `pg_restore` into a newly created empty database and restore the legacy directory into a new path. Configure both paths together; never mix unrelated snapshots. Environment/provider secrets and unsent browser drafts are not included.

PostgreSQL is an independent local process. Stop it after stopping the API with `.local/postgres/bin/pg_ctl -D "$PWD/.local/pgdata" stop`. `start-local.sh` starts it again when the bundled runtime exists. The scripts do not deploy, send messages or connect to production.
