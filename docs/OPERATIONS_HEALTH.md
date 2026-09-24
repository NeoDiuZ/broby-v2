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

Current progress belongs to this process; a recent heartbeat from an earlier
process cannot certify a new worker. Failure counts, last failure and recovery
are stored in `worker_history` and survive restarts. Failure to persist this
history is itself visible. Each application lifespan owns its stop event so
starting a new lifespan cannot resume an older stopped loop.

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

## Verification and boundaries

The backend suite covers sanitized failure/recovery, durable history across a new
supervisor, disabled providers, bounded backoff, interruptible shutdown, dead and
overdue workers, storage failures, queue classification/limits, clinic/role
isolation, guarded retry and real lifespan startup/shutdown. Isolated production
browser acceptance exercises a controlled worker failure plus a failed document,
then reviews/retries it and verifies the exact assembled source and receipt.

This is in-app operational visibility and bounded loop recovery. It does not add
external/on-call alerts, acknowledge incidents, verify backup recovery, certify
message delivery or settlement, kill hung provider calls, or introduce independent
worker services. `/api/ready` continues to check storage readiness separately.
The single-backend deployment constraint remains. Hosted revision, real-cycle
acceptance and remaining limitations are recorded in the private release report.
