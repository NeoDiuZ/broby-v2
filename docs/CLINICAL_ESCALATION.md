# Optional clinical staff notifications

This is a deterministic notification and staff-review workflow, separate from
the infrastructure monitor in OPERATIONAL_ALERTS.md. It never assesses symptoms,
predicts clinical urgency, gives advice, or certifies an emergency response.
Owner-marked urgency, an explicitly configured internal acknowledgement target,
or interrupted question retrieval can create internal attention. External staff
notification additionally requires both explicit deployment configuration and a
reviewed clinic policy. **Both are disabled by default. No live destination or
real recipient has been configured or contacted by this implementation.**

## Explicit configuration and authority

An operator configures `BROBY_CLINICAL_ESCALATION_MODE=webhook` and
`BROBY_CLINICAL_ESCALATION_ROUTES`, a JSON object mapping safe alias labels to
`{"url":"https://receiver.example/path","token":"optional bearer secret"}`.
Actual URLs and tokens remain in backend/dispatcher environment secrets. They
never appear in settings, payloads, logs, receipts or API status. Normal mode
requires HTTPS with system TLS validation. The client follows no redirects,
discovers no proxies and does not read or record response bodies.

`test-loopback` is an explicit local-only mode for synthetic acceptance: literal
loopback IP addresses only, HTTP or HTTPS, forbidden in hosted mode. It is not a
production transport setting. `disabled` is the default and permits no HTTP send.

In Handover → Owner conversations → Clinical staff notifications, an active
administrator reviews the clinic policy through the existing authorized,
versioned and audited `conversation.policy` action. The clinic must supply:

- Distinct active primary and backup clinic members and known destination aliases.
- An explicit primary acknowledgement timeout and a backup timeout measured from
  the primary deadline. The application supplies no clinical timing defaults.
- Exact manual fallback instructions for staff if both deadlines elapse.
- Explicit notification authority for both named recipients and a review reason.

Active membership is a routing eligibility check, not consent to notify someone.
The administrator must separately confirm clinic authority. Notification policy
does not grant any record-reading or acknowledgement permission to a recipient.
The receiver must map each configured alias to the intended authorized member;
that mapping and real recipient receipt require deployment acceptance.

The action retains existing active membership, administrator, read permission,
expected-version, mutation-key and audit guards. An older client omitting the
new escalation object preserves the reviewed external policy. The assistant can
guide the operator to this review; it cannot select unreviewed recipients,
destinations or deadlines as a raw action. No new assistant actions are added.

The policy snapshots a random opaque destination revision. The server's private
route registry compares actual configured destinations and credentials. Removing
or changing a destination fails closed for queued incidents, including if its
alias is reused. A fresh reviewed policy pins the new revision for future owner
questions. Destination digests never enter policy records or staff responses.

## Incident lifecycle and receipts

Opt-in is captured when each new owner question is created. Enabling a policy
does not sweep existing urgent conversations or later timeouts of old questions.
Editing policy applies to future questions; previously opted-in questions retain
their original recipient/deadline policy. Disabling clinic policy or transport
stops pending dispatch. Reactivation does not make an unreviewed replacement
destination eligible. Every dispatch positively rechecks active selected clinic
membership, current enabled policy and the pinned destination revision.

One incident is created per conversation/latest owner turn within the same write
transaction as internal attention. It starts the clinic's primary acknowledgement
deadline immediately, independently of HTTP success. Repeated attention is
deduplicated. If no reviewed acknowledgement arrives by that deadline, the backup
event is queued once and unaccepted primary retries are superseded. If the backup
deadline elapses, **manual fallback remains visibly required until actual staff
review**, even if a receiver returns HTTP 2xx. The read view also derives this
overdue state if the dispatcher itself is stopped.

Staff must read the latest conversation and use the existing reasoned
`conversation.acknowledge` or `conversation.close` action. Thread version and
latest-owner-turn guards prevent stale acknowledgement; pending question
retrieval must finish or recover first. Any currently authorized clinic staff
member can record this review; the receipt names the actual reviewing member,
which may differ from the assigned primary or backup. This records follow-up
responsibility, not delivered treatment or clinical resolution. A normal portal
reply alone is not acknowledgement. New owner input needs a new incident; prior
incidents are retained as superseded history, never labelled acknowledged.
Supersession happens immediately in the new-owner-turn transaction, before
retrieval starts, including when notification policy has since been disabled.
Status prioritizes unresolved incidents and shows total/truncation counts rather
than hiding older unresolved work behind newer completed history.

Clinical eligibility is reevaluated on every incident-status read. If the original
patient/thread is under an identity or provenance hold, delivery/acknowledgement
metadata stays available for administrative follow-up. Preserved free-text policy
and review wording is explicitly qualified as historical evidence, collapsed in
the UI and never presented as current clinical instructions. Original receipts
are not rewritten or deleted; safe staff acknowledgement remains available.

The transport sends only event/incident IDs, an opaque recipient reference, fixed
stage/sequence metadata and deadlines. There are no patient/owner identities,
questions, clinical text, media, fallback instructions or review reasons.
No login link or automatic clinic navigation is sent. The receiver/operator must
sign in, select the exact clinic, open Handover and match the incident reference
before reading its conversation. Internal review navigation remains clinic and
permission scoped; no one-click cross-clinic deep-link acceptance is claimed.

Each HTTP event has a stable `event_id`/`Idempotency-Key`, immutable payload and
durable per-attempt receipt. Six automatic attempts use bounded exponential
delays for timeouts, connection errors, 408/425/429 and 5xx. Redirects and other
HTTP errors stop attempts and remain visible. Primary delivery failure cannot
extend the configured backup deadline. Attempt exhaustion never marks staff
acknowledgement or clears manual fallback.

The receiver must deduplicate event IDs and suppress lower sequences for the
same incident: primary is 1, backup is 2, staff acknowledgement is 3. Acknowledgement
events go to recipients for whom dispatch was attempted. HTTP 2xx means only
**receiver acceptance**. A lost sender can retry an already-applied event; exactly
once delivery is not promised. Token-fenced 30-second claims recover process
loss; late responses retain their attempt receipt without overwriting a newer
claim or a superseded/acknowledged workflow. A request already in flight cannot
be recalled, including after revocation or new owner input.

## Supervision and deployment gates

After the API prepares the schema, supervise `python clinical_escalations.py`
from `api/` separately. `--once` runs one scan/delivery cycle. The five-second loop
stores a heartbeat; the UI marks it overdue after 30 seconds. A supervisor must
restart it. This process needs the same PMS database/schema as the API and no
clinical file volume in PostgreSQL mode; SQLite requires its local database file.
The API's default embedded workers do not silently enable this dispatcher.

The dispatcher cannot report its own host loss or deliver through an unavailable
database/network. An independent availability monitor, named receiver operator,
supervisor/service-execution access, actual primary/backup receipt, staffed
fallback drill and clinic-approved timings are still required for operational
acceptance. The existing matched PostgreSQL/file cloud restore and shared storage
gates remain; local tests do not prove Railway worker separation, cloud recovery,
multiple replicas, an actual on-call response or emergency service readiness.

## Verification

`api/tests/test_clinical_escalations.py` exercises real synthetic loopback HTTP
primary acceptance → timeout → backup acceptance → reasoned staff acknowledgement,
both-deadline manual fallback, HTTP retries/exhaustion, redirects, concurrent
claims/scans, old-client compatibility, explicit future opt-in, policy snapshots,
destination replacement, recipient revocation, independent read permissions,
tenant isolation and disabled/stale states. A real sender is killed after receiver
application; restart retries the same event and the receiver applies it only once.
The suite runs with SQLite and disposable PostgreSQL schemas. Root browser and
hosted-disabled acceptance results are recorded separately after execution.
