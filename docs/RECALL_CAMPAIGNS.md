# Reviewed recall campaigns

Messages now includes **Recall campaigns**. Choose an inclusive due-date period
(up to 366 days), optionally filter reminder titles, then preview. A review is
limited to 100 matching reminders; narrow the filter when it exceeds that limit.
The screen shows patient, primary owner, contact information, due date and exact
server-composed message. Select eligible reminders and name the campaign before
preparing. Preparation creates manual drafts and sends nothing.

## Integrity and progress

The review digest covers clinic, filters, reminder versions, patient/owner versions
and displayed recipient information. The shared action executor validates it again
inside the same write transaction as campaign/draft creation. Any intervening
change rejects the whole preparation; partial writes roll back. Same-key replay
returns the original campaign, and a fresh key cannot reuse a stale review.

Campaign progress reads current outbox records: pending, cancelled, sent manually,
skipped/excluded, missing or needing review. The original recipient review remains
stored. Cancelling a campaign cancels only its pending drafts, retaining completed
history and unrelated messages. Reminder edits/closure cancel their pending drafts.
A cancelled draft retains its reminder link, so scheduled preparation or another
campaign cannot silently send it again. After a deliberate reminder correction,
staff must review a new draft. There is no automatic retry of uncertain delivery.

Owner recall preferences record who changed an opt-out, when, why and which drafts
were cancelled. Opt-out cancels that owner's pending reminder drafts across all
campaigns; non-reminder care messages remain unchanged. Withdrawing an opt-out does
not resurrect drafts. Owner merges preserve an existing opt-out. Absence of an
opt-out is not evidence of marketing or WhatsApp consent.

Editing a recall draft, opening its WhatsApp link, copying it for delivery and
marking it sent recheck the reminder, current primary owner, contact details and
opt-out. Stale or legacy drafts without a recipient snapshot require a new review.
The external WhatsApp page is a manual handoff: Broby cannot revoke already-copied
text or a tab someone has opened. Staff must check the recipient before sending.
“Sent manually” records a staff assertion, not a provider receipt.

## Permissions and endpoints

All writes use the shared authorized, audited, versioned action boundary:
`recall.prepare`, `recall.cancel`, `owner.recall_preference`. Preparation inherits
`message.queue` restrictions, cancellation inherits `message.cancel` restrictions.
Clinic-scoped reads: `POST /api/recalls/preview`, `GET /api/recalls/{id}` and
`GET /api/outbox/{id}/delivery-review`. Delivery review requires `message.complete`.

## Verification and limits

Thirty regression cases cover stale review, concurrent preparation, exact message
content, duplicate/replayed requests, rollback, bounds, selection, cross-clinic
access, permission locks, contact/ownership changes, opt-out, merge inheritance,
sent-history preservation and old drafts. Isolated production-browser acceptance
prepared two drafts, opted one owner out, cancelled the other and checked progress.
All 66 original fixture records remained exact. Both services restarted and saved
campaign/opt-out/cancellation history persisted. A repeatable API harness passed
15 checks and 9 readbacks; no external messages were sent.

Run `scripts/smoke-recalls.py BASE_URL --credentials PRIVATE_JSON --state NEW_JSON`
only once per synthetic fixture; use `--verify-only` for subsequent verification.
Credentials/state files belong in ignored private storage. The harness closes its
test reminders and cancels all drafts, retaining an auditable synthetic history.

This completes reviewed manual recall campaign management. Actual BSP delivery,
provider-specific consent/templates, retry/receipt policies and bulk-load testing
remain separate. Twilio's own-number join/reply is verified; its trial UI still
withholds template controls. Customer sending remains disabled. Campaign reads
still use the current full-dataset store; this is not clinic-scale certification.
