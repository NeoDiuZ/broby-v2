# Hard workflow release: verification guide

Use synthetic patients in Broby New. Existing WhatsApp and V1 are separate and unchanged. No payment processor, messaging provider or physical analyser is connected by this release.

## Operator walkthrough

1. Settings → Integrations → Integration rehearsal: receive a synthetic lab report. Open the patient timeline; verify the value, supplied range and original receipt. Text and yes/no results are also accepted by the API. Ask Broby for that patient's observations.
2. Reports → Saved record views: save an observation query for the patient, then refresh it. The query and its results survive sign-in on another browser; the server reruns the query on refresh.
3. Patient timeline: approve a native result for the owner vault. Open a newly created owner link and verify it appears. Remove approval and refresh the owner page; it disappears. Only approved record content is shared.
4. Inventory: create an item, record purchase orders and deliveries with lots and expiry dates, then dispense. Eligible stock is consumed by earliest expiry. Expired stock cannot satisfy dispensing. Multiple-lot stocktakes require a selected lot and reason.
5. Billing: create an invoice with an explicit discount and tax percentage. Rates default to zero; the system does not decide the clinic's tax policy. Integration rehearsal can simulate successful payments/refunds without changing real invoice balances or moving money.
6. Settings → Clinic: configure rooms and staff availability. Book inside/outside the window and try a room collision. Organization masters can create new clinics and apply inherited restrictions, including to ordinary clinic administrators.
7. Settings → Team & access: create a staff member and a single-use invitation. The staff member uses `/enroll`, creates an account or proves their existing credentials, and optionally enables an authenticator. Save the one-use recovery codes. Password changes invalidate all sessions; deactivating membership blocks that clinic.
8. Settings → Observation catalog: propose a dictionary entry or request an AI proposal. An administrator explicitly accepts/rejects it. Codes and synonyms cannot redefine an existing meaning or unit.
9. Owner page → Share with a registered clinic: give explicit consent. Receiving clinic staff find the request under Settings → Data & migration. Revocation/expiry before acceptance prevents import. Acceptance creates an independent copy of approved events and files; it is not deleted by later revocation. No automatic name-based patient merge is performed.
10. Settings → Data & migration: preview a synthetic clinical export with source IDs, then apply its digest. Replaying identical data creates no duplicate records; changed content using the same source identity is rejected.

## Repeatable checks

From the repository root:

```
.venv/bin/python -m pytest api/tests -q
node --test web/tests/*.test.cjs
node web/node_modules/typescript/bin/tsc --noEmit -p web
.venv/bin/python scripts/smoke-advanced.py http://127.0.0.1:3100 --state .local/advanced-local.json
.venv/bin/python scripts/smoke-advanced.py http://127.0.0.1:3100 --state .local/advanced-local.json --verify-only
```

Hosted checks use the live website URL and `--credentials` pointing to an ignored, private JSON file. The script prints check labels, never credentials. It revokes its owner grants and signed-callback key in cleanup. Test records remain labelled SYNTHETIC for inspection.

The signed synthetic callback contract is POST `/api/integrations/test/events`. An administrator provisions a clinic-bound key through POST `/api/integrations/test/key`; revoke with DELETE `/api/integrations/test/key/{id}`. Headers are `x-broby-key`, `x-broby-timestamp` (Unix seconds) and `x-broby-signature` (HMAC-SHA256 hex of `timestamp + '.' + raw request bytes`). The JSON contains `event_id`, `action` and `payload`. Only synthetic lab/payment/message actions are accepted. Five-minute freshness, exact event replay, changed-content rejection and current member permissions are enforced. Keys are never included in bootstrap or normal exports.

## What this does not prove

These tests do not establish real message delivery, card settlement, analyser compatibility, multilingual clinical accuracy, unattended emergency response or a live V1 migration. PostgreSQL holds native clinical events and receives a durable projection of legacy clinical records; transactional PMS/auth/jobs still use SQLite. This is not yet a single-database architecture or a horizontally scaled deployment. Offline cold launch, verified cross-device owner identity, a continuous 25-minute refinement pipeline, accounting-specific credit notes and a reconciled V1 financial/stock cutover remain unfinished. Original audio is preserved; context preferences do not constitute an approved clinical data-deletion policy.

MFA uses the time-based algorithm in [RFC 6238](https://www.rfc-editor.org/rfc/rfc6238), including a stored counter to reject reused authenticator codes; the tests include published SHA-1 vectors. Recovery codes are stored only as hashes and consumed transactionally.

## Restore rehearsal

With the local API stopped, `scripts/backup-local.py` captures both stores and files. `scripts/verify-backup.py BACKUP NEW_DIRECTORY` restores the PostgreSQL dump to a newly created disposable database, copies and validates the SQLite store, rewrites restored binary paths, checks attachment/audio hashes, and removes only its own temporary database. The restored file directory and a count-only verification report remain for inspection. The release rehearsal restored 109 SQLite records, 24 PostgreSQL events, 14 observations and two binary files from the pre-release 0002 backup. This proves the local coordinated snapshot can be restored; it is not a Railway disaster-recovery drill or a real V1 cutover.

Clinic JSON exports now include native clinical facts. The clinic ZIP includes a clinic-scoped PostgreSQL snapshot in `spine.json`, including original dedupe keys and typed columns. It excludes credentials and access grants. The legacy-only restore command refuses an archive containing native events instead of silently omitting them; full recovery uses the coordinated database-and-files procedure above.
