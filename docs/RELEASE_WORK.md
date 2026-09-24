# Completion work in progress

This follows the 58 requirements in FEATURE_STATUS.md. A shipped feature must have
its code, failure-path tests, hosted verification and exact deployed revision
recorded before its status is changed to complete.

## Confirmed release decisions

- Broby New remains separate from V1, using synthetic records.
- Stripe is the selected payment provider: one clinic merchant, starting in a real
  Stripe sandbox. Live account activation and real settlement are separate gates.
- The user authorizes a controlled WhatsApp test to their own number. Existing
  V1 WhatsApp routing and its registered number must remain intact.
- The user authorizes provisioning required services and accounts. Provider
  verification, legal acceptance and security prompts are handled when reached.

## Work sequence

1. Real Stripe Checkout, signed durable callbacks, reconciliation, refunds,
   duplicate/concurrent/failure tests, deployment and browser payment test.
2. WhatsApp test sender onboarding, bounded recipient access, inbound/outbound
   delivery state and retry/reconciliation; real recipient receipt verification.
3. Durable assistant conversations and complete permitted action contracts.
4. Offline cold launch and encrypted local clinical storage; continuous recording
   refinement; cross-device and transfer reconciliation.
5. Canonical PostgreSQL PMS, external files, independent worker, pagination and
   operational monitoring, with recovery and load acceptance.
6. Remaining billing/rota/retention/owner identity/reporting requirements and
   vendor-specific lab/migration work once the actual inputs are available.

Do not label placeholders, a healthy deployment, test-mode money or an internal
notification as verified live delivery, settlement, clinical acceptance or a V1
cutover. See FEATURE_STATUS.md for the complete open requirement inventory.

## Acceptance — staff rota and dated leave, 24 September

The previous form replaced a staff member's whole week with one day. The editor
now retains all weekdays and staff, supports split shifts/breaks and reasoned dated
leave/replacement hours, and presents effective shifts from Appointments and
Settings. Review lists affected bookings. Saving checks scheduled/arrived bookings
from the clinic-local current date onward inside the same transaction used by
booking creation; conflicting schedules or room removal are blocked. Create,
reschedule, recurring series and reopening all use the same effective-shift rules.

Local acceptance covers the complete backend suite, including 32 new rota cases,
16 frontend tests, TypeScript and the production build. An isolated production
frontend/API with separate SQLite/files and PostgreSQL schema passed browser
conflict preview, split shifts, dated leave, reload persistence, frozen draft,
stale-version rejection/reopen recovery and appointment-form leave rejection.
Eight API/database checks confirmed exact saved shifts, retained weekdays/leave,
break/leave booking rejection, an allowed afternoon booking, durable SQLite state
and the concurrent revision used for the stale-editor check. The local fixture is
in `.local/rota-ui/`; do not rerun its prepare/readback mutation phases.

Hosted verification and exact release identifiers are recorded separately in
`.local/reports/broby-rota-release-2026-09-24.md` when completed. No clinic policy,
V1 data, messaging or payment configuration is changed. See STAFF_ROTA.md for
boundaries; the overall scheduling requirement remains partial.

## Acceptance — earlier transfer baseline recovery, 24 September

Patients imported before revision tracking can now receive further updates through
an explicit reviewed current-source baseline. A current owner transfer request is
still required. The receiving reviewer sees patient/owner identity and earlier
clinical copies, records a reason, and acknowledges possible duplicate facts.
Acceptance appends current approved source records, retains all earlier copies
and local edits, and records a private timeline receipt. It never invents the
missing historical manifest or calls an old record an equivalent match.

Local acceptance passed 293 backend tests, including 12 baseline cases, plus
16 frontend tests, TypeScript and the production build. A separate local production
frontend/API with isolated SQLite/files and PostgreSQL schema reproduced the old
import layout. Browser acceptance verified the disabled confirmation, displayed
earlier record, stale-owner rejection, reload/reset, successful import and restored
timeline after reload. Ten API/database checks verified the single saved baseline,
review reason/actor, every preserved record/stock value, prior file bytes, the
PostgreSQL timeline, replay and next-request deduplication.

The current hosted synthetic fixture has no pre-revision mapping. Historical
recovery evidence is therefore isolated-local, with normal-transfer regression
verified separately after deployment. Exact release SHA, deployment IDs and hosted
evidence are recorded in `.local/reports/broby-baseline-release-2026-09-24.md`.
Private local evidence is in `.local/baseline-ui/` and `.local/baseline-*.txt`.
V1, provider configuration, WhatsApp and payments are outside this release.

## Verified checkpoint — 24 September

Stripe PR #9 is merged and deployed at `5d9f35d`. Hosted declined-card, successful SGD 1.00 payment, signed event receipt and SGD 0.40 partial refund were verified in the browser and against Stripe. Private evidence: `.local/stripe-hosted-results.json`. The ten hosted account/migration/ontology checks also passed; evidence: `.local/advanced-access-results.json`.

Twilio trial account and WhatsApp sandbox are activated with explicit user approval. Recipient must send `join twilio-trial` to the trial sender shown in Twilio; a user-input request is pending. Native WhatsApp controls did not open its new-chat form. Do not claim delivery or backend integration complete. The earlier console-domain review rejection was resolved using official Twilio documentation.

Assistant history PR #10 is merged and deployed at `1a67908`. Eight hosted real-AI/privacy/replay checks passed, followed by browser question/confirmation/reload acceptance. Evidence: `.local/assistant-hosted-results.json`.

WhatsApp trial adapter and admin UI were merged in PR #11 and deployed at `628638c`, disabled pending provider setup. Twelve provider-mocked failure-path scenarios cover signatures, isolation, uncertain send recovery without resend, consent and polling bounds. See WHATSAPP_TRIAL.md. Recipient join, actual credentials/template configuration and real delivery remain pending; the user-input request is still open. Official trial restrictions prevent custom clinic messages before upgrade/registered sender.

Continuous recording refinement PR #12 is merged and deployed at `7a87357`. The full 161-backend/14-frontend suite and CI passed. Hosted real-Deepgram acceptance passed eight preview checks and ten final checks, with identical preview/final decoded bytes, reused provider receipt, one source and original audio integrity. The browser showed the provisional preview outside Sources, then both final timestamped markers. An additional isolated real-browser MediaRecorder/IndexedDB test passed with 11 seconds of generated audio. See CONTINUOUS_SPEECH.md and `.local/continuous-hosted.json`. Physical long-session/device acceptance remains.

## Verified checkpoint — reviewed clinic transfers

PR #14 is merged at `040afab44e0121b0c30edb9f4699920ddfcac9cc`.
Backend `d26991af-76eb-4971-b742-e4c05319534a` and Frontend
`0572f14d-e10e-4112-aa9f-2bfaef840a88` both deployed successfully in Broby New.
Final PR head `66e72d2` passed CI run `35908273168`; the local full suite passed
185 backend tests, including 24 transfer cases, plus 14 frontend tests, TypeScript
and the production build.

Hosted synthetic acceptance passed: owner consent and persistent request state;
receiving-clinic preview and initial import; exact original audio/file bytes;
private receiving defaults; unchanged stock/no dispensing; repeat-request dedupe;
explicit changed-source review and preserved local patient edit; both immutable
identity revisions; normalized PostgreSQL timeline with typed potassium and
external medication history; independent media after source-grant revocation.
The copied two-second generated WAV played to its end in the browser (duration 2,
currentTime 2, ended true, no media error). Native accessibility clicks on the
embedded browser's media play button crashed that test tab twice; a fresh tab and
normal keyboard playback completed successfully. The cause of the native-control automation crashes remains unconfirmed;
keyboard playback succeeded and no server failure was observed. Backend error-log query
returned no matches. No physical microphone, V1 data or customer contact was used.

Evidence: `.local/transfer-hosted.json`, `.local/transfer-hosted-prepare.txt`,
`.local/transfer-hosted-verify.txt`, `.local/transfer-hosted-final.txt` and
`.local/reports/broby-transfer-release-2026-09-24.md`. The private state includes
an already-revoked synthetic owner capability; never copy it into public docs.
The synthetic receiving clinic was provisioned through the existing organization
workflow under the same administrator, within Broby New.

A follow-up makes the receiving preview readable as labelled clinical fields,
with a clear medication-history title. It does not change consent or acceptance
boundaries. Final follow-up deployment/readback evidence belongs in the private
release report. Verified owner identity and baselines for old accepted transfers
without origin manifests remain unfinished; see CLINIC_TRANSFERS.md.

## Verified checkpoint — assistant query parity

PR #16 merged at `c5f28629a7d72c79d8600394ac026152a56a73d5`. Backend
`0e0aaea0-85b9-4494-b346-c072e8a9077d` and Frontend
`6c743e06-5fcf-4adc-a291-a5d739162319` both deployed that exact revision in
Broby New. PR CI `35913556217`, push CI `35913511487` and main CI
`35913932834` passed. Local acceptance passed 216 backend tests against isolated
PostgreSQL, 14 frontend tests, TypeScript and the production build.

The assistant previously applied low-stock/outstanding filters without storing
them in its saved query, so Reports could show a broader result. Both surfaces
now use the same validated contract/executor. Status/name/code/unit/value filters,
clinic-local occurrence dates, reminder due dates and groupings are explicit.
Boolean false remains distinct from zero or text. See ASSISTANT_QUERIES.md.

Fifteen hosted checks used the real configured AI provider: low/all inventory,
patient outstanding invoices, future due reminders, numeric PostgreSQL facts
with original receipts and clinic dates, boolean false, unsupported-join
clarification, prescribing refusal, six exact saved-view comparisons and invalid
filter rejection. Four refresh checks proved a persisted inventory change updates
the view while the saved answer remains unchanged, sending stays disabled and
storage stays ready. One fixture preparation/readiness check also passed.

Browser acceptance asked for low stock grouped by name, saved the answer, opened
Reports, inspected the original record, reloaded and restored the same filters.
After a synthetic stock change, Refresh results changed one match to zero; opening
the saved conversation still showed its dated original one-match answer.

All fixtures belong to the existing synthetic receiving clinic in Broby New.
No V1 access, customer message or payment occurred. Evidence lives in
`.local/query-hosted.json`, `.local/query-hosted-evaluate.txt`,
`.local/query-hosted-refresh.txt` and the private query release report. This
verification does not complete advanced action contracts, arbitrary joins,
representative clinical/language evaluation or large-data performance.

The acceptance follow-up also clears the previous view while a new selection loads
and ignores late responses from a superseded selection/clinic. This prevents
rapid selection changes from attaching the previous result to the new selection.
Final follow-up revision/deployment and browser readback are recorded privately.

## Verified checkpoint — reviewed assistant operations

Eight additional assistant operations now cover reminder edits/cancellation,
purchase orders/cancellation, recording names, complete owner links and handover
preparation/acknowledgement. Ten operations (including existing reminder create
and complete) use strict schemas, read-only record/version/patient checks and
deterministic labelled reviews. Missing/invalid fields produce clarification.
Saved confirmation still uses the shared permission/version/idempotency boundary.
Handover preparation also rejects confirmation after the reviewed clinic date
changes. See ASSISTANT_OPERATIONS.md for exact scope and outstanding contracts.

PR #18 merged at `7fe01daf6df14da7f1b00eab3d8ff1245bccc1e8`. Backend
`fe70f553-6147-462d-9762-c6d14ab96dfe` and Frontend
`8b4de65e-9006-45da-8c9e-c7ed5a8bb54a` deployed that exact revision successfully.
PR/push CI `35920552784` / `35920522375` and main CI `35920847185` passed.
Local verification passed 246 backend tests, including 30 operation scenarios,
plus 14 frontend tests, TypeScript and the production build.

Real-provider hosted acceptance passed all ten typed operations, missing-quantity
clarification, stale-confirmation rejection and repeat-confirmation identity.
Readbacks verified all saved reviews/results, cancelled drafts, preserved partial
stock, owner-link revocation, unchanged original audio bytes and disabled sending.
Browser acceptance created and confirmed a synthetic reminder, restored its
completed review after reload and found the exact reminder/date in Messages.
A small follow-up replaces the historical "nothing changed" introduction after
confirmation with an explicit completed-review message. Final follow-up deployment
and readback evidence is kept in `.local/reports/broby-operations-release-2026-09-24.md`.

Private fixtures/evidence: `.local/operations-hosted.json`,
`.local/operations-hosted-prepare.txt`, `.local/operations-hosted-evaluate.txt`,
`.local/operations-hosted-readback.txt`. They contain synthetic data and a revoked
owner capability; never copy credentials/capabilities into repository docs.

## Credit notes — deployed core and acceptance follow-up

PR #20 is merged at `080643d2de6d1a08e241e7899a340b5ee1ac1109`.
Backend `7a03d686-49cc-4f1b-b6b6-39019f174fc4` and Frontend
`52387d5f-bc3a-4a2d-89d7-37a12a51ded4` deployed successfully in Broby New.
PR/push CI `35927255809` / `35927220173` passed. Local credit release checks
passed 267 backend tests, 16 frontend tests, types and production build.

Hosted synthetic acceptance verified real-model credit issue/reversal, no write
before confirmation, replay, paid-credit refund due and external refund records.
The browser issued a 218-cent credit, reloaded it and reversed it, restoring the
1090-cent invoice with the full history retained. A real Stripe sandbox checkout
charged 80 cents after a 20-cent credit. A subsequent 30-cent credit and verified
Stripe refund left the original 100-cent invoice with 50 cents credited and
50 cents paid. Stripe's API independently confirmed test mode, payment and exactly
one successful 30-cent refund. A fresh app session verified balances, saved reviews,
immutable notes/reversals, the CSV register and both PDFs, which were rendered and
visually checked. No real money, V1 or customer message was involved.

The missing-tax real-model case exposed an invalid JSON response twice. No clinic
records changed; its failed question remains retryable. The follow-up changes the
assistant planner to a structured result collector, without executing model tools,
and maps provider failures to a safe retryable HTTP response. Local acceptance for
that fix passes 281 backend tests. PR #21 deployed this fix at
`62ab61895bbd5979f9a5ebc7432a5d5713ec7214`: Backend
`edba1f0c-d89b-45ce-8558-93bc19a1251f`, Frontend
`ebe37535-9187-42f6-9d83-d4b1d3a2c5f1`, both SUCCESS. PR/push CI
`35928564045` / `35928533147` and main CI `35928865824` passed. The exact failed
question recovered using the browser Retry button and its original saved turn.
Four fresh real-model proposals/reads passed with identical before/after clinic
record snapshots. The acceptance harness now retains both snapshots and excludes
only independent Stripe poll timestamp/version metadata when comparing results.
Fresh-session credit/export/payment readback was repeated on this revision.
The report CSV was downloaded through the browser and reconciled to the hosted
records (15657 cents net charges, 50 cents net credits, 873 cents net payments). This remains a scoped billing release,
not a general ledger, approved clinic policy or completion of the 58 requirements.
See CREDIT_NOTES.md and the ignored `.local/credit-hosted.json` evidence.

## Reviewed links to existing receiving patients

A receiving vet or administrator can select an independently created clinic
patient for an unmapped incoming transfer. Acceptance requires a fresh review of
source and receiving identities, all receiving owners and existing history, a
recorded reason and explicit duplicate-risk acknowledgement. It preserves local
records, creates an immutable link receipt and uses that mapping on future
transfers. Known species/origin conflicts and changed previews are rejected.
This does not prove owner identity, equate independent clinical facts or provide
a correction/relink workflow. See CLINIC_TRANSFERS.md for the exact boundary.

Local verification passed 357 backend tests (31 patient-link cases and a native
PostgreSQL integration scenario), 16 frontend tests, TypeScript and the production
build. The production browser rehearsal verified disabled acceptance before
review, stale additional-owner rejection, reset after reload, acceptance into the
same patient and persistence. Sixteen API/database checks passed, including exact
file/audio bytes, all preexisting records unchanged, private copies, stock
invariance, replay, subsequent-request deduplication and source revocation.
Providers were disabled in the isolated local fixture.

The hosted synthetic acceptance fixture is prepared in Broby New. Deployment
revision, CI, hosted browser/API results and final readback are recorded after
release in `.local/reports/broby-patient-link-release-2026-09-24.md`. No V1 data,
active WhatsApp connection, customer message or real payment is involved.


## Background worker diagnostics and guarded recovery

The four existing background workers now use one supervisor with sequential
cycles, interruptible bounded backoff and sanitized persistent failure/recovery
history. Unexpected polling/storage failures can no longer silently kill the
speech/document worker. Long-running calls are flagged for inspection, never
forked or terminated blindly. Separate stop events prevent a new application
lifespan from resuming an older loop. Provider/task permissions, leases,
idempotency and uncertain-send protection remain unchanged.

Administrators can inspect Settings → Sync & jobs for process-local worker
progress and clinic-scoped document/payment/WhatsApp queues. Counts include all
saved work; issue lists are bounded to 20 per queue. Claims and scheduled retries
are distinguished from overdue unclaimed work. Existing failed-document retry
uses the shared audited action. Provider credentials, task payloads, source text
and raw exceptions are excluded from the diagnostic response.

Local verification passes 378 backend tests, including 21 operational cases,
16 frontend tests, TypeScript and production build. Production-browser acceptance
uses an isolated SQLite/files/Pg fixture with all providers disabled and a
controlled worker failure. The page showed the fault, queued a guarded retry,
recovered the original document with exact receipts, and retained nine controlled
loop failures plus recovery time after a server restart. Twelve API/data checks
passed, including clinic preservation and administrator-only access. Exact results
and final hosted revision are recorded
in `.local/reports/broby-operations-health-release-2026-09-24.md`. This release
provides in-app diagnostics, not external alerts, delivery/settlement proof or
multi-worker infrastructure. See OPERATIONS_HEALTH.md for limits.
