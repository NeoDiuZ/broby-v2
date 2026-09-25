# Broby V2 requirements audit — 25 September 2026

For the concise launch classification and release gates, see
[the 24 September launch audit](LAUNCH_AUDIT_2026-09-24.md).

Source: [Broby V2 Google Doc](https://docs.google.com/document/d/1Oca1mRqo32iZ7OjH_nz24OjChAuxAUo369uWJmq1kR0/edit), both tabs re-read on 25 September. The 58-item **THE VISION** tab is the full scope. **FIRST BUILD** describes an earlier, smaller milestone; completing it does not complete the product.

This replaces the obsolete status table, which incorrectly continued to list features shipped in PR #5 as missing. The first-build PostgreSQL contract is implemented. The whole vision is **not ready for a real-clinic cutover**. Broby New is a live, authenticated deployment with synthetic data. Stripe sandbox checkout/refunds are deployed and verified; WhatsApp trial activation and an own-number join/reply exchange are verified; the provider setup screen still withholds the supplied template controls, and backend configuration remains pending. Lab feeds remain simulations. “Implemented” below describes the named capability in that agreed release scope, not a guarantee of clinical accuracy or an end-to-end production certification.

Current Doc-scope classification: **40 implemented, 16 partial, one lab test-mode
integration and one WhatsApp provider integration in progress** (58 total).
Real-clinic launch gates below are tracked separately from those counts.

## Every requested feature

| # | Requirement | Current state and remaining work |
|---|---|---|
| 1 | Patient identity; query production first | **Partial.** Stable clinic-scoped IDs, duplicate-name disambiguation and source-ID migration mapping. A V2-only converter prepares the original patient-table shape from a supplied export, and a separate consultation-text converter requires an explicit staff patient crosswalk. They preserve source IDs and unapproved history while refusing unresolved identities and linked media; both are synthetic-tested. The consultation-text path also passed hosted synthetic preview/Apply/replay, stale-review rejection, second-session staff readback and staff/owner browser checks on 25 September 2026. Actual approved V1 exports, owner reconciliation, media/entry history and production cutover have not happened. See V1_PATIENT_IMPORT_PREP.md and V1_CONSULTATION_IMPORT_PREP.md. |
| 2 | Owners and owner–patient links | **Implemented.** Primary/additional owners, edit/merge and normalized PostgreSQL links. Real V1 data reconciliation remains part of #1/#35. |
| 3 | Open patient events | **Implemented.** PostgreSQL JSONB events, dated timeline, novel event types without a schema migration, deduplicated ingest. PMS records now live in a separate PostgreSQL schema and project into the typed clinical tables. |
| 4 | Typed observations | **Implemented.** Number/text/boolean enforced in PostgreSQL; false is preserved; nonnumeric facts cannot receive numerical ranges. |
| 5 | AI-authored ontology | **Partial.** Model/manual proposals, aliases, reviewed acceptance/rejection and immutable codes/types/units. Approved clinical terminology and broader model evaluation remain; a real hosted AI proposal and rejection were verified with synthetic data. |
| 6 | Provenance / receipts | **Implemented with verification limits.** Original document/audio/human receipts, missing-source flags, verbatim AI quote validation, omitted source text and timestamps. This exposes mistakes; it does not certify speech or clinical interpretation accuracy. |
| 7 | Outbox | **Partial.** Durable drafts, edit/cancel/manual completion, simulated delivery callbacks and signed replay checks. A restricted Twilio trial worker, signed callbacks and conservative reconciliation are implemented. Provider configuration/delivery evidence and production customer dispatch remain unfinished. |
| 8 | One action layer for UI and AI | **Partial: shared executor implemented; full assistant coverage unfinished.** Shared authorized, versioned, idempotent audited mutations; AI proposals require confirmation. All 74 directly proposed operations now have strict schemas, reference checks, labelled reviews and atomic referenced-version guards. Twenty-seven complex/capture/provider operations route to their dedicated review screens; six internal test-adapter actions stay unadvertised. Exact selected recall batches and internal escalation acknowledgements now have complete recipient/source review, stale guards and explicit operator commands. Exact administrative commands additionally review a complete member read-restriction replacement or withdrawal of a pending organization request; effective access is pinned to current clinic/member versions and organization policy/account relationships. Owner-conversation acknowledgement, closure and exact staff reply require an explicit operator command and show the complete human conversation before confirmation; pending, closed and long conversations use the Handover screen. A reply is saved in the owner portal without external dispatch. Direct AI execution of the remaining guided workflows and representative intent evaluation remain unfinished. See ASSISTANT_OPERATIONS.md. |
| 9 | Read APIs | **Implemented.** Clinic-scoped patient search, paged timeline, observations, event detail and source access. Patient-page summaries now use five queries per page instead of five per patient. A 1,000-patient/eight-client isolated PostgreSQL workflow passed 19 checks with no HTTP errors; the unnecessary clinical refresh after dashboard writes was removed. A 5,000-patient/16-client burst also passed with zero HTTP errors. Removing redundant bootstrap JSON conversion cut standalone 5,000-patient reads from 1.08–1.28 seconds to 0.49–0.73 seconds and a matched mixed burst's bootstrap p95 from 9.20 to 4.17 seconds. Hidden tabs no longer poll the full snapshot every six seconds. Guarded single patient/owner changes now project incrementally; a real synthetic patient edit read back in 246.8 ms at 5,000 patients with 20/20 acceptance checks passing. After V2 revision `672b5cc` deployed, a separate small hosted synthetic create/update/readback retained the same owner link and revised name in both typed view and bootstrap. The uncompressed bootstrap remains 7.84 MB and first clinical projections took 20–27 seconds across disposable runs; older PMS screens still load full datasets, other clinical changes require full projection, and pagination and broader soak work remain. |
| 10 | Numbered voice notes | **Implemented.** Persistent notes, renaming, imported audio, independent capture lifecycle and replay. Real microphone/device/browser acceptance remains limited. |
| 11 | Offline first | **Partial.** Offline cold launch, encrypted account-scoped notes/audio/drafts/clinic copies, password unlock, bounded session access, legacy migration and snapshot eviction are implemented. Isolated production-browser acceptance verifies disconnected reopening, exact note/audio recovery and reconnect without changing unrelated records. Full physical-device/browser crash and storage-eviction acceptance remains. See OFFLINE_DEVICE.md. |
| 12 | Gap detection | **Implemented.** Contiguous upload manifests, checksums, immutable finalized audio, preserved local data on upload/storage failure. Physical device fault testing remains. |
| 13 | Handoff without stopping old device | **Partial.** Devices create independent notes; no remote stop or cursor-transfer action exists. A two-client API overlap test passes in SQLite and PostgreSQL. After PR #51 deployed, two independent signed-in V2 sessions saved separate synthetic WAV notes: the second finished while the first remained open, then the first finished with both original byte streams intact and completion replay deduplicated. An isolated and the deployed V2 browser showed the same-device return link while capture remained active. Simultaneous physical-device microphone and offline/reconnect handoff have not been tested. |
| 14 | Remove 10-second pass; ~25-minute refinement | **Implemented and hosted-verified with synthetic audio.** Automatic previews of complete 25-minute sections while recording, followed by strict final-audio verification and one transcript on Finish. Durable retries reuse decoded-byte/provider receipts; manual completed-note processing remains. Physical long-session/device acceptance remains. See CONTINUOUS_SPEECH.md. |
| 15 | Diarization flag | **Implemented.** Operator can turn speaker separation on/off. Speaker identifiers are scoped per window and must be reviewed before naming people. |
| 16 | Generate notes with receipts | **Implemented.** Verbatim local assembly or provider-selected exact excerpts, character receipts, omitted text review, optimistic-version protection and vet approval. Translation is not implemented; multilingual speech quality is not certified. |
| 17 | Medical vs medical+context retention | **Implemented for the named medical/context preference.** AI excerpt selection uses the saved setting, shows omissions and preserves original source records. Timed source deletion/legal holds are separate operational work; the document does not specify such a policy. |
| 18 | Patient timeline | **Implemented.** Dated, paged search/category filters, event details and receipt navigation. |
| 19 | Visual analytics | **Implemented for defined views.** Numeric trends with supplied reference bands, source navigation and saved count/group queries. Broader operational analytics and performance at clinic scale remain. |
| 20 | Bloods/cytology/X-ray/all views | **Implemented.** Category filters and typed findings; manual imaging records are allowed, automated radiology interpretation is removed. |
| 21 | Source-neutral flags | **Implemented.** Range comparisons apply to structured numbers regardless of original source. Missing receipts/ranges remain explicit. |
| 22 | Numbers/ranges/sources, not judgement | **Implemented.** Stored observations and supplied ranges, no inferred diagnoses/treatment or invented clinical ranges. Human/clinical acceptance is still required. |
| 23 | Patient AI chat | **Partial.** Factual retrieval, exact identity, date bounds and confirmed shared actions work. Private saved conversations, retry recovery and reload-safe confirmation are implemented. Explicit status, species, exact owner-linked patient and typed observation filters share their executor with saved views; local SQLite/PostgreSQL parity passed. Hosted real-model Cat/species and owner-linked patient questions passed on synthetic data; the latter saved view matched two linked pets, refreshed to one after a link change, and survived browser reload/unlock. Invalid model-produced read filters complete as a saved clarification without leaking a broader result; one unsupported owner/invoice question passed hosted readback. Saved owner-linked patient views survive a reviewed owner merge: local SQLite/PostgreSQL regression and hosted synthetic API/two-session/browser readback passed after PR #62. The server also refuses an owner-specific model read that drops or substitutes the named owner. Broader query composition, direct advanced-workflow proposals and representative clinical/language evaluation remain unfinished. All advertised mutation proposals are now strict; intent context is bounded without limiting deterministic query counts. |
| 24 | Clinic AI chat | **Partial.** Clinic-wide reads, counts, navigation and action proposals. Exact appointment clinician filtering/grouping passed local database tests and a hosted real-model question for a named synthetic-clinic vet; saved-view/API and browser readback matched. Patient-species filtering/grouping of appointments passed local SQLite/PostgreSQL tests and hosted model/API/browser acceptance on synthetic data. Exact owner-linked appointments pass local SQLite/PostgreSQL parity and hosted real-model/API/browser acceptance, including saved-view persistence after reload/unlock and one correct synthetic source receipt. Nine initial hosted synthetic phrasings and 13 later explicit phrasings mapped to the expected filters or safe clarifications. The ambiguous phrase “scheduled on” selected the date without a status filter; explicitly requesting “status equals scheduled” produced both. These examples do not establish representative model accuracy. Saved owner-linked appointment views resolve a reviewed owner merge in local SQLite/PostgreSQL tests; hosted merge acceptance covered patient views only. The saved-view/direct-query appointment join now batch-loads only referenced same-clinic patients; a 501-reference SQLite regression passed. The intent step now retrieves recent, exact and linked planning candidates instead of every clinic record, then fetches only the requested kind for the final factual read. It still loads clinic patient identities for name matching, and final query results are not database-paginated. A 5,000-patient disposable PostgreSQL assistant run passed complete counts; hosted large-clinic capacity and broad model accuracy remain unverified. Saved conversations are implemented; broader model evaluation and large-dataset limits remain. |
| 25 | AI drives dashboard | **Implemented for defined queries.** Assistant answers and saved views share validated filters, including low stock, outstanding balances, exact statuses/names/species/clinicians/owner links, clinic-local dates and typed observation values. Saved views retain filters, show matching receipts and refresh current records. Arbitrary joins/custom chart builders and clinic-scale performance remain unfinished. See ASSISTANT_QUERIES.md for acceptance and limits. |
| 26 | Clients / patients | **Implemented.** Create/edit/search, merge owners, stable identity, DOB and extra owner links. |
| 27 | Scheduling | **Partial.** Day/week/month, recurring/reschedule/status and room collision checks. A complete weekday editor, split shifts/breaks, dated leave/replacement hours and staff rota view are implemented, with conflict previews and atomic protection for existing bookings. Reviewed full-day leave requests, approval/rejection/withdrawal history and inclusive rota periods are now implemented with shared booking conflict protection. Clinic-specific cancellation/no-show/deposit behavior still needs an agreed policy. Payroll is not named in the Google Doc and is not counted as a blocker for this scheduling item. See STAFF_ROTA.md and RELEASE_WORK.md for acceptance. |
| 28 | Billing | **Partial.** Integer-cent invoices, explicit discount/tax, PDFs, external payment/refund records and voids. Credit-note issue/reversal, explicit net/tax credits, refund-due balances, printable notes and a CSV credit register are implemented and hosted-verified on synthetic records. A dated financial register, append-only void receipts, invoice-balance reconciliation and guarded CSV export are implemented. The implemented invoice/credit/register workflow is tested; clinic tax/accounting acceptance remains. Double-entry accounting and bank reconciliation are not explicitly named in this document and are not counted as missing invoicing features. See FINANCIAL_REGISTER.md. See CREDIT_NOTES.md. |
| 29 | Billing / payments | **Implemented for the current synthetic workflow.** Server-priced Stripe sandbox Checkout, signed callbacks, reconciliation and verified partial refunds passed hosted browser/provider checks. Real merchant activation/settlement, clinic billing policy and accounting reports remain. Credit-aware settlement passed hosted Stripe test-card payment and refund checks. |
| 30 | Inventory | **Implemented for current stock workflows.** Receiving lots/supplier/batch/expiry, remaining balances, FEFO, expired-stock rejection, reasoned stocktakes and purchase orders/partial receiving. Real stock-history migration is excluded. |
| 31 | Medication dispensing | **Implemented.** Atomic eligible-lot consumption with vet-supplied dose/frequency/instructions; no AI dose inference. |
| 32 | Staff | **Implemented for the listed account flows.** Nurse/vet/admin access, activation/revocation, manual single-use invitations, password change, TOTP and recovery codes. Account flows passed isolated tests and ten hosted synthetic checks, including invitation replay, MFA/recovery reuse, password/session revocation, migration replay/conflict and AI proposal review. Email delivery/reset is unfinished. |
| 33 | Reminders / recalls | **Partial.** Due dates, completion, scheduled preparation and reviewed recall campaigns are implemented. Campaign previews, selected recipient batches, progress, cancellation, opt-out history and stale-contact guards are tested. Duplicate/uncertain delivery is never automatically retried. Actual provider delivery, consent/templates, provider retry policies and bulk-load acceptance remain. See RECALL_CAMPAIGNS.md. |
| 34 | Reporting | **Implemented for the one-line Doc requirement.** Clinical and financial counts, net payments, credit registers, period reports, CSV export and handover are available. The full-record clinic overview includes patient/owner/species, consultation, appointment, reminder, message, stock and follow-up counts. SQLite/PostgreSQL tests and hosted V2 browser rendering, clinic scoping, period switching, JSON/CSV parity and a browser CSV download pass on synthetic records. The current-owner metric counts valid additional links and excludes merged or foreign owners in isolated tests; hosted JSON, CSV and browser readback matched 32/32 normal links. A 1,000-patient profile removed a 1.49-second owner-link join; a later 5,000-patient disposable run returned five standalone reports in 82.0–85.3 ms and passed a 16-client mixed workload without HTTP errors. The Doc specifies “Reporting” without a general-ledger or bank-settlement contract. Those extra accounting functions and acceptance with actual clinic data remain separate work; the isolated benchmark is not hosted capacity proof. See FINANCIAL_REGISTER.md and OPERATIONAL_REPORTS.md. |
| 35 | Migration tooling | **Partial.** Preview/digest/apply/replay, stable source IDs, conflict rejection, clinical JSON/CSV rehearsal, archives and isolated restore. Read-only V1 patient-table and consultation-text adapters are synthetic-tested in SQLite/PostgreSQL. Consultation preparation requires a reviewed per-visit patient crosswalk; existing V2 patient name/species/version and all referenced records invalidate stale previews before Apply. Private preview output, conflict rejection and replay pass. Hosted synthetic consultation-text preview/Apply/replay, stale-review rejection, second-session staff readback and staff/owner browser checks passed on 25 September 2026. Actual V1 export acceptance, consultation media/entries, financial/stock history, binaries, owner reconciliation and cutover/rollback rehearsal remain. See V1_PATIENT_IMPORT_PREP.md and V1_CONSULTATION_IMPORT_PREP.md. |
| 36 | Labs / analysers | **Test mode only.** Manual CSV and signed synthetic lab delivery enter real typed records with deduplication/receipts. Vendor selection, mappings/units, device access and real feed acceptance remain. |
| 37 | Owner claim without signup wall | **Implemented for first-tap access without signup.** Revocable clinic links and 90-day saved browser access work. This is capability-based access; a separate verified cross-device owner account is not implemented. |
| 38 | Pet profiles | **Implemented for shared access.** Approved shared profile and saved multi-pet browser access. Verified owner/household account management is unfinished. |
| 39 | Record vault | **Implemented for shared access.** Approved notes/files/labs; unapproved clinical facts hidden. Verified-account limitation from #37 applies. |
| 40 | Discharge and medication instructions | **Implemented.** Approved care/PDF and recorded dose/frequency/instructions. No invented or translated treatment instructions. |
| 41 | Upcoming/due care | **Implemented.** Shared due reminders ordered by date. External notification delivery is #33/#45. |
| 42 | Vet audio playback | **Implemented.** Explicit audio approval, revocable access and byte-range playback/seek. |
| 43 | Share / grant to a new clinic | **Partial.** Reviewed transfers copy approved events/files, opt-in original audio and medication history. Origin mapping skips repeats and appends reviewed changes. Pre-revision imports can establish a reviewed current-source baseline. A first transfer can now link to an independently created receiving patient after explicit identity/all-owner/history review, duplicate-risk acknowledgement and a recorded reason; local records remain intact. Isolated browser/PostgreSQL acceptance passed. Established mappings can now be corrected after fresh explicit owner consent, full old/new identity and history review, two acknowledgements and a reason. Local PostgreSQL browser acceptance rejected a stale additional-owner review, then preserved all 14 reviewed records and exact original file bytes while applying the corrected mapping. Both patient timelines retain unresolved clinical-history notices. Verified owner identity and clinical-fact reconciliation remain; historical equivalence cannot be reconstructed. See CLINIC_TRANSFERS.md. |
| 44 | Pre-consult forms | **Implemented.** Submit/edit, duplicate protection, internal urgent flag and accepted intake source receipts. This is not an emergency monitoring service. |
| 45 | WhatsApp BSP / Meta | **Provider integration in progress.** User authorized controlled tests to their own number. Twilio free trial and WhatsApp sandbox are activated after explicit legal approval. A restricted adapter now supports durable trial sends, signed callbacks, canonical delivery reconciliation and an isolated inbound inbox. The authorized own-number join was received and Twilio’s automatic reply arrived. Twilio’s setup screen still shows Link your device and does not expose the required template/webhook controls. The documented Content API also returns HTTP 401 / Twilio 20003, stating that this feature is unavailable on a trial account. No ContentSid was returned. Backend configuration and Broby-originated delivery tests remain pending; V1 WhatsApp is untouched. |
| 46 | Rich discharge / referral media | **Partial.** Shareable approved PDFs/files/audio in the portal. Automatic provider media delivery and receipt tracking remain. |
| 47 | After-hours AI bot | **Partial — portal workflow implemented.** Persisted owner conversations, optional AI intent selection, exact approved-care quotations, failure recovery and staff replies are implemented. The model cannot author treatment advice. WhatsApp conversation routing and delivery remain blocked on the enabled provider channel; verified household identity is separate. See OWNER_CONVERSATIONS.md. |
| 48 | Emergency escalation | **Partial.** Urgent questions and expired clinic-defined acknowledgement targets create one internal alert, with review/closure history and interrupted-worker recovery. On-call alert delivery, a staffed fallback and real response acceptance require an enabled provider and clinic escalation policy. No emergency monitoring is claimed. |
| 49 | Morning handover | **Implemented for portal conversations.** Live shift queue and immutable daily handover snapshots now include exact owner/clinic conversation text and message receipts alongside intakes, appointments, drafts and unfinished work. WhatsApp history and real staffed acceptance remain dependent on #45/#47/#48. |
| 50 | Master multi-clinic account | **Implemented for provisioning and reviewed adoption.** Master provisions clinics and sets inherited restrictions. Existing independent clinics can request adoption after explicit access/policy review; the master separately accepts, with stale-consent, expiry, rollback and membership guards. Existing records and identities remain unchanged. Full two-account browser acceptance used isolated synthetic clinics; hosted existing clinics were not reassigned. Detach/ownership transfer and real clinic adoption acceptance remain. See ORGANIZATION_ADOPTION.md. |
| 51 | Multi-clinic membership | **Implemented.** Credential-to-active-membership checks and clinic switching. |
| 52 | Roles including nurse | **Implemented.** Server-side authorization and active-membership checks. |
| 53 | Feature permissions / master locks | **Implemented with explicit offline limits.** Shared-action and read restrictions, inherited master locks, individual member controls, guarded routes/downloads/AI history and filtered bootstrap are implemented. Mixed histories/files/archives require all read areas; browser views clear after the next successful permission refresh. Offline access expires within 12 hours and downloaded files cannot be recalled. See READ_ACCESS.md for acceptance. |
| 54 | Remove radiology/differential | **Implemented in V2.** No autonomous radiology or differential agent. V1 has not been altered. |
| 55 | Remove general_knowledge | **Implemented in V2.** Factual retrieval only; no general clinical advice tool. |
| 56 | Remove old prompts/corrector | **Implemented in V2.** New receipt-backed assembly, no medical corrector. |
| 57 | Remove 10-second live chunk pipeline | **Implemented in V2.** Five-second browser chunks are durability/upload pieces, not ten-second AI passes. |
| 58 | Remove duplicate action executors | **Implemented in V2.** UI and assistant proposals use the shared authorization/mutation boundary. |

## Administrative and operational review verification — 25 September

The next integration batch passes **1,026 backend tests in SQLite PMS mode and
1,026 in PostgreSQL PMS mode**, with one expected skip in each and a real
PostgreSQL clinical spine. All **41 frontend tests**, TypeScript, production build
and offline packaging pass. These counts describe local revision `37d3203`;
release deployment is recorded separately after required CI.

The primary operator personally reviewed and confirmed both synthetic
administrative proposals in the local password-authenticated browser. A separate
login passed **18 readbacks**: exact restriction only, inherited inventory lock
retained, stale organization-policy proposal unexecuted, exact consent history
preserved, independent clinic unchanged, and both completed confirmations replayed
without a second mutation. The local model was fixed for this fixture; this is
not hosted real-model acceptance. The hosted service fixture requires verified
V2 service execution, which the currently configured Railway CLI account cannot
access. The API-only fallback covers a new synthetic child clinic's restrictions
without changing existing organization policy or clinic ownership.

A separate local PostgreSQL/browser/API/worker fixture produced six actual
loopback HTTP 503 receipts. The primary operator reviewed a retry, which preserved
the original event ID and recorded HTTP 204 on attempt seven, then separately
acknowledged the still-open incident and retried its failed synthetic document.
The job completed; the independent monitor recorded a distinct sequence-2
recovery event accepted with HTTP 204. **11 independent saved-state checks**
confirmed job completion, preserved receipts, two audited reviews, separate
acknowledgement/recovery and matching external worker storage. No hosted webhook,
real on-call destination or clinical emergency service was enabled. See
[OPERATIONAL_ALERTS.md](OPERATIONAL_ALERTS.md).

## Completion release verified — 25 September

The isolated integration branch passes **944 backend tests in SQLite PMS mode
and 944 in PostgreSQL PMS mode** (one expected skip in each), with a real
PostgreSQL clinical spine. All **41 frontend tests**, TypeScript, the production
web build and offline packaging pass. These are local results. PR #82 subsequently passed every SQLite, PostgreSQL,
frontend and packaged-API CI check before merge.

Both isolated Railway services reported SUCCESS at exact revision
`cc32980a69ce24dc43a1dc29624371ca735164e7`. The existing persisted-state check
passed **17/17**. A fresh synthetic workflow passed **30 checks**, including new
verbatim and real-Anthropic source-excerpt jobs, PDF/file/lab receipts, owner
access exclusions and revoked-link rejection. Chrome displayed the new saved
source excerpts and omitted-source text. Hosted document/schedule/payment worker
cycles progressed in embedded mode; the messaging worker remained disabled.

Two real-model assistant reviews were confirmed in Chrome: exactly two manual
recall drafts and one internal escalation acknowledgement. Saved reviews, exact
draft text, idempotent confirmation receipts and unchanged open owner conversation
passed API readback. The unsent drafts were cancelled and synthetic owner link
revoked. No external message was sent.

Hosted mapping-correction acceptance used two newly created SYNTHETIC clinics.
The owner browser explicitly selected medication history, original audio and
permission to correct the earlier patient link. The staff browser displayed both
identities, all owners and native facts; after a controlled additional-owner edit,
its stale confirmation was rejected. Reload cleared the reason and both
acknowledgements. Fresh browser confirmation passed **43 stored-state readback
checks**, including unchanged prior records, exact file/audio bytes, native
PostgreSQL events/observations/receipts, exact new destination copies, immutable
review fingerprints, no stock movement, and a deduplicated repeat. Both patient
screens showed unresolved-history warnings, retained while filtering. This does
not establish legal owner identity or resolve clinical-fact equivalence.

New coverage includes reviewed recall preparation and internal escalation
acknowledgement; explicitly consented correction of existing receiving-patient
mappings; independent worker process interruption and recovery with exactly one
final document commit; and batched native clinical receipts. A 405-event fixture
with 810 observations and 405 sources uses six SELECTs with exact receipt parity;
a paged timeline uses five including authorization. This does not paginate the
legacy full bootstrap or certify hosted clinic-scale capacity.

A reusable real-model administrative question corpus passed 24/24 exact outcomes
on clearly synthetic records at deployed PR #80 revision `48bbb0c`. Expected
filters, identities and counts came from an independent complete snapshot;
business records were unchanged. This is English administrative intent evidence,
not clinical-language or general model certification.

The public legal pages now display the V2 synthetic-preview restrictions before
the unchanged reference copy, including the absence of verified automatic
90-day audio deletion. Legal approval and a retention implementation/rehearsal
remain open; the banner does not resolve those launch gates. The V2 Twilio
Content API was freshly probed on 25 September at 13:43 UTC: HTTP 401, provider
code 20003, no template ID and trial-feature restriction. Customer dispatch
remains disabled.

## Blockers versus unfinished engineering

### 25 September V2-only assistant acceptance

PRs #72–#74 strengthened the partial patient and clinic assistant items (#23–24)
without changing their classification. An explicit recorded status or species
cannot be omitted or substituted by a model-produced factual query. A single
explicit `on YYYY-MM-DD` request has exact day bounds; invalid, conflicting or
multiple ISO dates clarify without records. Relative clinic periods reject
conflicting model dates. Patient chat cannot silently switch from the selected
animal to a different animal or the whole clinic; an explicit whole-clinic
request cannot be narrowed back to one patient by the model.

All three PRs passed frontend, SQLite, PostgreSQL and packaged API CI. At V2
revision `a11ec5785e0a9d879080fb6135d5e64113ab83b7`, both isolated Railway
services reported SUCCESS, the persisted-state smoke passed 17/17 checks, and
real-model synthetic questions returned the exact requested status, species,
calendar day, selected patient and explicit whole-clinic scopes. An invalid
day returned no records or action. These are specific prompt and fixture checks,
not a representative model or clinical-language certification. Exact evidence
is in ASSISTANT_QUERIES.md and ignored private test receipts.

The V2 Twilio trial's Content API was read again on 25 September: HTTP 401,
provider code 20003, with no template ID. Customer dispatch remains disabled.
The native WhatsApp app cannot show whether this Twilio account has upgraded.
Read-only inspection of the original Broby repository found terminology files
but no approved patient/consultation export. No original Broby files or service
were changed.

PR #76 moved owner-conversation acknowledgement and closure from guided
navigation to strict reviewed assistant proposals, increasing direct coverage
from 67 to 69 actions and leaving 30 guided. The request must contain the exact
thread ID and verbatim reason; the model sees only thread selection metadata,
while the deterministic staff review displays the exact human conversation.
Pending, closed, stale and more-than-20-message threads remain protected. Full
frontend, SQLite, PostgreSQL and packaged API CI passed. At isolated V2 revision
`20a186c965517accf23bc6fef4f088cefda0c896`, both Railway services reported
SUCCESS. A hosted real-model synthetic closure proposed the exact action and
reason; review left the thread unchanged, confirmation closed it, replay returned
the same receipt, and a new-login readback retained the review/result, resolved
one internal alert and rejected the revoked test owner link. No customer message
was sent; Twilio sending remained disabled. The standard hosted readback passed
17/17 checks. This narrows #8/#23/#24 but does not establish general model
accuracy or real-clinic readiness.

PR #78 added the owner-visible staff reply to the same reviewed assistant path,
bringing direct proposals to 70 and guided operations to 29. Its frontend,
SQLite, PostgreSQL and packaged API CI passed. The first hosted model attempt
selected the right action but substituted a field, so the server rejected the
proposal without saving a reply. A follow-up V2 main commit
`dab49ead6fda8f73819a74c4ae21bc1201ff0f48` made the exact operator command,
not model-provided fields, authoritative for conversation target, reason and
reply text. This commit was pushed directly to V2 main in error; the original
Broby repository and services were untouched. The exact commit's [push CI](https://github.com/NeoDiuZ/broby-v2/actions/runs/36135737075)
then passed all three jobs, and both isolated V2 Railway services reported
SUCCESS at that SHA. A fresh hosted real-model synthetic test passed exact
reply review, owner-portal visibility, unchanged urgent alert, no external
message, confirmation/replay, closure and new-login readback with one timeline
receipt per human message. A separate deployed-browser test displayed the
exact owner message and staff reply before confirmation, then confirmed one
portal reply; API readback matched and its synthetic grant was revoked. The
standard hosted smoke passed 17/17 at this revision. These are synthetic
examples, not representative clinical-language or real-customer acceptance.

PR #80 narrowed the assistant planning read without bounding deterministic
answers. At merged V2 revision `48bbb0c60907dd094fd9f7247bde2129d870c652`, full
frontend, SQLite, PostgreSQL and packaged API CI passed, and both isolated
Railway services reported SUCCESS at that exact SHA. A disposable PostgreSQL
run with 5,000 added patients, 16 concurrent clients and 16,305 clinic
planning records passed 21 checks. Only 250 records went to the model planner;
complete assistant answers counted one old patient's appointment, 5,004 Cat
patients and 500 appointments for an exact clinician. The three local
server-side intent/answer timings were 1,686.7, 682.1 and 592.3 ms before
model latency. At the deployed V2 URL, a fresh synthetic fixture passed one
preparation, 15 real-model answer/saved-view checks and four refresh checks.
The browser opened the exact 6.2 mmol/L synthetic observation and original
source receipt, then showed its one-result saved view after reload and device
unlock. Customer sending remained disabled. This is bounded synthetic
acceptance, not a real-clinic capacity or clinical-language certification.

**Engineering that can continue without a new vendor:** offline physical-device/crash acceptance; long-session physical-device acceptance; verified owner account flows (delivery channel needed for final verification); clinical-fact reconciliation after reviewed mapping correction; shared object storage and hosted worker separation; full bootstrap pagination and broader load/soak testing; external alerts and incident response; direct advanced assistant workflows, broader custom reports and test coverage. The completion release adds all-advertised-action strict contracts and a real process-loss/complete-row restore rehearsal; see RELIABILITY_ACCEPTANCE.md. These are unfinished work, not things an AI agent is inherently unable to build.

**External inputs for final acceptance:** live merchant activation and lab vendor/test access; Twilio provision of a usable trial template/webhook setup (or an explicitly approved upgraded sender), then production sender enrollment; approved V1 export; clinic sign-off on the proposed billing, retention and escalation policy in CLINIC_LAUNCH_POLICY_DRAFT.md; representative recordings and physical devices. Test adapters cannot prove payment settlement, analyser compatibility, emergency response or customer message delivery.

**Release restrictions still in force:** synthetic data only, no V1 cutover and no real money movement. Controlled WhatsApp tests to the user’s own number are authorized; customer sending is not enabled. The hosted invitation/MFA/recovery and migration checks have now passed.

## Railway / Redis explanation

Broby New contains **Frontend, Backend and Postgres**, all in Singapore, under **cxlabyky's Projects**. Frontend is public HTTPS; the API and database use private routing. Backend has a persistent `/data` volume. Deployments track this repository's `main` branch. PostgreSQL now contains both the normalized clinical spine and the PMS/account/session/job schema. `/data` contains audio/uploads, the frozen legacy SQLite file and its pre-cutover backup. Preserve PostgreSQL and the file volume together; the old SQLite file is no longer an active writer.

V1's `Redis-Ky2t` supports transient auth tickets, request limits, coordination locks, caches and live-event pub/sub. V2 does not call Redis: its current sessions, rate limits and job claims use its database, and the browser polls for updates. Therefore absence of Redis is **not a missing connection causing current V2 workflows to fail**. Creating an unused Redis service would not add these features or make V2 scalable.

Administrator worker/queue diagnostics and bounded loop recovery are implemented (see OPERATIONS_HEALTH.md). They distinguish current process progress, failed tasks and provider-disabled workers, with durable sanitized failure/recovery history. A guarded standalone worker process is implemented and process-loss tested on a shared POSIX volume, with database ownership, durable heartbeat and backup exclusion. Hosted separate-worker deployment, shared object storage, external alerts and incident acknowledgement remain unfinished.

The architectural limit is one backend replica with local persistent files, embedded worker loops (with an optional tested same-host standalone worker) and a serialized PMS writer. The SQLite-to-PostgreSQL migration is complete. Generic PMS records still project into typed clinical tables in the same database. A bounded local load/crash/restore rehearsal has passed. Externalizing files and separating workers/observability, with larger load/soak and cloud failure testing, must precede a multi-replica claim. Redis may then be useful for shared ephemeral coordination/pub-sub if the chosen worker design needs it. Never point V2 at V1 Redis, because that would share sessions/locks/events across environments.

Only the required Deepgram/Anthropic provider keys were reused in the original setup, with real synthetic provider requests verified; no V1 database, Redis, JWT or messaging credentials were copied into use. Shared provider keys also share quota/billing.

## Verification records

- [First-build contracts](FIRST_BUILD.md), [clinic workflows](CLINIC_WORKFLOWS_TESTING.md), [advanced workflows](HARD_WORKFLOWS_TESTING.md).
- [Speech windows and this audit release](SPEECH_WINDOWS_TESTING.md).
- [Deployment and storage boundaries](DEPLOYMENT.md).

A service marked SUCCESS or an HTTP 200 is evidence of deployment/health only. Clinical correctness, external delivery, settlement, physical-device behavior and full disaster recovery require their own evidence.

## Latest verified delivery and audit scope

PR #33 implemented read restrictions; PR #34 implemented persistent owner
conversations, replies, internal escalation, handovers and patient-timeline
receipts. PR #35 added PostgreSQL PMS storage and the guarded all-table cutover.
The hosted switch and persistence checks are recorded in RELEASE_WORK.md.

This audit distinguishes literal requirements from extra product scope. A feature
is not marked missing solely because payroll, double-entry accounts, household
identity, arbitrary joins or timed deletion were not added. Conversely, a working
subset does not establish full AI operation coverage, real WhatsApp delivery,
real analyser compatibility or a clinic migration. The remaining engineering
listed above is buildable work; it is not an external dependency or lack of user
permission. No requirement is certified by a green deployment alone.
