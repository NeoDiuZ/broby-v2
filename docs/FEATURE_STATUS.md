# Broby V2 requirements audit — 24 September 2026

Source: [Broby V2 Google Doc](https://docs.google.com/document/d/1Oca1mRqo32iZ7OjH_nz24OjChAuxAUo369uWJmq1kR0/edit), both tabs re-read on 24 September. The 58-item **THE VISION** tab is the full scope. **FIRST BUILD** describes an earlier, smaller milestone; completing it does not complete the product.

This replaces the obsolete status table, which incorrectly continued to list features shipped in PR #5 as missing. The first-build PostgreSQL contract is implemented. The whole vision is **not ready for a real-clinic cutover**. Broby New is a live, authenticated deployment with synthetic data. Stripe sandbox checkout/refunds are deployed and verified; WhatsApp trial activation is complete but its recipient link and backend configuration remain pending. Lab feeds remain simulations. “Implemented” below describes the named capability in that agreed release scope, not a guarantee of clinical accuracy or an end-to-end production certification.

## Every requested feature

| # | Requirement | Current state and remaining work |
|---|---|---|
| 1 | Patient identity; query production first | **Partial.** Stable clinic-scoped IDs, duplicate-name disambiguation, source-ID migration mapping. Actual V1 identity reconciliation and production import have not happened; require an approved export plus implementation of its mapping. |
| 2 | Owners and owner–patient links | **Implemented.** Primary/additional owners, edit/merge and normalized PostgreSQL links. Real V1 data reconciliation remains part of #1/#35. |
| 3 | Open patient events | **Implemented.** PostgreSQL JSONB events, dated timeline, novel event types without a schema migration, deduplicated ingest. Older PMS writes still project from SQLite. |
| 4 | Typed observations | **Implemented.** Number/text/boolean enforced in PostgreSQL; false is preserved; nonnumeric facts cannot receive numerical ranges. |
| 5 | AI-authored ontology | **Partial.** Model/manual proposals, aliases, reviewed acceptance/rejection and immutable codes/types/units. Approved clinical terminology and broader model evaluation remain; a real hosted AI proposal and rejection were verified with synthetic data. |
| 6 | Provenance / receipts | **Implemented with verification limits.** Original document/audio/human receipts, missing-source flags, verbatim AI quote validation, omitted source text and timestamps. This exposes mistakes; it does not certify speech or clinical interpretation accuracy. |
| 7 | Outbox | **Partial.** Durable drafts, edit/cancel/manual completion, simulated delivery callbacks and signed replay checks. A restricted Twilio trial worker, signed callbacks and conservative reconciliation are implemented. Provider configuration/delivery evidence and production customer dispatch remain unfinished. |
| 8 | One action layer for UI and AI | **Implemented.** Shared authorized, versioned, idempotent audited mutations; AI proposals require confirmation. The assistant's field descriptions and intent evaluation still need expansion for all advanced actions; availability of an action is not proof every natural-language request works. |
| 9 | Read APIs | **Implemented.** Clinic-scoped patient search, paged timeline, observations, event detail and source access. Older PMS screens still load full bootstrap datasets; pagination/load work remains. |
| 10 | Numbered voice notes | **Implemented.** Persistent notes, renaming, imported audio, independent capture lifecycle and replay. Real microphone/device/browser acceptance remains limited. |
| 11 | Offline first | **Partial.** Open-page offline notes/audio, durable chunk queue, recovery and retry. Offline cold launch, encrypted local clinical cache/device unlock, cache eviction and full browser crash matrix are not implemented. |
| 12 | Gap detection | **Implemented.** Contiguous upload manifests, checksums, immutable finalized audio, preserved local data on upload/storage failure. Physical device fault testing remains. |
| 13 | Handoff without stopping old device | **Partial.** Devices create independent notes; no remote stop or cursor-transfer action exists. Simultaneous physical-device handoff has not been tested. |
| 14 | Remove 10-second pass; ~25-minute refinement | **Implemented and hosted-verified with synthetic audio.** Automatic previews of complete 25-minute sections while recording, followed by strict final-audio verification and one transcript on Finish. Durable retries reuse decoded-byte/provider receipts; manual completed-note processing remains. Physical long-session/device acceptance remains. See CONTINUOUS_SPEECH.md. |
| 15 | Diarization flag | **Implemented.** Operator can turn speaker separation on/off. Speaker identifiers are scoped per window and must be reviewed before naming people. |
| 16 | Generate notes with receipts | **Implemented.** Verbatim local assembly or provider-selected exact excerpts, character receipts, omitted text review, optimistic-version protection and vet approval. Translation is not implemented; multilingual speech quality is not certified. |
| 17 | Medical vs medical+context retention | **Partial.** Generation preference and omission visibility exist. Original audio/text remain preserved; clinic-approved expiry/deletion schedules, legal holds and deletion reconciliation are not implemented. |
| 18 | Patient timeline | **Implemented.** Dated, paged search/category filters, event details and receipt navigation. |
| 19 | Visual analytics | **Implemented for defined views.** Numeric trends with supplied reference bands, source navigation and saved count/group queries. Broader operational analytics and performance at clinic scale remain. |
| 20 | Bloods/cytology/X-ray/all views | **Implemented.** Category filters and typed findings; manual imaging records are allowed, automated radiology interpretation is removed. |
| 21 | Source-neutral flags | **Implemented.** Range comparisons apply to structured numbers regardless of original source. Missing receipts/ranges remain explicit. |
| 22 | Numbers/ranges/sources, not judgement | **Implemented.** Stored observations and supplied ranges, no inferred diagnoses/treatment or invented clinical ranges. Human/clinical acceptance is still required. |
| 23 | Patient AI chat | **Partial.** Factual retrieval, exact identity, date bounds and confirmed shared actions work. Actor-private saved conversations, retry recovery and reload-safe confirmation are implemented in this release. Rich query composition and a representative live-model evaluation remain unfinished. |
| 24 | Clinic AI chat | **Partial.** Clinic-wide reads, counts, navigation and action proposals. Saved conversations are implemented; the same model evaluation and large-dataset limitations as #23 remain. |
| 25 | AI drives dashboard | **Implemented for defined queries.** Assistant queries can be saved, scoped and re-run against current records. Arbitrary joins/custom chart builders are not implemented. |
| 26 | Clients / patients | **Implemented.** Create/edit/search, merge owners, stable identity, DOB and extra owner links. |
| 27 | Scheduling | **Partial.** Day/week/month, recurring/reschedule/status, staff availability and room collision checks. Full rota management and approved cancellation/no-show/deposit policies remain. |
| 28 | Billing | **Partial.** Integer-cent invoices, explicit discount/tax, PDFs, external payment/refund records and voids. Credit notes, accounting export/reconciliation and clinic-approved tax/accounting rules remain. |
| 29 | Billing / payments | **Implemented for the current synthetic workflow.** Server-priced Stripe sandbox Checkout, signed callbacks, reconciliation and verified partial refunds passed hosted browser/provider checks. Real merchant activation/settlement, full credit notes, clinic billing policy and accounting reports remain. |
| 30 | Inventory | **Implemented for current stock workflows.** Receiving lots/supplier/batch/expiry, remaining balances, FEFO, expired-stock rejection, reasoned stocktakes and purchase orders/partial receiving. Real stock-history migration is excluded. |
| 31 | Medication dispensing | **Implemented.** Atomic eligible-lot consumption with vet-supplied dose/frequency/instructions; no AI dose inference. |
| 32 | Staff | **Implemented for the listed account flows.** Nurse/vet/admin access, activation/revocation, manual single-use invitations, password change, TOTP and recovery codes. Account flows passed isolated tests and ten hosted synthetic checks, including invitation replay, MFA/recovery reuse, password/session revocation, migration replay/conflict and AI proposal review. Email delivery/reset is unfinished. |
| 33 | Reminders / recalls | **Partial.** Due dates, completion, draft preparation and optional scheduled preparation. Sending is disabled; real delivery, retry policy and recall campaign management remain. |
| 34 | Reporting | **Partial.** Clinical/financial counts, net payments, CSV export and handover. Full operational reports, audited accounting reports and clinic-scale performance are unfinished. |
| 35 | Migration tooling | **Partial.** Preview/digest/apply/replay, stable source IDs, conflict rejection, clinical JSON/CSV rehearsal, archives and isolated restore. Actual V1 mapping, financial/stock history, binaries, reconciliation and cutover/rollback rehearsal remain. |
| 36 | Labs / analysers | **Test mode only.** Manual CSV and signed synthetic lab delivery enter real typed records with deduplication/receipts. Vendor selection, mappings/units, device access and real feed acceptance remain. |
| 37 | Owner claim without signup wall | **Partial.** Revocable first-tap clinic link and 90-day saved browser access work. This is a capability, not verified cross-device owner identity. |
| 38 | Pet profiles | **Implemented for shared access.** Approved shared profile and saved multi-pet browser access. Verified owner/household account management is unfinished. |
| 39 | Record vault | **Implemented for shared access.** Approved notes/files/labs; unapproved clinical facts hidden. Verified-account limitation from #37 applies. |
| 40 | Discharge and medication instructions | **Implemented.** Approved care/PDF and recorded dose/frequency/instructions. No invented or translated treatment instructions. |
| 41 | Upcoming/due care | **Implemented.** Shared due reminders ordered by date. External notification delivery is #33/#45. |
| 42 | Vet audio playback | **Implemented.** Explicit audio approval, revocable access and byte-range playback/seek. |
| 43 | Share / grant to a new clinic | **Partial.** Reviewed clinic transfers now copy approved events/files, opt-in original audio and externally recorded medication history. Stable origin mapping skips repeats; changed data (including reversions) appends reviewed revisions without changing local edits or stock. Hosted two-clinic browser/API/PostgreSQL acceptance passed. Verified owner identity and reviewed baselines for transfers accepted before revision tracking remain. |
| 44 | Pre-consult forms | **Implemented.** Submit/edit, duplicate protection, internal urgent flag and accepted intake source receipts. This is not an emergency monitoring service. |
| 45 | WhatsApp BSP / Meta | **Provider integration in progress.** User authorized controlled tests to their own number. Twilio free trial and WhatsApp sandbox are activated after explicit legal approval. A restricted adapter now supports durable trial sends, signed callbacks, canonical delivery reconciliation and an isolated inbound inbox. Recipient linking, configuration and actual delivery tests remain pending; existing WhatsApp is untouched. |
| 46 | Rich discharge / referral media | **Partial.** Shareable approved PDFs/files/audio in the portal. Automatic provider media delivery and receipt tracking remain. |
| 47 | After-hours AI bot | **Not implemented as specified.** Owner portal retrieves saved care/reminders and contact information; there is no persistent after-hours WhatsApp AI conversation/handover service. |
| 48 | Emergency escalation | **Partial.** Urgent submission enters an internal acknowledgement queue. No on-call alert delivery, acknowledgement timeout/fallback or staffed monitoring. Requires clinic escalation policy and an enabled notification provider. |
| 49 | Morning handover | **Partial.** Stored clinic/owner intake overview and urgent queue. Actual after-hours message conversation summaries and staffed handover acceptance depend on #45/#47/#48. |
| 50 | Master multi-clinic account | **Implemented for newly provisioned organizations.** Master provisions clinics and sets inherited restrictions. Adoption of existing independent clinics needs an explicit reconciliation workflow. |
| 51 | Multi-clinic membership | **Implemented.** Credential-to-active-membership checks and clinic switching. |
| 52 | Roles including nurse | **Implemented.** Server-side authorization and active-membership checks. |
| 53 | Feature permissions / master locks | **Partial.** Shared-action restrictions and inherited locks, including clinic-admin restrictions. Granular read restrictions and security/operational acceptance remain. |
| 54 | Remove radiology/differential | **Implemented in V2.** No autonomous radiology or differential agent. V1 has not been altered. |
| 55 | Remove general_knowledge | **Implemented in V2.** Factual retrieval only; no general clinical advice tool. |
| 56 | Remove old prompts/corrector | **Implemented in V2.** New receipt-backed assembly, no medical corrector. |
| 57 | Remove 10-second live chunk pipeline | **Implemented in V2.** Five-second browser chunks are durability/upload pieces, not ten-second AI passes. |
| 58 | Remove duplicate action executors | **Implemented in V2.** UI and assistant proposals use the shared authorization/mutation boundary. |

## Blockers versus unfinished engineering

**Engineering that can continue without a new vendor:** offline cold start/device privacy; long-session physical-device acceptance; verified owner account flows (delivery channel needed for final verification); legacy transfer baseline reconciliation; PMS transition to one canonical PostgreSQL store; independent workers/object storage; pagination/load testing; operational diagnostics/alerts; fuller assistant/action contracts, reporting and test coverage. These are unfinished work, not things an AI agent is inherently unable to build.

**External inputs for final acceptance:** live merchant activation and lab vendor/test access; WhatsApp recipient linking and production sender enrollment; approved V1 export; clinic billing, retention and escalation policies; representative recordings and physical devices. Test adapters cannot prove payment settlement, analyser compatibility, emergency response or customer message delivery.

**Release restrictions still in force:** synthetic data only, no V1 cutover and no real money movement. Controlled WhatsApp tests to the user’s own number are authorized; customer sending is not enabled. The hosted invitation/MFA/recovery and migration checks have now passed.

## Railway / Redis explanation

Broby New contains **Frontend, Backend and Postgres**, all in Singapore, under **cxlabyky's Projects**. Frontend is public HTTPS; the API and database use private routing. Backend has a persistent `/data` volume. Deployments track this repository's `main` branch. PostgreSQL contains the normalized clinical spine; `/data` still contains the SQLite PMS/session/job store plus audio/uploads. Both must be backed up and restored together.

V1's `Redis-Ky2t` supports transient auth tickets, request limits, coordination locks, caches and live-event pub/sub. V2 does not call Redis: its current sessions, rate limits and job claims use its database, and the browser polls for updates. Therefore absence of Redis is **not a missing connection causing current V2 workflows to fail**. Creating an unused Redis service would not add these features or make V2 scalable.

The architectural limit is one backend replica with local persistent files and a remaining SQLite/Pg projection. Moving canonical PMS data to PostgreSQL, externalizing files, and separating workers/observability must precede a multi-replica claim. Redis may then be useful for shared ephemeral coordination/pub-sub if the chosen worker design needs it. Never point V2 at V1 Redis, because that would share sessions/locks/events across environments.

Only the required Deepgram/Anthropic provider keys were reused in the original setup, with real synthetic provider requests verified; no V1 database, Redis, JWT or messaging credentials were copied into use. Shared provider keys also share quota/billing.

## Verification records

- [First-build contracts](FIRST_BUILD.md), [clinic workflows](CLINIC_WORKFLOWS_TESTING.md), [advanced workflows](HARD_WORKFLOWS_TESTING.md).
- [Speech windows and this audit release](SPEECH_WINDOWS_TESTING.md).
- [Deployment and storage boundaries](DEPLOYMENT.md).

A service marked SUCCESS or an HTTP 200 is evidence of deployment/health only. Clinical correctness, external delivery, settlement, physical-device behavior and full disaster recovery require their own evidence.
