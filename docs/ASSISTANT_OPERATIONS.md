# Reviewed assistant operations

## Current coverage — 25 September 2026

All 69 directly proposed assistant operations now have strict typed contracts,
read-only preparation and labelled deterministic reviews. This replaces the old
49 untyped field descriptions and adds ten routine operations: speaker labels,
automation settings, save/archive dashboards, recall preference/cancellation,
leave request/review/withdrawal and discharge draft preparation. Every one of the
105 shared operations is explicitly classified: 69 reviewed proposals, 30 routed
to their dedicated review screen, and six internal test-adapter operations that
are never advertised to the model. Guided operations are not direct AI execution.

Four formerly advertised low-level operations (raw imports and binary recording
creation/finalization) now route to the existing import/recorder screens, where
the source file, manifest and migration review can actually be inspected. Stripe,
Twilio, clinic transfer/adoption, complex rota changes and owner-conversation
replies similarly retain their purpose-built reviews. No arbitrary untyped
mutation fallback remains.

Owner-conversation acknowledgement and closure now have direct assistant
proposals. The operator must use the exact command “Acknowledge conversation
[ID] reason: [reason]” or “Close conversation [ID] reason: [reason]”. The server
requires the exact thread ID and the exact reason in that same request; neither
can be supplied only by the model. The model receives status, urgency, patient
ID and version metadata, never the owner's message text or access-link digest.
The deterministic review displays every human message, the latest owner-turn
ID, urgency and effect. Conversations with more than 20 messages remain in
Handover for full review. Pending or closed conversations cannot be proposed.
Confirmation rechecks the thread and referenced records under the writer lock;
a newer owner message requires a fresh review. Neither action sends a reply or
an external notification.

For hosted synthetic acceptance, run `scripts/smoke-assistant-conversations.py`
with private credentials and a fresh state file in `setup`, `review`, then
`readback` phases. It tests the real model proposal, unchanged record at review,
exact owner text, confirmation/replay, persisted result, internal alert and
revoked owner link without sending a customer message.

New reviews validate exact clinic and patient references, calendar dates, finite
values, explicit tax/discount fields, replacement contact fields and workflow
states. Confirmation checks every referenced record version under the shared
writer lock. A concurrent contact/patient/stock change requires a fresh review.
An already completed confirmation still replays its original receipt exactly,
including after the response was lost. Permission checks remain authoritative.

Intent input is bounded to 250 selection records and 140,000 record characters.
Exact referenced IDs/names, the selected patient and referenced dependencies take
priority. Large fields are omitted explicitly, never truncated into apparent
complete source facts. This is not a limit on factual queries: deterministic
reads still count/filter the complete authorized clinic dataset. Missing context
requires exact identification or clarification, not guessed IDs or facts.

New acceptance covers all 57 expanded contracts through saved proposal, actual
confirmation, persisted result and replay, plus invalid values, unknown fields,
patient isolation, reference changes and permission revocation. The hosted
real-model scenario is repeatable with scripts/smoke-assistant-completion.py.
Real-model intent accuracy remains an acceptance boundary beyond schema validity.

## Earlier release history

Ask Broby can now propose eight additional operations: edit/cancel a reminder,
create/cancel a purchase order, rename a recording, update a patient's complete
owner list, prepare a clinic handover and acknowledge a selected handover.
Reminder creation and completion also use the new typed contracts.

These ten operations provide strict JSON schemas to the model. Before saving a
confirmable proposal, the server checks required fields, types, unknown fields,
calendar dates, exact clinic-scoped record kinds, versions, selected-patient
scope and applicable open/closed state. Invalid proposals become clarifications.
Read-only preparation never calls the mutation executor as a simulated write.
The model receives purchase-order and handover selection metadata as well as
current records; nested handover clinical snapshots are excluded from its input.

The review is built deterministically from those records and the validated
payload. It displays labelled changes, current values where relevant and effects:
reminder edits cancel obsolete unsent drafts, purchase orders do not contact
suppliers or receive stock, and owner changes revoke existing owner access links.
The complete additional-owner list is required to prevent an omitted list from
silently clearing it. Linked record receipts remain available. The displayed
review and confirmed result persist with the private conversation.

Confirmation uses the existing shared action executor. It rechecks permission,
dependency locks and current versions, and the saved turn's idempotency key
prevents duplicate writes. The browser cannot replace the stored payload.
Handover preparation pins the reviewed clinic date server-side and rejects a
confirmation after the clinic date changes; a new proposal is then required.
Older callers without that optional date guard retain their existing behavior.

## Try it with synthetic records

- “Move reminder [exact reminder ID] to 2098-07-12; keep its title.”
- “Create a purchase order for 10 packs of [exact inventory name] from [supplier].”
- “Cancel the remaining balance of purchase order [ID]. Reason: duplicate order.”
- “Rename recording [ID] to Owner follow-up.”
- “Add [existing owner] as an additional owner for this patient; keep the primary owner.”
- “Prepare today's handover.” After reviewing its snapshot: “Acknowledge handover [ID].”

Inspect the labelled review, confirm, reload and reopen the saved conversation.
Check the resulting reminder, order, patient or recording in its normal screen.
Requests missing a purchase quantity must ask for clarification. An intervening
record update must make the old confirmation fail without overwriting that update.

## Acceptance and limits

`api/tests/test_assistant_operations.py` covers every new contract through stored
proposal, confirmation and replay, plus invalid model fields, clinic/kind/patient
isolation, stale versions, dependency revocation, owner grant revocation, reminder
draft cancellation, partially received stock preservation and midnight handovers.
`scripts/smoke-assistant-operations.py` provides explicitly invoked prepare,
evaluate and readback phases using synthetic data, the real configured model,
authenticated hosted APIs, audio-byte verification and saved conversation reloads.
Credentials and capability-bearing evidence belong in ignored private files.

Hosted acceptance on 24 September passed all ten operations with the real model,
plus missing-quantity clarification, stale-write rejection and confirmation
replay. A new authenticated session verified saved reviews/results, reminder
states, received stock, owner links and identical original audio bytes. Browser
acceptance created a synthetic reminder, confirmed it, restored its completed
review after reload and checked its exact title/date in Messages. PR #18 and
the Railway release details are recorded in RELEASE_WORK.md; final acceptance
follow-up evidence is in the ignored operator release report.

The earlier 61-action/12-schema limitation has been superseded by the coverage
and explicit routing above. Clinical interpretation, languages and provider
acceptance still require separate evidence.

Credit-note issue and reversal add two strict contracts with explicit net/tax
amounts, reasons, charge-only effects and resulting balances. See CREDIT_NOTES.md.
Hosted issue/reversal, confirmation replay and saved reviews passed. A provider
format failure on missing tax details led to a structured-intent transport fix;
its local failure/retry tests pass, the failed question recovered through the
browser, and fresh real-model credit/reversal/read/reminder regressions passed.
