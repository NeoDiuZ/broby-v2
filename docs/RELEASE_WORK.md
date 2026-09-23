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

## In progress — reviewed clinic-transfer release

Implementing explicit optional audio/medication consent, receiving preview/digest,
immutable origin revisions, subsequent-request deduplication, exact binary copies
and rollback cleanup. Medication history cannot dispense or change stock. Private
transcripts remain excluded. See CLINIC_TRANSFERS.md. Older accepted transfers
without source manifests require a reviewed baseline; verified owner identity
remains unfinished. No full-vision completion claim is made.
