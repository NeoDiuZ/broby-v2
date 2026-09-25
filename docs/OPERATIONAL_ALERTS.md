# Optional operational webhook alerts

This feature reports infrastructure worker and queue problems. It does not read
clinical source text, send owner messages, respond to emergencies, or certify an
on-call response. **The default is disabled. No hosted destination or credentials
have been configured by this implementation.** Local acceptance uses synthetic
data and a loopback HTTP receiver only.

## Process and configuration

After the API has prepared the database, run `python operational_alerts.py` from
`api/` as an independently supervised process. `--once` performs one monitoring
and delivery cycle. The normal loop checks every 15 seconds. A separate process
can observe the API/worker process losing its heartbeat without relying on that
failed process to send its own alert. It uses the same PMS database/schema; a
PostgreSQL monitor does not need the audio/upload volume. SQLite mode requires
the same local database file. The monitor never creates schema or clinic data.

| Variable | Meaning |
|---|---|
| `BROBY_OPS_ALERT_MODE=disabled` | Default: no scan, claim or HTTP delivery |
| `BROBY_OPS_ALERT_MODE=webhook` | Enables the configured HTTPS webhook |
| `BROBY_OPS_ALERT_WEBHOOK_URL` | One fixed deployment-configured destination; never accepted from an API action |
| `BROBY_OPS_ALERT_WEBHOOK_TOKEN` | Optional bearer credential; kept in environment secrets |
| `BROBY_OPS_ALERT_MODE=test-loopback` | Explicit synthetic test mode, local environment only, literal loopback IP only; permits HTTP |

Normal webhook mode always requires HTTPS. The client verifies TLS, does not
follow redirects, discover environment proxies, read response bodies, or log
request URLs. URLs, query credentials, bearer tokens, response bodies and raw
exception text never enter the outbox, receipts, logs or health response.

Configure a restart policy for the monitor separately. Its scan heartbeat appears
in Settings → Sync & jobs → Background service health and becomes overdue after
90 seconds. This monitor cannot notify through a database it cannot reach, and
cannot report its own host/process loss while stopped. External availability
monitoring, a staffed on-call destination, escalation policy and real response
acceptance remain deployment/operational gates. `/api/ready` continues to assess
API storage readiness independently.

## Conditions and lifecycle

The monitor reuses the existing worker heartbeat and queue classification. It
opens incidents for a missing/stopped process, process heartbeat older than 30
seconds, overdue/stopped worker cycles, three consecutive failed cycles, worker
history persistence failure, or startup exceeding 30 seconds. Provider-disabled
workers are not failures.

Queue conditions use aggregate document failures/conflicts/overdue work, Stripe
test task failures/overdue work, and restricted WhatsApp trial failure,
undelivered, uncertain, needs-review or blocked states. They include unresolved
older work, matching the existing operational health page. Deliberately canceled
messages are not an alert trigger. No job payload, result, error message, patient,
phone number, provider receipt or clinical text is sent.

Each clinic has its own incident and administrator review boundary. Shared worker
conditions appear in each clinic; the external payload contains only an opaque
incident reference, fixed worker/queue names and aggregate counts. An unchanged
condition creates one opening event. Its latest counts can update in the app
without repeatedly paging the destination. When the observed condition clears,
one recovery event is created atomically. A later recurrence starts a new incident.

Unaccepted opening events are superseded when recovery is observed so a delayed
retry cannot reopen an already recovered condition. Their receipts remain. An
in-flight request may still arrive, so every event includes an immutable sequence:
opening is 1, recovery is 2. **The receiver must deduplicate `event_id` and ignore
lower sequence numbers for an incident.** The `Idempotency-Key` header is the same
event ID on every automatic or manually reviewed retry. Exactly-once delivery is
not claimed; a timeout or interruption can occur after the receiver accepted a
request but before Broby saved its response.

## Delivery and review receipts

Detection and outbox creation are one transaction. A sender claims an event with
a 60-second lease and a new token. Each attempt has a durable start, finish,
allowlisted outcome and optional HTTP status. A replacement can recover an
expired claim; an old claimant cannot overwrite the new event state. A killed
final attempt becomes visibly failed after its lease expires.

A 2xx response records **webhook acceptance**, not human delivery or response.
HTTP 408/425/429/5xx, timeouts and connection failures retry with increasing delay:
30, 60, 120, 240 and 480 seconds for the initial six-attempt budget. Other HTTP
responses, including redirects, need review immediately. Manual retries preserve
the exact event ID/payload and all prior receipts, add a six-attempt budget, and
keep subsequent delays bounded at 15 minutes.

Administrators review details and enter an explicit reason in Settings. Both
actions use `actions.execute`, active membership, administrator permission,
clinic ownership, current incident version, normal idempotency keys and audit:

- `operations.alert.acknowledge`: `id`, `version`, `reason`. Records that the
  administrator reviewed the incident. It changes neither recovery nor delivery.
- `operations.alert.retry`: `id`, `version`, `event_id`, `reason`. Requeues a
  failed event after destination/configuration review. Accepted or superseded
  events cannot be manually resent. Disabled transport leaves the retry queued.

Reasons and review history remain in the administrator view; they are never
included in webhook events. Assistant requests route to this explicit review
screen. The health response shows totals for the entire clinic and at most 20
incidents, 10 recent receipts per event and 10 recent administrator reviews per
incident. The PostgreSQL/SQLite tables are included by the existing coordinated
whole-store backup; this does not substitute for a cloud restore rehearsal.

## Verification

`api/tests/test_operational_alerts.py` uses an actual temporary loopback receiver
and synthetic queue data. It checks 503→scheduled retry→204 with the same event,
redirect rejection, receipt retention/manual retry, recovery ordering, bounded
exhaustion, killed claimant/restarted monitor recovery, disabled mode, strict
destination rules, concurrent detection, sanitized payloads/errors and active
administrator/clinic/version/reason boundaries. It runs in both SQLite and
PostgreSQL PMS modes. Existing worker/health/action-contract tests and frontend
typechecking remain part of the integration checks.
