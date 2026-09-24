# Reviewed assistant operations

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

There are now 61 advertised actions out of 105 shared operations. Twelve use the
new strict proposal schemas; the other 49 retain their earlier field descriptions
and executor-time validation. The remaining 44 advanced operations still need
appropriate review contracts. This is not blanket coverage of all natural-language
intents, languages, clinical policies or ambiguous ownership instructions.
Model interpretation remains fallible: the operator must inspect the exact review.
The other offline, storage, accounting, provider and cutover gaps in FEATURE_STATUS
remain open. No supplier message, customer send or real payment is part of this work.

Credit-note issue and reversal add two strict contracts with explicit net/tax
amounts, reasons, charge-only effects and resulting balances. See CREDIT_NOTES.md.
Hosted issue/reversal, confirmation replay and saved reviews passed. A provider
format failure on missing tax details led to a structured-intent transport fix;
its local failure/retry tests pass, the failed question recovered through the
browser, and fresh real-model credit/reversal/read/reminder regressions passed.
