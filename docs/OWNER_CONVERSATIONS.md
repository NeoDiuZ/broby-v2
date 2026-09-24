# Saved owner conversations and staff handover

Owners can ask questions from a valid private pet link or their saved browser
access. A conversation is scoped to that exact grant and pet; a separate link,
even for the same pet, cannot read its messages. A revoked link loses access.
The existing first-tap flow and approved record vault remain available.

Questions, quoted source receipts and staff replies are persisted. When enabled,
the model only chooses medications, reminders, approved care or staff review.
It receives the question, not the clinic record set. Deterministic code returns
exact shared facts; neither model-authored care advice nor an invented dose can
enter an answer. Without the provider, bounded keyword retrieval remains available;
a provider failure or unsupported question is saved for staff review. Withdrawn
or changed shared records are withheld from old owner answers; the original
receipt remains in staff history. This is not clinical triage or monitored care.

Each message has an idempotency key and durable claim. Concurrent duplicates and
changed retries are rejected. Expired processing claims become failed questions
in the staff queue, with one internal alert, and a late worker cannot publish its
answer. The same message can be retried without adding a duplicate. Questions are
limited to 2,000 characters, threads to 100 messages and owner traffic is bounded
per clinic/pet. Returned fact lists show at most 20 records with an explicit limit.

Staff use **Handover → Owner conversations** to read, reply, acknowledge or close.
A new owner message invalidates the reviewed version. The UI requires a refresh
before submitting a stale review and preserves a drafted reply while refreshing.
Replies are saved to the portal; this never implies a WhatsApp message was sent.
Acknowledgement and closure include the acting member, time and reason.

An owner-marked urgent question creates one internal escalation. An optional
administrator-defined acknowledgement target also creates an internal alert when
it expires. Repeated worker cycles do not duplicate alerts; new messages do not
postpone an existing earlier deadline. Acknowledging/closing resolves the internal
alert. There is no default clinical deadline, on-call delivery or emergency
response promise. The interface explains this before submission.

Current and prepared morning handovers include verbatim owner/clinic messages
and their turn IDs. Prepared handovers remain snapshots of the preparation time;
the live queue shows later changes. They do not manufacture an AI clinical summary.

## Acceptance and remaining channel boundary

31 dedicated regression cases cover approved-only retrieval, link/patient scope,
revocation during provider processing, changed sources, stale reviews, duplicate
messages, provider outage/invalid intent, expired worker claims, saved browser
access, immutable handover receipts, timeouts and access-policy enforcement.
The full suite passed 567 backend tests, with 40 frontend tests, TypeScript and a
production build for the combined release.

Local two-sided browser acceptance uses password authentication, real PostgreSQL
and the production frontend. It records a question, returns only approved care,
receives a follow-up while staff are drafting, rejects the stale review, preserves
the draft on refresh, saves a staff reply visible after owner reload, prepares a
handover and closes the conversation. A real one-minute scheduled target created
exactly one internal overdue alert. All 66 original fixture records stayed exact;
browser error logs were empty. Restart and deployed evidence are recorded in the
release receipt after execution.

Run `scripts/smoke-owner-conversations.py` with private credentials and a new state
file for a synthetic API/provider story. It closes the test conversation and
revokes both test links. Reuse `--verify-only` for readback; `--require-ai` requires
an actual configured model intent receipt. Local tests with providers disabled
are not evidence of an external model call.

Twilio's account still withholds the trial template/API capabilities required for
Broby-originated sends. These portal flows do not prove WhatsApp conversation
routing, delivery or an on-call response. V1's sender is untouched. Verified
cross-device owner accounts, production sender enrollment and clinic staffing/
escalation policy remain separate work or external acceptance requirements.
