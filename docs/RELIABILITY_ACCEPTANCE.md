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
