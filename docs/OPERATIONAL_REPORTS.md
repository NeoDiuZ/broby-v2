# Clinic operational report

Reports → Clinic overview loads a server-generated clinic snapshot for the
selected 7, 30 or 90 local calendar days. The CSV export generates a fresh
snapshot with the same definitions and includes the period, timezone and UTC
generation time on every row. Both endpoints require all read capabilities,
because they combine patient, clinical, scheduling, message and stock data.

The report counts the full persisted clinic record set, not the browser's
bootstrap cache or current page. Patient, owner and species totals are all time.
Consultations and messages use their creation timestamp in the clinic timezone;
appointments use the scheduled date; reminders use the due date. Current open
intakes, failed/conflicting jobs and stock are point-in-time counts. A message
status describes the stored outbox state and does not certify delivery.
Inventory records with invalid quantities or malformed legacy data are reported
separately and excluded from stock totals. Unusual legacy species/status values
remain visible as labelled counts instead of crashing the report. Service items
are excluded from stock. The report never
infers a tax position, bank settlement or a clinical outcome.

This is a clinic operations view alongside the existing clinical and financial
reports. General-ledger accounting, independent settlement reconciliation,
performance at a real clinic's data volume and hosted browser acceptance are
separate release work. The focused tests cover clinic isolation, local-day
boundaries, owner links, status counts, invalid stock, CSV parity and read
permissions; their passing result alone is not a launch certification.

A disposable local PostgreSQL benchmark with 21,000 synthetic records (10,000
patients, 5,000 appointments, 5,000 messages and 1,000 stock items) returned
the full report in 21, 20 and 20 ms across three reads. This tests the server
query path at that fixture size; it does not measure a concurrent clinic workload
or hosted latency.
