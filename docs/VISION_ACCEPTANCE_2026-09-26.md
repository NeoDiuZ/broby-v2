# Full 58-item vision acceptance — 26 September 2026

**Broby V2 is not ready for a real-clinic launch.** Both source tabs were read;
THE VISION is the scope and FIRST BUILD is only an earlier milestone.
This report distinguishes deployed software, synthetic tests, real-provider
sandbox evidence, physical-device evidence and clinic acceptance.

“Complete” below means the named deterministic software capability is implemented
and verified in the isolated V2 scope, with no feature-specific engineering gap
identified. It does **not** approve real-clinic use. “Partial” means the capability
exists but engineering or required acceptance remains. “Blocked” identifies a
required external integration for which a real end-to-end path cannot currently
be demonstrated. No row has a recorded real-clinic acceptance sign-off.

Both Railway V2 services were verified at application release `71ba6d996b70f15144810044981189b7b5668303` (PR #85). Subsequent changes in this acceptance update add only a read-only verification helper, its tests and documentation; they do not change application behavior. The final delivery message records the exact deployed acceptance revision. The detailed implementation history remains in
[FEATURE_STATUS.md](FEATURE_STATUS.md); clinic decisions remain
[PROPOSED](CLINIC_LAUNCH_POLICY_DRAFT.md).

| # | Requirement | Status | Evidence and its limit | Exact remaining work | Human input needed |
|---|---|---|---|---|---|
| 1 | Patient identity | Partial | Stable scoped IDs; export/crosswalk converters; hosted synthetic import and replay | Reconcile actual patient/owner identities, full history and cutover | Approved V1 export, explicit migration scope, staff crosswalk and approver |
| 2 | Owners and patient links | Complete | Normalized PostgreSQL links; primary/additional owners, merges and scoped readback | Actual-data reconciliation belongs to #1/#35 | Migration owner for actual records |
| 3 | Patient events | Complete | Open JSONB events, deduplicated ingest and hosted persisted timeline | Clinic acceptance of actual event sources | Clinical reviewer |
| 4 | Typed observations | Complete | Database type enforcement, false values, ranges and source parity tests | Real feed/clinical terminology acceptance belongs to #5/#36 | Clinical reviewer and lab vendor |
| 5 | AI-authored ontology | Partial | Real-model synthetic proposal/rejection; guarded code/type/unit review | Approved terminology and representative model evaluation | Clinician-approved concepts, aliases and evaluation cases |
| 6 | Provenance and receipts | Complete | Original source/audio/file receipts, verbatim excerpts, missing/omitted source flags | Representative clinical accuracy acceptance; receipts do not certify interpretation | Approved recordings/documents and clinician |
| 7 | Outbox | Partial | Durable manual drafts, cancellation, simulated callbacks and restricted trial adapter | Actual V2 provider send, callback, delivery and uncertain-send acceptance | Usable sender/templates/webhook and own-number test destination |
| 8 | Shared UI/AI actions | Partial | Shared authorized executor; 74 strict direct actions, 28 guided operations and six internal adapters; exact reviewed recall/admin actions; saved section-specific guides | Remaining representative guided-workflow and broader intent acceptance | Representative staff workflows and reviewer |
| 9 | Read APIs | Complete | Scoped search and paged native APIs; batched receipts; isolated load tests. Reconciliation disables the unchanged shortcut deployment-wide, including hosted V2 | Whole-workspace pagination needs dependency/media-integrity indexing and offline-scope design; hosted load/soak acceptance remains | Agreed clinic-size/latency target for capacity acceptance |
| 10 | Numbered voice notes | Partial | Persistent numbered notes, imported audio, independent capture/replay | Physical microphone, crash and long-session acceptance | Target devices/browsers and approved synthetic recording session |
| 11 | Offline capture | Partial | Encrypted scoped device data; browser disconnect/reopen/reconnect acceptance | Physical crash, eviction, quota and recovery acceptance | Target physical devices and agreed recovery scenarios |
| 12 | Gap detection | Partial | Manifest/checksum enforcement; exact original bytes retained on failure | Physical interruption and storage-fault acceptance | Target devices and controlled fault session |
| 13 | Independent device handoff | Partial | Two hosted sessions retain exact overlapping synthetic notes; old capture not stopped | Simultaneous physical microphones and offline/reconnect test | Two target devices and operator |
| 14 | 25-minute refinement | Partial | Hosted synthetic sections, final manifest, deduplicated provider receipts | Real long-session capture/background/reconnect acceptance | Approved representative recording and target device |
| 15 | Diarization flag | Complete | Saved on/off flag reaches provider; speaker labels remain window-scoped | Representative speaker/language quality acceptance | Approved multivoice samples and clinician |
| 16 | Notes with receipts | Partial | Verbatim assembly/provider-selected excerpts, omissions and vet approval | Representative clinical/language accuracy and usefulness evaluation | Approved samples, clinician and acceptance criteria |
| 17 | Medical/context retention | Partial | Saved preference controls excerpts; originals retained; public preview notice | Reconcile legal promise; implement/test any approved timed deletion, holds and backup expiry | Approved per-class retention schedule, legal hold owner and V2 notice |
| 18 | Patient timeline | Complete | Paged dates/categories/search, source navigation and stored readback | Real-clinic workflow acceptance | Clinical reviewer |
| 19 | Visual analytics | Complete | Hosted assistant and saved numeric trends; exact code/unit/date/point receipts, zero and missing ranges; source navigation and reload parity | Agreed-workload and real-clinic usability acceptance | Clinical reviewer and representative workload |
| 20 | Category views | Complete | Bloods/cytology/imaging/all filters; manual imaging, no autonomous interpretation | Actual data acceptance through source integration | Clinical reviewer and sample files |
| 21 | Source-neutral flags | Complete | Structured numeric comparison across source types; missing ranges explicit | Actual unit/range mapping belongs to #36 | Vendor units/ranges and clinical reviewer |
| 22 | Numbers/ranges/sources | Complete | Deterministic flag values and receipts; no inferred diagnosis/dose | Clinical acceptance of supplied mappings | Clinical reviewer |
| 23 | Patient AI chat | Partial | Saved private chat; exact owner/medication/record/literal-event reads and numeric trends; quoted data cannot alter intent; 24/24 plus four exact hosted real-model cases | Broader factual composition, guided workflow acceptance and clinical-language evaluation | Representative questions/samples and clinician |
| 24 | Clinic AI chat | Partial | Exact species/status/date/owner/clinician queries; isolated 5,000-patient tests | Broader queries, representative model accuracy, hosted load/soak acceptance | Workload/latency target and representative clinic questions |
| 25 | AI-driven dashboard | Complete | Confirmed saved queries share deterministic executor; hosted count and numeric-chart filter/point/source parity after browser save, refresh and reload | Broader query composition follows #23/#24 | Report/workflow reviewer |
| 26 | Clients and patients | Complete | CRUD, owner links, merge/disambiguation and version guards | Actual-data onboarding/reconciliation follows #1/#35 | Approved export and staff reviewer |
| 27 | Scheduling | Partial | Conflict guards, clinician rota/leave, hosted synthetic booking readback | Configure/test approved cancellation/no-show/deposit treatment | Timezone, hours, rules, exemptions and approval |
| 28 | Invoicing and billing | Partial | Deterministic charges, credit receipts, PDF/register/balance parity | Approved tax/rounding/credit/refund examples and accounting acceptance | Legal entity/currency, accountant, approved rules/examples |
| 29 | Payments | Partial | Real Stripe sandbox checkout/refunds and signed receipt reconciliation | Approved live merchant activation, settlement/refund and reconciliation acceptance | Approved merchant and specifically authorized live test scope |
| 30 | Inventory | Complete | Lots, FEFO, expiry, stocktakes, purchase orders and partial receipt; concurrency tests | Real stock-history migration and operational acceptance | Approved stock export and stock controller |
| 31 | Dispensing | Complete | Atomic eligible-lot consumption and vet-supplied instructions; no inferred dose | Actual workflow/label acceptance | Vet and approved medication examples |
| 32 | Staff management | Partial | Memberships, roles, invites, password, TOTP/recovery and session revocation | Real staff onboarding and recovery acceptance; select delivery channel if emailed invitations are required | Approved staff roster, delivery channel and account owner |
| 33 | Reminders and recalls | Partial | Scheduled/manual preparation; reviewed recipient batches, opt-out/stale checks | Consent/templates, real delivery/retry and bulk-load acceptance | Approved consent/quiet-hours/retry policy and enabled sender |
| 34 | Reporting | Complete | Operational/financial reports, CSV/browser parity and isolated scale checks | Actual clinic/accountant acceptance; no general-ledger claim | Required report examples and accountant |
| 35 | Migration tooling | Partial | Preview/digest/apply/replay, converters, archives and isolated restore | Full actual history/media/balances/stock, reconciliation and rollback rehearsal | Approved export/binaries/crosswalk, explicit scope and cutover approver |
| 36 | Lab/analyser integration | Blocked | Manual CSV and signed synthetic feed only | Vendor adapter/mapping, units, exact identity, error/duplicate and real feed acceptance | Selected vendor, protocol/specification, sandbox/device access and sample feed |
| 37 | First-tap owner claim | Partial | Revocable capability links and saved browser access without signup | Real-clinic identity/recovery acceptance; verified cross-device accounts are additional product work if required | Approved identity/recovery policy and verification channel |
| 38 | Pet profiles | Partial | Approved profile and saved multipet capability access | Real household authority acceptance; any cross-device account requirement follows #37 | Owner identity/household policy |
| 39 | Record vault | Partial | Approved notes/files/labs; private facts excluded | Owner-authority acceptance and actual migrated visits/media; first-tap capability access is implemented | Identity policy and approved migration inputs |
| 40 | Discharge and medication instructions | Complete | Approved care/PDF, exact recorded name/dose/frequency/instructions | Representative clinician/owner acceptance; external send is #46 | Approved discharge examples and reviewer |
| 41 | Due care | Complete | Approved shared reminders ordered by due date | External notification acceptance is #33/#45 | Consent/templates and enabled sender |
| 42 | Vet audio playback | Partial | Explicit approval, revocation and byte-range seek; hosted synthetic bytes | Physical owner-device playback and representative explanation acceptance | Target devices and approved audio |
| 43 | Record sharing to another clinic | Partial | Consented mapping corrections; immutable per-record dispositions; held current care/AI/media/exports and onward-copy qualification; hosted browser plus 25 readbacks | Verified owner identity, unresolved legacy/derivative lineage, separate receiving-clinic reconciliation and a proven hold-release contract | Both clinic reviewers, verified owner authority and actual reconciliation cases |
| 44 | Pre-consult forms | Complete | Submit/edit, duplicate guards, source receipts and internal urgent flag | Staff workflow acceptance; not an emergency service | Clinic-approved form and emergency wording |
| 45 | WhatsApp BSP/Meta | Blocked | Trial join/automatic reply historical evidence; fresh Content API 401/20003, no template | Usable sender/templates/webhook, Broby-originated own-number delivery, production enrollment | Enabled authorized V2 provider account/sender and approved templates |
| 46 | Rich discharge/referral media | Partial | Approved PDFs/files/audio available in portal | Real provider media send/delivery receipts | Enabled sender, media/template approval and own-number target |
| 47 | After-hours bot | Partial | Persisted portal questions, approved-care quotations, staff replies and failure recovery | Verified owner/channel routing, actual WhatsApp delivery and staffed acceptance | Enabled channel, identity policy, coverage/emergency wording and staff |
| 48 | Emergency escalation | Partial | Reviewed named primary/backup policy, durable external incident dispatcher, acknowledgement/deadlines/fallback; root local browser and real loopback HTTP drill; hosted transport verified disabled | Approved HTTPS receiver deployment, independent supervision, actual named staff receipt and response drill; receiver acceptance is not clinical response | Primary/backup staff, recipient authority, private receiver routes, deadlines, fallback and drill participants |
| 49 | Morning handover | Partial | Immutable daily portal snapshots with exact conversation/source receipts | Actual WhatsApp history and staffed handover acceptance | Enabled channel and named handover reviewers |
| 50 | Master multi-clinic account | Partial | Provisioning, inherited restrictions, two-party reviewed adoption | Real organization authority, clinic adoption and inherited-access acceptance | Organization authority and approved ownership-transfer policy |
| 51 | Multi-clinic membership | Complete | Credential-to-active-membership checks and switching isolation | Actual clinic membership onboarding acceptance | Approved organization/staff membership roster |
| 52 | Nurse/vet/admin roles | Complete | Server-enforced roles and active memberships; negative authorization tests | Actual role assignment acceptance | Approved staff roles |
| 53 | Feature permissions/master locks | Complete | Shared read/write restrictions, inherited locks and guarded downloads/history | Offline revocation bound remains ≤12 hours; downloaded files cannot be recalled | Clinic acceptance of offline/download policy |
| 54 | Remove radiology/differentials | Complete | V2 code contains no autonomous radiology/differential agent | None in V2; V1 deliberately unchanged | None |
| 55 | Remove general knowledge | Complete | Factual tools only; unsupported clinical advice returns no records/action | Continue clinical-language regression evaluation | Clinical reviewer for broader corpus |
| 56 | Remove old prompt/corrector chain | Complete | New receipt-backed assembly; no medical-corrector pipeline | None in V2; source receipts/quality gates still apply | None |
| 57 | Remove ten-second AI pass | Complete | Five-second pieces are durable upload chunks; refinement uses long sections | Physical long-session acceptance tracked in #14 | Target devices/samples |
| 58 | Remove duplicate executors | Complete | UI and assistant mutations share authorization, versions, idempotency and audit | Direct assistant coverage still partial under #8 | Workflow reviewer |

Operational gates apply across the table: matched PostgreSQL/file cloud restore,
shared storage before independent Railway workers or multiple replicas,
external operational alerts and a staffed incident drill, full-bootstrap scaling design, and hosted load/soak acceptance. A same-host worker test or an
isolated database restore does not prove these cloud boundaries.


## Verified release evidence

- [PR #85](https://github.com/NeoDiuZ/broby-v2/pull/85) merged as `71ba6d996b70f15144810044981189b7b5668303`. Backend deployment `81617411-04dc-4d35-8ad1-66f0225a731a` and frontend deployment `9f194f8d-4d7e-4504-9cfa-751f41c65bff` both reported SUCCESS for that exact SHA in the verified Broby New project. Local full suites passed **1,332 tests plus one expected skip in each SQLite/PostgreSQL mode**, with a real PostgreSQL spine; **62 frontend tests**, type checking, production build and offline packaging passed. All six push/PR CI jobs passed, including packaged API checks. Root reviewed the integration; independent reviewers verified adversarial parser, chart and clinical-notification cases. CodeRabbit skipped automated review.
- On that deployment, **24/24** administrative real-model intent cases and **four additional exact-read/chart cases** passed without changing business records. Root opened the exact zero-valued measurement and its original synthetic source in the browser, saved the chart, then verified Reports selection, refresh and full reload/unlock retained the three exact measurements and supplied ranges. No inferred range, converted unit or clinical interpretation was accepted.
- Six saved real-model guides retained their exact review destination without an action or execution. Root clicked every saved guide: migration preview opened Data & migration; trial send and provider reconciliation opened Integrations; operational retry opened Sync & jobs; schedule and organization policy opened Clinic. This verifies routing, not provider dispatch or organization approval. The selected synthetic clinic has no organization policy authority; existing reviewed administration acceptance remains separate. Stored chart/source/guide readback passed **16 checks**.
- All **14 existing hosted feature groups**, **17 release-persistence checks** and **seven hosted worker/disabled-operational-transport checks** passed again on PR #85. These read back stored synthetic workflows; they do not establish real-device recording, customer delivery or bank settlement.
- Clinical escalation local acceptance used disposable PostgreSQL, a real loopback HTTP receiver and a separate dispatcher. Root reviewed the named primary/backup policy in the browser, verified old questions did not send, created a new marked synthetic question, observed primary then backup receiver acceptance without acknowledgement, and observed manual fallback after both deadlines. Root then signed in as the named backup nurse, opened the exact question and recorded an explicit acknowledgement. Independent readbacks passed 5 send/baseline, 8 fallback and 11 acknowledged-state checks. Notification payloads contained opaque incident references only. All fixture processes were stopped; unrelated shared test databases were preserved. This is not proof of actual on-call staff delivery or an emergency service.
- The hosted clinical-notification transport, monitor and selected synthetic clinic policy remain **disabled**. A bound read-only helper passed **nine checks** with no business mutation or external send; empty exposed routes does not prove the absence of dormant environment values. The helper has **29 regression cases**; the combined binding/visual harness group passed **42 tests**. Real clinical receiver setup, separate supervision and the staffed response drill remain gated.
- [PR #80](https://github.com/NeoDiuZ/broby-v2/pull/80), [PR #82](https://github.com/NeoDiuZ/broby-v2/pull/82), [PR #83](https://github.com/NeoDiuZ/broby-v2/pull/83) and [PR #84](https://github.com/NeoDiuZ/broby-v2/pull/84) were reviewed, merged after required checks, and verified on both isolated V2 Railway services. [PR #81](https://github.com/NeoDiuZ/broby-v2/pull/81) is the concurrent acceptance-documentation update. V1 was not modified.
- PR #84 integration: **1,099 backend tests passed, one expected skip in each SQLite/PostgreSQL PMS mode**, with a real PostgreSQL clinical spine; **54 frontend tests**, type checking, production build and offline packaging passed. All six push/PR backend/frontend CI jobs passed, including packaged API checks. CodeRabbit reported a skipped review; root performed the integration review.
- Root personally completed hosted browser → API → persisted-state checks for reviewed administrative restrictions, selected recalls/internal acknowledgement, owner-consented mapping correction, exact assistant patient-choice continuation and catalog navigation, and clinician dispositions. These were clearly named synthetic fixtures.
- PR #84 mapping-history acceptance: stale owner change rejected; reload cleared every choice; fresh three-record disposition recorded; **25 independent checks** verified original records and media, current-use holds, AI/export/manual-delivery guards and qualified independent onward copies. Staff, owner and onward-owner screens were inspected. **Nine additional checks** verified owner contact and staff acknowledgement without reopening clinical use, and conservative full refresh after reconciliation.
- Five hosted real-model factual cases passed exact filters/counts/source identities for owner-linked invoices/reminders, local medication names and separate imported history. Browser selection preserved the exact original filtered question and returned only the chosen Cat's reminder. Saved views retained membership after a merge of only the new synthetic owner. Earlier **24/24 real-model synthetic intent cases** passed; neither corpus establishes clinical-language accuracy.
- The existing release workflow passed **17 persistence checks**. Thirteen existing feature groups passed immediately; continuous speech exposed a test-harness default-clinic assumption after new synthetic clinic creation. Exact recording/clinic/history checks proved the original completed job, transcript and bytes intact. Guarded binding fixed the harness, and **11 read-only continuous-speech checks** passed with no new transcription request.
- Hosted worker readback passed **seven checks**: workers run with the API; WhatsApp and external operational notifications remain disabled. A separate local PostgreSQL/browser/worker fixture verified six real loopback HTTP 503 attempts, audited retry, seventh HTTP 204 acceptance, administrator acknowledgement and a separate recovery event. No external human receipt or hosted independent-worker recovery is claimed.
- Conditional refresh local browser acceptance used 1,084 records (888,371-byte cold response versus 105-byte unchanged response) and verified foreground permission revocation. Any reconciliation review currently disables unchanged shortcuts deployment-wide to preserve cross-clinic/native/media integrity checks. This is not a hosted scaling claim.
- Full-bootstrap paging was assessed separately: specified patient/timeline cursor APIs already exist. A two-store probe demonstrated file-only media changes can open a hold without changing database revisions. Superficial paging would miss that change or multiply eligibility reads. Genuine bounded backend paging needs an authoritative dependency/integrity read model and a defined offline-snapshot scope; see [BOOTSTRAP_REFRESH.md](BOOTSTRAP_REFRESH.md). No unmeasured capacity claim is made.

## Consolidated inputs for the next acceptance batch

1. **Clinic authority and rules:** named approving clinic owner and clinical reviewer;
   timezone/hours; cancellation, no-show and deposit rules; currency/tax/credit/refund
   examples; recall consent/quiet hours; emergency wording and coverage. The existing
   policy document remains PROPOSED until explicitly approved.
2. **Migration authority:** an approved V1 export and included binaries, explicit
   permitted scope and date range, patient/owner/staff crosswalks, balances/stock
   control totals, and named reconciliation/cutover/rollback approvers. V1 stays
   read-only; access alone is not authority to copy real data.
3. **Integrations:** selected analyser vendor, protocol and test feed/device access;
   an enabled V2 WhatsApp sender, approved templates and webhook access, plus an
   authorized own-number test target. The latest Content API probe failed with
   HTTP401/code20003. No customer dispatch is authorized.
4. **Identity and clinical acceptance:** owner verification/recovery channel and
   household/clinic authority rules; approved terminology and representative
   questions/documents/audio; named reviewers and acceptance criteria. Private
   recordings need specific provider/destination authorization before processing.
5. **Devices and operations:** target physical devices/browser versions and two
   operators for simultaneous microphone, long-session, crash/eviction/recovery
   tests; clinic-size and latency targets; approved V2 storage/recovery destination
   and usable V2 service-execution access for a matched cloud restore rehearsal.
6. **Delivery and response:** an approved HTTPS operational alert receiver, private
   credential setup path, event-ID deduplication/incident-sequence handling and named
   receiving operator; separate external monitoring for API/monitor-host loss; clinical primary/backup/on-call rota, acknowledgement deadline,
   fallback channel and participants for an actual response drill. Infrastructure
   webhook acceptance is separate from clinical escalation and human receipt.
7. **Money and retention:** approved merchant and explicit authorized live payment
   test scope; per-data-class retention/deletion and backup-expiry schedule,
   legal-hold owner, and approved V2 public privacy text. No live money movement
   or retention deletion is authorized by this engineering task.
