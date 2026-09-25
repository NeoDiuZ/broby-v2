# Background service health

Administrators can open Settings → Sync & jobs → Background service health.
`GET /api/operations/health` returns current worker progress and selected-clinic
queue counts without source text, job payloads/results, provider credentials,
phone numbers or raw exception messages. It requires an active administrator and
uses the normal authenticated clinic-membership boundary. Responses are not cached.

The four existing workers (documents/speech, scheduled preparation, Stripe test
reconciliation and the restricted WhatsApp trial) now share a supervised loop.
Each runs one cycle at a time. A loop failure records a sanitized warning and
retries with increasing delay capped at 60 seconds. Per-task authorization,
leases, provider idempotency, retry limits and uncertain-send protection remain
in force. A failed task is distinct from failure of the worker's polling or
persistence. Failed document jobs use the existing audited `job.retry` action;
conflicting documents must be regenerated from current sources.

Embedded mode reports progress from the current process. External mode reports
the current registered worker's persisted snapshot and heartbeat; registering a
replacement clears the old snapshot before any polling starts. Failure counts,
last failure and recovery are stored in `worker_history` and survive restarts.
Failure to persist this history is itself visible. Each runtime owns its stop
event so starting a new lifespan cannot resume an older stopped loop.

A worker that exits is shown as stopped. More than five minutes without cycle
progress is shown as overdue. Long work can legitimately exceed this interval:
operators must inspect the task and logs. The supervisor does not kill or fork a
possibly running provider call. Provider-disabled workers are labelled not
configured, rather than claiming successful delivery. Their configuration state
is deployment-wide; task counts are scoped to the selected clinic.

Document and Stripe queues distinguish active leases, scheduled retry waits,
ready work, work unclaimed for at least five minutes and terminal states. Counts
cover the entire clinic queue; at most 20 recent issues per queue are listed.
WhatsApp trial uncertainty/failure/blocked states remain visible without exposing
recipient data. Old failures remain in totals until resolved through their
existing workflows; this is not a recent-only incident count. The page refreshes
every 15 seconds while open and labels stale results after a read failure.

## Separate API and worker processes

`BROBY_WORKER_MODE=embedded` is the default and preserves the existing single
API deployment. For **one host with the same persistent POSIX file volume**,
`BROBY_WORKER_MODE=external` starts no polling threads in the API. After the API
has prepared the database, a separate `python worker.py` process runs the four
workers. Both processes must use identical PMS/spine database settings and the
same absolute `BROBY_DATA_DIR` mount path. The worker does not migrate databases,
seed clinics or provision accounts.

| Process | Mode and command | Responsibilities |
|---|---|---|
| Existing API | mode omitted or `embedded`; `python serve.py` | API plus one guarded worker runtime |
| API only | `BROBY_WORKER_MODE=external`; `python serve.py` | API, schema initialization, authenticated health/readbacks |
| Separate worker | `BROBY_WORKER_MODE=external`; `python worker.py` | Queue polling, scheduled preparation, provider reconciliation |
| Worker health probe | `BROBY_WORKER_MODE=external`; `python worker.py --check` | Exit 0 only for fresh, matching, non-attention worker progress |

The hosted image also accepts `BROBY_PROCESS_ROLE=worker` to run the worker
entrypoint without migrations. Leave its default `api` and embedded mode on the
current Railway deployment. These settings alone do **not** make an independent
Railway service safe: the worker needs the actual backend upload/audio volume.

The API binds a persistent, opaque volume identity in `worker_runtime` before a
separate worker may consume tasks. A different empty volume is rejected. This
identity is a configuration guard, not proof of a distributed shared filesystem:
do not copy its marker to another volume to bypass the check. Files still contain
absolute paths and must be available at the same paths in both processes.

A POSIX file lock protects the volume in both modes. PostgreSQL additionally
holds a dedicated session advisory lock for the PMS schema. A competing runtime
fails before polling. Locks release when a process dies; they do not require a
manual stale-lock deletion. The file lock remains held while a stopped runtime
still has an unfinished provider call, even if database connectivity is lost.
The heartbeat publishes sanitized worker state every five seconds. External
health marks a missing, stopped, mismatched or more-than-30-second-old process
as needing attention. A fresh process heartbeat does not erase an overdue worker
cycle. Heartbeat failure stops further polling and the standalone process exits
after a bounded shutdown; a process manager must restart it.

Document jobs retain their existing 90-second claims and 20-second renewals. A
replacement waits for a lost job's lease to expire, then claims with a new token;
the old token cannot commit. Completed speech windows remain checkpoints. A
provider request interrupted before its checkpoint may be repeated, so this is
not an exactly-once provider-call guarantee. Payment idempotency and WhatsApp's
uncertain-send review remain unchanged. SIGTERM/SIGINT allow up to 30 seconds for
the standalone process to finish; remaining daemon work ends with the process.

For switching modes or restoring data, stop both processes first, preserve both
stores and the complete file volume, prepare schema through the API, then start
exactly one worker. Coordinated local backup now acquires the worker ownership
locks for the whole snapshot, so stopping only the API cannot silently back up
while an external worker is still writing. The API must remain stopped too.

## Verification and boundaries

The backend suite covers sanitized failure/recovery, durable history across a new
supervisor, disabled providers, bounded backoff, interruptible shutdown, dead and
overdue workers, storage failures, queue classification/limits, clinic/role
isolation, guarded retry and real lifespan startup/shutdown. Subprocess tests run
a real API and worker against synthetic queues, reject a competing worker, kill
the claimant with SIGKILL, let a shortened test lease expire naturally, and
recover through the normal worker entrypoint with one final document commit and
unchanged source receipts. These run in SQLite and PostgreSQL PMS modes. Tests
also cover stale/mismatched heartbeats, stopping on heartbeat failure, retaining
ownership during a blocked call, and refusing backup with a live external worker.
Isolated production browser acceptance exercises a controlled worker failure plus a failed document,
then reviews/retries it and verifies the exact assembled source and receipt.

This is in-app operational visibility and bounded loop recovery. It does not add
external/on-call alerts, acknowledge incidents, verify backup recovery, certify
message delivery or settlement, kill hung provider calls, or deploy independent
cloud worker services. `/api/ready` continues to check storage readiness separately.
Shared object storage, multiple hosts/replicas, file-volume outage recovery and a
cloud restore drill remain unverified. The single-backend Railway deployment
constraint remains. Hosted revision, real-cycle acceptance and remaining
limitations are recorded in the private release report.
