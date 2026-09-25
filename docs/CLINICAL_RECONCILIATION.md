# Conservative review of transferred history

Evidence date: **2026-09-25**. This is a bounded V2 workflow for clinician dispositions and preservation of historical evidence. It does **not** complete clinical-fact reconciliation, certify patient/owner identity, infer equivalence, release an established patient hold, or settle another clinic's independent copy. Original Broby/V1 is outside its scope.

## Review and immutable evidence

A vet or administrator opens a mapping-correction receipt from either receiving patient. The review includes both identities and owners, their preserved current/history records, approved source payloads and transfer receipts, original file/audio checksum verification, earlier clinician decisions, and exact known onward-copy references. Records without a complete source group remain visibly unresolved.

A complete group must have the original transfer receipt and required receiving source/event/media or medication-history records. Each selected record needs its own explicit disposition and reason. A group is an inseparable source unit: mixed record dispositions are rejected, so uncertainty stays unresolved. The clinician separately acknowledges both the full evidence review and its patient-level consequences. An identity, record, binary, receipt or relevant history change invalidates the whole preview; the screen clears previous choices on reload.

Confirmation appends a receipt with reviewer, original identifiers/versions/fingerprints, per-record reasons, original byte receipts, and known onward-copy references. It never edits, moves, deletes, reassigns or deduplicates the original clinical facts or media. Original clinical equivalence is explicitly not asserted.

## Persistent current-use hold

Wrong-patient, unresolved, or subsequently stale retained evidence establishes a conservative hold. Old clinical text may have been copied into summaries, files and other records without dependable lineage, so the hold covers the patient's current clinical use and exact known downstream receiving-copy patients. This does not assert that every held record is wrong.

A later retained group **cannot release this patient hold**. The earlier hold seed remains part of the append-only record. A future release needs an independently reviewed contract for all historical derivatives, unresolved legacy data, identities and receiving copies; that release operation is deliberately absent here. Initial mapping corrections still carry their unresolved-history warning even before a clinician records a disposition. A fresh retained group only records that particular review; it is not a blanket historical resolution.

Financial and scheduling records remain administrative records. Their amounts are preserved, and held-patient administrative rows are qualified. Assistant/query context excludes their free text during the hold so an invoice item cannot masquerade as a current prescription. Financial PDF/CSV output explicitly qualifies clinical wording while preserving accounting history.

## Current-use consumer matrix

| Consumer | Enforced behavior | Regression evidence |
| --- | --- | --- |
| Bootstrap, patient cards/search, current record lists | Exclude held clinical records, clear cached weight, show patient/global hold notice; retain qualified administrative receipts | `test_clinical_reconciliation.py` |
| PMS/native timeline, measurements, concepts, counts, flagged results | Filter held facts and their exact native/source dependencies; native direct event/source URLs return409; filtered empty results do not establish absence of historical evidence | `test_reconciliation_spine.py` plus record/query tests |
| Direct staff files/audio/chunk/manifest reads | Reject current use; explicit vet/admin forensic media path provides unchanged bytes with historical status | Owner/media/binary tests |
| Owner links and owner-account aliases | Exclude held care/media and show notice; authorized direct media/PDF returns 409; other-patient token still returns 404 before hold evaluation | Direct media, owner conversation tests; delegated portal routes |
| Saved owner conversation replies/cards | Withhold previous clinical replies/cards from owner; preserve staff evidence with explicit qualification; held questions do not invoke provider classification | Saved owner reply/provider tests |
| Assistant model context, deterministic reads, saved turns/replays/actions | Filter current facts and ambiguous held administrative text; withhold stale saved responses/actions; fence generation/save/confirmation against relevant patient/clinic epochs | Assistant/history/query suites and reconciliation tests |
| Summary/transcription jobs and live speech | Check source/patient eligibility and relevant patient epoch before provider windows and publication; saved held results are withheld | Jobs/live speech suites, queued job/provider-race tests |
| Approvals, discharge, clinical export/copy | Guard under shared writer before idempotent replay; PDF and saved text exports revalidate live server state/version; clipboard no longer exports a cached editable draft | Action replay, text/PDF tests |
| Recalls, manual delivery preview, handover | Held recalls cannot be queued/delivered or used in campaign previews; affected saved campaigns and handovers are restricted. Urgent/new owner follow-up remains visible as a redacted administrative attention entry; staff can open qualified history, contact the owner and acknowledge follow-up, while clinical replies and raw old turns remain restricted | Recall/handover regression |
| Financial administrative exports | Preserve values; invoice/credit PDF and credit/financial CSV qualify clinical wording; held administrative text excluded from AI/query retrieval | Administrative receipt and existing billing/report tests |
| New outward transfers | Source patient must be eligible; previously accepted copies/receipts remain immutable | Transfer + onward-copy tests |
| Known downstream copies | Exact origin edges propagate a source-dispute qualification and current-use hold; own clinic can access qualified preserved history; no claim of correction or receiving-clinic adjudication | Onward-copy test and staged smoke readback |
| Forensic archive/history/backup | Preserve original rows, versions, native archive and media, with explicit purpose/current-use prohibition and qualification sidecar | Original-row/byte readback and archive tests |
| Unrelated patients and clinics | Per-patient epochs and dependency closure avoid invalidating unrelated jobs or saved answers | Unaffected patient/clinic regression |
| Offline/previously loaded copies | Existing encrypted 12-hour maximum remains; stale/offline notice and fresh server checks before new approval/export/AI; downloaded/loaded copies cannot be recalled | Existing 41 frontend tests plus server stale/action tests |

Clinician receipts and holds are recomputed from persisted evidence at read time. Conditional bootstrap optimization must disable its unchanged shortcut whenever a reconciliation review exists globally; upstream decisions, identity changes and native dependencies may affect another clinic without a local record revision. `has_reviews(c)` provides this fail-closed integration hook. No new claims about large-ledger performance or offline revocation are made. Reviews are bounded to 1,000 records / 5 MB metadata and 200 MB per media record; dependency chains and onward-copy reviews are bounded and refuse use when exceeded.

## Verification and remaining gates

The isolated synthetic PostgreSQL browser rehearsal was performed by the root agent on 2026-09-25: per-record/group review, stale owner edit returning 409, reload clearing choices, fresh clinician confirmation, visible hold, owner/direct/PDF restrictions, and qualified original media. Separate API readback verified original rows and binary hashes unchanged, affected queued work rejected, and an unrelated other-clinic job completed. No successful clinician decision was automated for that browser fixture. The root then verified the final urgent follow-up flow in the browser: a new synthetic urgent owner question appeared as a redacted staff chooser entry, its qualified original was readable with a contact link, no clinical reply form appeared, and browser acknowledgement cleared the attention count. Eight independent API checks confirmed the exact question/acknowledgement, persistent hold, continued owner/media restrictions and absence of an invented clinic reply.

Backend regression suites run separately with SQLite PMS and PostgreSQL PMS, including native PostgreSQL tests; frontend type checking, unit tests and a production/offline build are required for integration. The reconciliation permission is one guided action. When integrated with PR #83's catalogue it yields 74 strict + 28 guided + 6 internal = 108 actions; preserve the other agent's strict contracts and parity tests.

Final isolated branch checks on 2026-09-25: **967 passed, 1 skipped** with SQLite PMS/native PostgreSQL (66.87s), **967 passed, 1 skipped** with PostgreSQL PMS/native PostgreSQL (160.56s), **41 frontend tests**, TypeScript, and production/offline build passed. The fresh staged API smoke passed all phases in a separate disposable PostgreSQL test. These counts apply to this branch base plus this change; the combined release must rerun its catalogue and consumer checks after integration.

This branch's synthetic evidence is not a hosted-release or real-clinic-readiness assertion. Hosted acceptance, the deployed revision, independent clinician identity verification, complete legacy reconciliation, receiving-clinic adjudication, and any future safe patient-hold release remain separate gates. Existing downloaded/offline copies cannot be recalled, and untracked receiving copies cannot be enumerated reliably.

## Reproducible hosted synthetic acceptance

`scripts/smoke-clinical-reconciliation.py` reuses the existing `smoke-transfer-corrections.py` V2-only client and private state writer. It creates **fresh** clearly named synthetic source/receiving clinics, source facts/media, an established old link, a corrected link, preserved derivatives, a saved assistant review, and a known independent onward copy. It does not modify previously certified fixtures, send external messages, transcribe audio, request model-generated content, or call `clinical.reconcile` successfully. Prepared transfer mapping/consent is explicitly synthetic API setup; clinician reconciliation is a separate browser action.

Use a private credentials file and a new private state path. Owner capability URLs remain in that state file; do not paste them into public logs.

```sh
python scripts/smoke-clinical-reconciliation.py --credentials /private/path/v2-login.json --state /private/path/new-reconciliation.json --phase prepare
python scripts/smoke-clinical-reconciliation.py --credentials /private/path/v2-login.json --state /private/path/new-reconciliation.json --phase review
# Root opens patient_url in target_clinic_name and reviews original evidence.
python scripts/smoke-clinical-reconciliation.py --credentials /private/path/v2-login.json --state /private/path/new-reconciliation.json --phase stale
# Root confirms old preview -> 409, reloads, re-reviews, and explicitly records
# previous-patient file-group wrong-patient dispositions/reasons in the browser.
python scripts/smoke-clinical-reconciliation.py --credentials /private/path/v2-login.json --state /private/path/new-reconciliation.json --phase readback
```

The script refuses non-V2 hosts unless a disposable loopback fixture is explicitly enabled. Readback compares originals/media, checks stale saved assistant confirmation and new jobs are refused before provider use, checks authorized owner 409 versus wrong owner 404, and proves onward copy preservation/qualification. Hosted workers are not paused: queued-work race proof stays in the isolated local regression/browser fixture. The script's complete stages were independently exercised through a disposable local API/PostgreSQL test, with successful disposition supplied outside the script as a test-only stand-in; hosted browser evidence must be recorded separately.
