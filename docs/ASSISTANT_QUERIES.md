# Assistant answers and saved views

Ask Broby and Reports now run the same validated record query. Previously a
low-stock or outstanding-invoice answer could save a broader view because its
special filter was not stored. The saved query now retains those filters and
recomputes current results when refreshed; the saved conversation remains a
dated snapshot. Old views retain their existing stored meaning. Lost filters
cannot be reconstructed from an old view's title; ask again and save a new view.

## Supported questions

- A single exact record ID within a supported record kind. “Show event record ID
  [ID]” or “Show invoice record ID [ID]” retains the ID in the saved query. It
  intersects the selected patient, clinic and every other filter; a missing,
  foreign, held or wrong-kind record does not widen the answer into a list.
- Literal event-title/body search, matching the timeline's case-insensitive
  substring meaning: “Find events whose text contains \"exact phrase\"”. Quotes
  make the requested phrase authoritative; a dropped or substituted phrase or
  record ID yields clarification. `%`, `_`, brackets and other punctuation are
  literal characters, never patterns. This searches recorded wording only; it
  does not infer synonyms, diagnoses or equivalent clinical meanings. Saved
  views re-evaluate current record versions while saved answers retain the
  versions originally returned. Shared permissions and reconciliation holds
  apply to both local and native PostgreSQL events.
- Low stock versus a complete inventory list; positive outstanding invoice
  balances, excluding void invoices.
- A patient or the clinic, inclusive start/end dates, exact recorded category,
  status or name; exact patient species and appointment clinician ID; counts
  grouped by category, status, species, name, clinician or day.
  In patient chat, the selected or exactly named patient stays authoritative:
  the model cannot replace that patient ID or silently widen the read to the
  clinic. Explicit “clinic-wide,” “whole clinic,” “entire clinic,” or “across
  this/the clinic” wording permits a clinic read, but the model cannot then
  narrow it back to one patient. Other scope changes require clarification.
- Patients, appointments, invoices and reminders linked to an exact clinic owner
  ID, including current primary and additional owner links. Matching uses the
  current patient link within the same clinic. Invoice reads describe current
  relationships, not historical invoice ownership or payment liability. An owner name alone is not an identity
  key; the assistant must select the recorded owner ID before retrieving the
  complete clinic-scoped set.
Duplicate owner names require explicit identity selection rather than a guess.
For an owner-specific question, the server also checks that the model kept the
same exact owner ID in a supported owner-linked query. If the model omits the
owner, selects a different one, or proposes another record kind, the answer is
a clarification without records. An unknown explicit owner ID is clarified.
- When a question explicitly says **status equals/is** or **species equals/is**
  a value recorded in this clinic, the server checks that the model kept the
  same exact filter. A missing, substituted, unknown or conflicting value
  returns a clarification without records or a saved view. This guard covers
  these explicit forms; it is not a general language-completeness guarantee.
- Appointments filtered or grouped by the exact recorded species of their
  linked clinic patient. Missing, malformed or foreign-clinic patient links do
  not match a requested species; grouping labels them "Not recorded".
- Observations with an exact concept code, optionally exact unit and typed
  equality. Boolean false remains distinct from zero and the text "false".
- User-supplied numeric bounds for an exact observation code and unit. No unit
  conversion, invented reference range, diagnosis or treatment recommendation.
- Externally recorded medication history separately from local prescriptions.
  Both support exact recorded name filters and name grouping, ignoring case but
  never matching substrings, alternative strengths, brand/generic substitutions
  or inferred drug equivalents. With “medication name equals/is [recorded name]”,
  a dropped, substituted or unknown name produces clarification. Explicit
  “local prescriptions” and “imported medication history” cannot be interchanged
  by the model; request them separately. This retrieves recorded instructions
  and does not determine whether a historical medication is currently indicated.

For example: “Show due reminders on 2098-07-10 grouped by day” or “Show recorded
potassium at least 5 mmol/L on 2026-09-24 for this patient.” Unsupported conditions
must be clarified; arbitrary query fields are rejected by the server. An invalid
model-produced read now becomes a saved clarification with no records or action,
rather than an unsuccessful conversation turn. Saved-view and direct API query
validation still reject the invalid filter.

Dates follow the clinic timezone. Reminders use due dates, appointments use their
scheduled date, and timestamped clinical facts use their occurrence date in that
timezone. Saved relative-date questions become explicit calendar bounds; a view
saved from “today” does not advance tomorrow. Ask again to choose a new period.
For a request saying **on YYYY-MM-DD**, the server applies both bounds to that
exact valid day and rejects a conflicting model date. It also rejects a model
date that conflicts with a deterministically resolved relative period such as
“today” or “last week.” Multiple explicit ISO dates in an “on” request require
clarification; this is not a general free-form date parser.

The answer shows its actual filters. Reports shows the same filters, counts and
matching-record receipts. Counts cover all matches; answers list 12 records with
30 receipt buttons and saved views return at most 100 records. Limits are visible
and ordering is stable. This is response bounding, not database pagination: the
current read layer still loads the requested record kind in memory and is not
clinic-scale certified. The saved-view/direct-query appointment species and
owner filters now fetch only their referenced same-clinic patients in bounded
ID batches instead of loading the clinic's entire patient table a second time.
The assistant's intent step now fetches recent, exact and linked planning
candidates, plus recorded filter metadata, without materializing the entire
clinical spine. It still reads the clinic's patient identities for name
resolution. The final factual read fetches only the requested record kind.
Neither read path paginates all matching appointments or certifies hosted
concurrent-load capacity.

## Acceptance

`api/tests/test_record_queries.py` checks assistant/view parity, exact species
and clinician filters, appointment-to-patient species links,
primary/additional owner links and live link changes on patients and
appointments, including clinic isolation and malformed links,
outstanding balances, timezone boundaries,
reminder due dates, exact units and typed equality, malformed/unsupported filters,
scope, native facts, bounded output and old saved-query compatibility.
It also checks that a model cannot silently widen an explicit recorded status
or species request, including a wrong value and an unknown value.
Explicit ISO-day and relative-period cases check omission, conflicting model
bounds, invalid dates and multi-date clarification.
Patient-scope cases reject a substituted patient, an unrequested clinic scope,
and a model-narrowed explicit clinic request, while preserving valid patient
and clinic reads.
PostgreSQL acceptance also verifies native
numeric filters, original receipts, boolean/text equality and saved-view parity.

Run the complete backend suite against isolated local PostgreSQL, then the web
tests, typecheck and build. Hosted synthetic evaluation uses
`scripts/smoke-assistant-queries.py`, a private credential file and private output
state. It tests the actual configured model and persisted current records. Browser
acceptance must additionally save an answer, open the view in Reports, inspect a
matching receipt, reload and verify the saved result. Exact release and provider
evaluation evidence is kept in the operator's ignored release report.

Remaining scope includes complete advanced action field contracts, arbitrary
joins/custom charts, representative linguistic/clinical evaluation, granular read
restrictions and large-data performance. A tested set of model requests is not a
guarantee that every natural-language question is interpreted correctly.

## Hosted V2 acceptance — 25 September 2026

At deployed V2 revision `3cb6573`, the configured real model mapped “all Cat
patients in this clinic, grouped by species” to an exact patient-species query
with 14 synthetic-clinic matches. It mapped appointments for Dr. Amelia Tan to
the exact `clinic-east-vet` clinician ID with 9 matches. Both queries returned
200; their saved views reproduced the same filters, counts, groups and source
IDs through authenticated API readback. In the hosted browser, Reports rendered
the 14 Cat matches; after reload and device unlock, the clinician view was still
listed and rendered 9 matches. This verifies these two example intents and
their persistence, not broad language accuracy or clinic-scale performance.

The exact owner-linked patient filter passed a focused synthetic SQLite and
PostgreSQL test on 25 September. It covered assistant/view parity, current
primary and additional links, a removed additional link, duplicate-name
clarification, wrong-kind rejection, foreign-clinic owner rejection and
malformed historical link data.

After V2 revision `3bdf9af` deployed, a real-model question about all pets
linked to one named synthetic owner, grouped by species, selected the exact
owner ID. It returned the two linked patients (one primary, one additional)
and one Cat and one Dog group. A separate authenticated session read back the
same saved-view query and two receipts. Removing the additional-owner link
changed the saved view to one Cat. The deployed browser displayed that one
matching patient, opened its receipt, then listed and rendered the same view
after reload and device unlock, with no framework error overlay. This verifies
one phrasing and this synthetic workflow, not broad owner-language accuracy.

Appointment species filtering and grouping passed a focused synthetic SQLite
and PostgreSQL test on 25 September. It combined an exact clinician and clinic
date with Cat appointments, checked saved-view parity, and excluded a patient
from another clinic and a malformed patient link. After V2 revision `1f43d00`
deployed, a hosted real-model question selected the exact Cat, clinician, date
and grouping filters. A separate authenticated session read back the saved view;
the deployed browser rendered its one matching appointment and exact receipt,
then showed the same saved view after reload and unlock.

Nine further hosted real-model synthetic prompts at revision `1f43d00` mapped
to the expected exact structured filters: Cat and feline patients, two owner
phrases, clinician/date, Cat plus clinician/date, Dog/date, outstanding invoices
and low stock. These are nine specific examples, not a representative language
or clinical evaluation. An owner-linked appointment question exposed a 422
invalid-query failure.

After revision `495702b` deployed to both V2 Railway services on 25 September,
the same real-model owner-linked appointment question returned the exact owner
ID, appointment kind and date bounds. Its result contained the linked synthetic
Cat appointment and excluded an unlinked synthetic Dog appointment. A second
authenticated session read back the matching saved-view query, count and source
IDs. In the hosted browser, Reports showed one match and the source receipt;
the view rendered again after reload and device unlock. An unsupported
owner-linked invoice question returned HTTP 200 with a limitation, no dashboard,
records or action, and persisted as a completed private conversation. This
verifies these synthetic examples only; representative model evaluation and
clinic-scale query performance remain unfinished.

At deployed V2 revision `8b94dfb`, another 13 synthetic real-model questions
passed exact query/clarification checks. They covered owner-linked patients and
appointments, owner plus species/date/clinician, explicit appointment status,
whole-clinic Cat and Dog patients, outstanding invoices, low stock, a supplied
owner ID and an unknown owner ID. The unsupported owner/invoice combination
returned no records or action. The first wording “appointments scheduled on
2098-08-04” selected the date but no status: “scheduled on” is ambiguous
between a booking date and the stored status. Rephrasing it as “recorded status
equals scheduled” produced both the exact date and status filters. The 13/13
result therefore applies to the explicit wording, not the ambiguous variant.
These cases do not certify clinical terminology, every phrasing or every
combination of read filters.

Owner-linked patient and appointment views now resolve a staff-merged owner ID
to its active owner when refreshed. This preserves saved views created before a
reviewed merge, with the active owner's current links and name displayed. A
malformed merge chain fails for review rather than silently returning a stale
or broader result. The saved-view regression passed all 46 query tests in both
SQLite and local PostgreSQL. After PR #62 reached both V2 Railway services at
revision `0aab16f`, an authenticated synthetic-clinic acceptance created two
owners, one pet and a saved patient view, then merged the owners. The view
returned the same pet under the current owner in two independent sessions;
the signed-in Reports browser displayed one match and the current owner's name.
The stored patient link and merged-owner marker were read back. Hosted appointment
views after a merge remain untested; their behavior is covered by the local
SQLite/PostgreSQL regression.

The saved-view appointment patient lookup also passed a 501-reference SQLite regression
that checks batch boundaries, exact species grouping, the 100-record saved-view
limit and absence of a full patient-table read. PostgreSQL parity remains a CI
gate for this change; hosted load/soak acceptance is still outstanding.

## V2 assistant filter and identity guard — 25 September 2026

PRs #72–#74 passed full frontend, SQLite, PostgreSQL and packaged API CI. The
focused assistant/query suites passed 105, 107 and 109 cases respectively as
the guards were added. Both isolated V2 Railway services reported the exact
successful commit after each merge. The 17-check persisted-state smoke passed
after PRs #73 and #74. Two fresh real-model synthetic questions retained the requested
recorded status and patient species. A third retained the exact `on YYYY-MM-DD`
bounds; an invalid day returned no records or action. After revision
`a11ec5785e0a9d879080fb6135d5e64113ab83b7`, real-model patient chat
stayed on the selected synthetic animal, and an explicit whole-clinic question
returned clinic scope. Private V2 test receipts retain the queries and saved
conversation IDs. No customer message, payment or original Broby action was
performed. These successful examples do not measure representative language
accuracy or capacity at real-clinic scale.

## V2 assistant scoped-read acceptance — 25 September 2026

PR #80 merged as `48bbb0c60907dd094fd9f7247bde2129d870c652`. Its full
frontend, SQLite, PostgreSQL and packaged API CI passed. A pure context
regression keeps an old named patient and linked owner in planning context
after 600 newer sources while excluding another clinic. A disposable
PostgreSQL 5,000-patient, 16-client workflow passed 21 checks, including
three assistant questions with complete deterministic counts: one old
patient appointment, 5,004 Cat patients and 500 clinician appointments.
The model context included 250 of 16,305 planning-eligible clinic records; server
intent plus factual read took 592–1,687 ms across the three questions.
Those timings exclude network and real-model latency.

Both isolated Railway services reported SUCCESS at the merged SHA. A fresh
synthetic hosted fixture passed 15 real-model query and saved-view checks,
then four persisted refresh checks; customer sending stayed disabled. The
deployed Reports browser displayed a one-result numeric observation view,
opened its exact 6.2 mmol/L source receipt and showed the saved view again
after reload and device unlock without a framework error overlay. This is
a synthetic release check; clinic-wide pagination, broader natural-language
evaluation and real-clinic capacity remain open.

## Bounded linked-read acceptance

`scripts/smoke-assistant-linked-reads.py` prepares a new synthetic owner, two
linked patients, exact invoice/reminder records, two differently named synthetic
medications and a same-name Cat/Dog pair for patient selection. Use only an
explicitly SYNTHETIC V2 clinic and private state/credentials outside Git:

```sh
python scripts/smoke-assistant-linked-reads.py "$V2_ACCEPTANCE_ORIGIN" \
  --credentials "$V2_ACCEPTANCE_CREDENTIALS" --state "$V2_LINKED_READ_STATE" \
  --clinic "$V2_SYNTHETIC_CLINIC" --actor "$V2_SYNTHETIC_ACTOR" --phase setup
```

Repeat with `--phase evaluate`. Evaluation checks actual model filters, complete
counts, exact source IDs and saved views while leaving business records unchanged.
The default imported-history case expects zero and proves a new local prescription
is not treated as imported history. To exercise a positive imported result, supply
`--history-record ID` in every phase for an existing synthetic imported-medication
receipt in this clinic. That record and its patient remain read-only. Positive
imported-history behavior also has local SQLite/PostgreSQL coverage.

The state file records two additional saved browser conversations:

1. Open `browser_turns.choices`, choose one of the two same-name synthetic
   patients, and inspect its exact due reminder on 2098-10-11. The retained
   question must remain `browser.duplicate_prompt`, with the original date/status.
2. Open `browser_turns.catalog`, click **Open Observation catalog**, and verify
   Settings displays **Typed observation catalog** and dictionary review. Do not
   create or approve a definition for this check.

Then run `--phase readback`. It requires the saved selected-patient continuation
first, verifies its exact filters/source and the persisted catalog destination,
then merges only this run's new owner into another fresh synthetic owner. Saved
invoice/reminder views must resolve that reviewed merge with the same source IDs,
while original saved answers retain their dated snapshots. Setup and interrupted
phases use deterministic mutation keys. No customer message, online payment or
assistant mutation confirmation is part of this script. Local script regressions
use fixed intent and API continuation stand-ins; only an observed hosted browser
run establishes hosted model and navigation acceptance.

Literal-search phrases and exact record/owner ID tokens are data, not scope or filter instructions. Before identity, dates, species, status, medication kind, advice and action detection, the assistant masks those spans and supported quoted exact-name/code/unit values. It retains the exact values separately for the read contract and preserves the original saved question. Conflicting, unterminated or escaped literal phrases clarify before selection metadata or model execution; backslash escapes are not a supported search syntax. A quoted `whole clinic`, `today`, patient name or `start` cannot widen a selected patient, add dates, select an animal or propose a consultation. Genuine outside scope wording still applies.

### Exact numeric trends from chat

Choose a patient, then ask `Plot observations whose code equals "potassium" and unit equals "mmol/L" from 2026-01-01 to 2026-09-25`. One unambiguous recorded name and exact unit also work. The model only selects a strict `presentation: "trend"` query; the shared read executor builds the chart from current eligible records. Code and unit must match exactly, including code case, with no conversion, drug/concept equivalence, diagnosis, fabricated values or inferred reference ranges. Missing patient, unit or ambiguous concept asks for clarification. Supplied ISO ranges and relative clinic-calendar dates remain in the saved query.

Each point includes its observation ID and version, source/event identity, numeric value and supplied bounds. All matching points and receipts are included up to 200; exceeding that limit asks for narrower dates and produces no partial chart. Missing bounds remain missing, and a shaded band needs both bounds. Lines connect recorded points only; gaps do not imply zero or continuous monitoring. Dates use a recorded observation/event timestamp when available; older local observations explicitly label the record timestamp fallback. Chart dates and filter summaries identify the clinic timezone.

Chat and saved views reuse the patient measurement chart. `Save this view` persists the exact query, and refreshing recomputes the complete bounded series. Saved answers retain their original point versions; a changed source version requests a refresh instead of silently showing different values. Reconciliation and permission checks apply to saved answers and live views, and a new reconciliation epoch clears the displayed chart/source. Count queries retain their existing response/query defaults.

The opt-in `scripts/smoke-assistant-visual-reads.py` binds to an explicit existing SYNTHETIC clinic/actor with a private 0600 state file. Run `setup`, `evaluate`, optional `guides`, then perform the manual browser open/save/source/reload steps in `state.browser` before `readback`. Setup adds only two new marked patients and five synthetic native result events (three plotted points, another unit and another patient). Evaluation uses the configured model and checks exact record/text filters and chart/source/range identity without confirming any action. Guide conversations exercise fixed Settings destinations. Readback verifies persisted state and original receipts; it does not claim browser clicks, hosted model acceptance or clinical accuracy from the local stubbed transport/model regression.

Numeric trends accept only the chosen patient, exact concept code/unit and requested dates. Extra record-ID, display-name, category or numeric-value subset filters are rejected by the shared saved-query contract rather than quietly hiding points or bypassing the 200-point limit. The assistant also rejects model-invented date bounds when the operator requested the complete recorded series. Use a count query for other supported filtering combinations.
