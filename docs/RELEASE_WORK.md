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
