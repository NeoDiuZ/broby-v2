# Repeatable load and recovery acceptance

The rehearsal runs a real authenticated API process against its own local
PostgreSQL database. It creates synthetic patients, sources, original file/audio
bytes, a document job and concurrent mutations. Provider calls are disabled.
It never accepts a hosted target, stops an unrelated service, or modifies V1.

Run with the local PostgreSQL runtime available:

```
.venv/bin/python scripts/verify-reliability.py \
  --output .local/reliability-new-run --patients 1000 --requests 160 --concurrency 8
```

Choose a new output path for every run. The output contains private test data,
server logs, backup, restored files and a JSON result. The script deletes only
its own disposable databases and terminates only its own child process.

The manually dispatched `V2 synthetic scale reads` GitHub workflow runs the
same isolated script on a disposable PostgreSQL database. Its larger fixture
adds synthetic appointments, unsent message drafts and stock items, then checks
the exact saved appointment view and full operational report. The concurrent
HTTP mix covers bootstrap, paged patient search, patient timeline, worker
health, the report and the saved view; the result artifact records per-route
latency and response size. The manual workflow uses `--skip-restore` because
the separate 24 September run below already covered backup integrity. A scale
run does **not** certify hosted Railway capacity, a prolonged soak, external
provider delivery or a real clinic's records.

## Verified on 25 September 2026

The disposable GitHub Actions PostgreSQL run with 1,000 added patients and
48 authenticated reads across eight clients passed all 19 correctness,
concurrency and forced-process-loss checks, with zero HTTP errors. It removed
its disposable database. Operational-report sequential reads measured 31.6–33.5
ms; before the same report's owner-link counting fix, they measured 1,500–1,531
ms and SQL profiling assigned 1,492 ms to one JSON-expression owner join.

A separate diagnostic run found that saving an unrelated dashboard queued a
full clinical projection. That refresh took 3,248.5 ms at 1,000 patients and
delayed otherwise small patient search and timeline responses. PostgreSQL and
SQLite triggers now enqueue only record kinds the clinical projection consumes;
membership changes remain tracked. The rerun's steady projection checks took
2.9–3.3 ms sequentially. In its mixed concurrent read burst, patient search
p95 was 489.7 ms and timeline p95 was 432.5 ms. The first full projection of
the 1,000-patient fixture still took 5.386 seconds. The test does not establish
incremental projection for genuine clinical changes or a hosted capacity bound.

The larger disposable run added 5,000 patients, verified 21,337 records and
completed 400 authenticated reads across 16 clients with zero HTTP errors. All
19 correctness/recovery checks passed again; the database was removed. Five
sequential operational reports took 82.0–85.3 ms, and sequential patient search
and timeline reads took 35.2–38.1 ms and 19.7–22.4 ms respectively. Under the
mixed concurrent burst, however, full bootstrap returned up to 7.84 MB and
reached 8,361.4 ms p95; search, timeline and operational report reached 3,945.2,
3,952.4 and 4,671.7 ms p95. The first full clinical projection took 27.096
seconds. These are concrete scaling limits. Full bootstrap pagination and
incremental projection of clinical changes remain release work; passing without
HTTP errors is not a latency or hosted-capacity certification.

A follow-up 5,000-patient/16-client run on the same disposable workflow profiled
21,325 bootstrap records. The database read took 190.4 ms, JSON decoding 165.6
ms, native clinical reads 22.2 ms and direct JSON encoding 45.6 ms; the original
full HTTP read took 1,077.8–1,275.0 ms. Returning the already-JSON clinic data
without a second framework conversion reduced the three standalone HTTP reads
to 493.8–731.7 ms. Across an otherwise identical 96-request mixed burst,
bootstrap p95 changed from 9,195.6 to 4,173.7 ms and total elapsed time from
18.493 to 8.784 seconds. Both runs passed all 19 checks and removed their
databases. These are two disposable CI runners, not a controlled hosted latency
guarantee. The 7.84 MB uncompressed bootstrap and full projection after genuine
clinical changes remain. The frontend also stops six-second full refreshes in
hidden tabs and refreshes when they become visible again.

A later guarded projection path records the changed PMS record IDs and kinds.
When at most 100 queued changes are exclusively patient/owner edits, it updates
only those typed identities and owner links in dependency order. Unknown older
queue rows, membership changes, other clinical kinds and larger batches still
take the full rebuild. The change queue upgrades existing SQLite/PostgreSQL
tables without removing old rows. A disposable 1,000-patient run projected and
read back a real synthetic patient edit with its owner link in 25.5 ms; its
first full projection took 5.288 seconds. At 5,000 patients, the edited identity
read back in 246.8 ms while that run's first full projection took 20.044 seconds.
Both runs passed all 20 correctness/recovery checks, had zero HTTP errors and
removed their databases. This does not make first imports, nonidentity clinical
edits, bulk identity changes or hosted multi-clinic load incremental.

## Verified on 24 September 2026

- 1,000 added patients; 4,086 PMS records in the final fixture.
- 160 authenticated reads across bootstrap, paged patient search, patient timeline
  and worker diagnostics, with eight concurrent clients: zero HTTP errors.
- Sixteen concurrent stock mutations with the same version: one dispense, fifteen
  conflicts; stock changes once. Sixteen retries of one payment: one payment and
  an exact balance. Sixteen competing bookings: one reserved slot.
- A real worker claimed a document job. Its API process was killed before job
  execution. Restart retained the original password session and respected the
  unexpired claim. After the actual 90-second lease expired, the restarted worker
  completed the job automatically, preserving exact source text and one save.
- Original patient/owner records, original attachment and original audio bytes
  survived. No model or message-provider receipt is claimed by this test.
- Full format-3 backup and isolated restore matched **48 tables / 13,334 rows**,
  all three data files and both indexed binary receipts. A deliberately corrupted
  file was rejected before any restore database was allocated.

A page previously executed five summary queries per patient, in addition to its
page query. It now batches those summaries in four queries, so a 50-patient page
uses five queries overall. The same local workload measured patient-search p95
at 594.5 ms before and 175.8 ms after; these are local measurements, not Railway
latency guarantees. Other final p95 measurements: bootstrap 289.9 ms, timeline
178.3 ms, operations health 160.1 ms. The test covers a bounded concurrent burst,
not a prolonged soak or a capacity guarantee.

A second, larger local run used 3,000 added patients (12,086 PMS records), 16
concurrent clients and 320 reads with no HTTP errors. All concurrency guards and
the real 90-second crash/lease recovery passed again. Its exact restore matched
48 tables / 39,334 rows, three files and both indexed binary receipts. At this
load, p95 was 1,738.9 ms for full bootstrap, 776.5 ms for patient search, 773.5 ms
for timeline and 649.8 ms for worker health. The full bootstrap response reached
4.46 MB, so further pagination remains a concrete scaling task.

## Backup format repair

The backup writer had moved to format 2 while the verifier accepted only format
1. The verifier now accepts both historical formats and the new format 3. Format
3 adds a hash of the PostgreSQL dump, original complete-row fingerprints from the
same exported database snapshot used by `pg_dump`, and file sizes/hashes.
Verification restores into a new local database, compares all original table
values/counts and file bytes, validates every indexed attachment/audio receipt,
then drops that database. Historical backups lacking original table fingerprints
explicitly report that exact original snapshot values could not be certified.

The source API must be stopped. `BROBY_BACKUP_API_URL` selects the local API
health address when it runs on a port other than 8100. This avoids confusing the
isolated acceptance server with an unrelated development service. This is an
operator-controlled stopped-workspace backup, not an online coordinated backup.

Remaining operational work includes a Railway disaster-recovery drill, large
binary archives, long-running load/soak tests, full bootstrap pagination,
independent workers/object storage, external alerts and physical-device capture
acceptance. These tests do not certify those separate boundaries.
