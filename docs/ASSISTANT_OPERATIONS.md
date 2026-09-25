# Reviewed assistant operations

## Current coverage — 25 September 2026

All 74 directly proposed assistant operations now have strict typed contracts,
read-only preparation and labelled deterministic reviews. This replaces the old
49 untyped field descriptions and adds ten routine operations: speaker labels,
automation settings, save/archive dashboards, recall preference/cancellation,
leave request/review/withdrawal and discharge draft preparation. Every one of the
105 shared operations is explicitly classified: 74 reviewed proposals, 25 routed
to their dedicated review screen, and six internal test-adapter operations that
are never advertised to the model. Guided operations are not direct AI execution.

Two additional formerly guided operations now have direct saved reviews:

- `recall.prepare`: use “Prepare recall campaign [title] from [YYYY-MM-DD] to
  [YYYY-MM-DD] reminders: [comma-separated IDs]”. The current operator request
  supplies the complete selection of 1–20 reminder IDs, dates and campaign title;
  model substitutions are ignored. The review displays each exact manual draft,
  patient, primary owner, recorded contact details and recall opt-out state.
  The server derives the existing recall-preview digest; it cannot be supplied
  by the model. Confirmation rechecks the entire bounded preview and selected
  record versions, then creates only these drafts. A new matching reminder,
  contact/name change, owner opt-out or concurrent draft preparation requires a
  fresh review. No message is dispatched. Recorded preference checks do not
  establish clinic-approved consent or real delivery acceptance.
- `escalation.acknowledge`: use “Acknowledge escalation [ID]”. The exact target
  and its current version come from the operator command and server records.
  The review displays the original owner intake or complete human conversation
  of at most 20 turns, urgency and current external-delivery state. Confirmation
  pins the source intake/thread and patient as well as the alert; newer source
  information requires review again. This acknowledges only the internal alert:
  it does not send a notification, reply to the owner or close the conversation.
  Pending, longer or source-less conversations remain in Handover.

Both retain shared permission/dependency locks and the saved turn's idempotency
key. Their strict schemas reject unsupported fields, duplicate/oversized recall
selections, invalid dates and cross-clinic or selected-patient references. The
exact alert target adds selection metadata to the model context; its original
owner source text is read directly for the deterministic human review. Provider
dispatch, master-policy decisions, clinic transfer/adoption approval and binary
capture retain dedicated screens.

`scripts/smoke-assistant-guided-completion.py` provides V2-only synthetic `setup`,
`review` and `readback` phases. Run setup/review, inspect and confirm both saved
proposals in the browser, then run readback. It verifies unchanged records before
confirmation, exact saved drafts, actor-private review/result persistence and
confirmation replay. Afterwards it cancels unsent synthetic drafts, closes the
synthetic thread and revokes its owner link. Keep credentials and capability-bearing
state files outside Git. The script itself is covered through authenticated local
APIs with a stubbed intent model; hosted real-model/browser acceptance is still
required after deployment. These workflows do not establish emergency-service,
real-provider or real-clinic acceptance.

Two administrative operations also support exact saved proposals:

- `organization.join_cancel`: “Withdraw organization request [ID] reason:
  [exact reason]” identifies only this clinic's pending request. Review shows the
  originally requested organization, clinic, requester, dates, reason, access
  consent and inherited restrictions. Confirmation withdraws that request while
  preserving its history. It grants no organization access, changes no membership
  and transfers no records. Changed requests, clinic details or requester records
  require a fresh review; already accepted or withdrawn requests cannot be used.
- `access.member`: “Set member [ID] read restrictions: [comma-separated read
  capability IDs, or none] reason: [exact reason]” replaces the complete list for
  another clinic member. Review shows current/new member restrictions, all current
  and resulting capabilities, inherited restrictions, and view availability with
  dependencies (billing also needs patients; mixed views need every area). An
  inactive member stays inactive. Member roles, write permissions and memberships
  are unchanged; clinic/master restrictions still apply. Own-account restriction
  changes and organization-master recovery-access changes are rejected.

The server extracts these administrative targets, complete lists and reasons from
that exact operator turn, ignoring model substitutions, and supplies current
versions. Both require clinic-wide chat and retain current administrator checks.
Member-access reviews also pin an internally generated digest of organization
policy and actor/target account relationships, covering authoritative state kept
outside versioned clinic records. The shared executor checks it under its writer
lock before applying the restriction change. Existing direct UI calls remain
compatible. Completed confirmations replay the original receipt even if the
reviewed policy subsequently changes.

`api/tests/test_assistant_administration.py` exercises the real shared proposal,
saved confirmation and read-permission paths with synthetic records, including
inherited restrictions, route dependencies, inactive members, protected masters,
permission revocation, concurrent adoption acceptance and policy/account changes.
Model intent is stubbed in these regressions. Hosted model/browser acceptance and
real-clinic administrative sign-off remain separate from these engineering checks.

Four formerly advertised low-level operations (raw imports and binary recording
creation/finalization) now route to the existing import/recorder screens, where
the source file, manifest and migration review can actually be inspected. Stripe,
Twilio, clinic transfer/adoption and complex rota changes retain their
purpose-built reviews. No arbitrary untyped
mutation fallback remains.

Owner-conversation acknowledgement, closure and staff reply now have direct
assistant proposals. The operator must use the exact command “Acknowledge
conversation [ID] reason: [reason]”, “Close conversation [ID] reason: [reason]”,
or “Reply to conversation [ID] message: [exact staff text]”. The model selects
only the operation. The server extracts the exact thread ID and reason or
owner-visible reply from that same operator request and reads the current
thread version; model substitutions are ignored. The model receives status, urgency,
patient ID and version metadata, never the owner's message text or access-link digest.
The assistant request accepts the full 4,000-character staff reply plus its
command prefix; the normal Handover editor remains available for multiline work.
The deterministic review displays every human message, the latest owner-turn
ID, urgency and effect. Conversations with more than 20 messages remain in
Handover for full review. Pending or closed conversations cannot be proposed.
Confirmation rechecks the thread and referenced records under the writer lock;
a newer owner message requires a fresh review. A reply is visible in the owner
portal after confirmation, leaves the urgent internal alert open, and sends no
WhatsApp or email. Acknowledgement and closure send no owner reply or external
notification.

For hosted synthetic acceptance, run `scripts/smoke-assistant-conversations.py`
with private credentials and a fresh state file in `setup`, `review`, then
`readback` phases. It tests the real model proposal, unchanged record at review,
exact owner text, owner-visible portal reply, confirmation/replay, persisted
result, internal alert and revoked owner link without sending an external
customer message.

This hosted script passed on 25 September at deployed V2 revision
`20a186c965517accf23bc6fef4f088cefda0c896`: one synthetic urgent owner
question, real-model exact closure proposal, unchanged record at review,
confirmed close, idempotent replay, and new-login readback of the exact review,
result, internal-only escalation and revoked owner link. The separate persisted
V2 smoke passed 17/17. These checks do not validate arbitrary owner language,
on-call delivery, or real-clinic policy.

The extended reply-and-closure script passed on 25 September at V2 revision
`dab49ead6fda8f73819a74c4ae21bc1201ff0f48`, including a real-model
proposal, unchanged review state, exact owner-portal reply, open urgent alert,
idempotent reply and closure, persisted readback and two exact patient-timeline
receipts. Before the exact-command fix, a model field substitution was safely
rejected with no reply saved. The fix derived the thread ID, staff text and
current version from the operator request and clinic records. Its exact-commit
push CI passed frontend, SQLite, PostgreSQL and packaged API checks. A separate
deployed-browser test displayed the exact owner/staff text and effect before
confirmation; staff/owner API readback matched the single confirmed reply and
the synthetic link was revoked. Twilio and external email remained unused.

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

New acceptance covers all 62 expanded contracts through saved proposal, actual
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
