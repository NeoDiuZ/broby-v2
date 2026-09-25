# Assistant answers and saved views

Ask Broby and Reports now run the same validated record query. Previously a
low-stock or outstanding-invoice answer could save a broader view because its
special filter was not stored. The saved query now retains those filters and
recomputes current results when refreshed; the saved conversation remains a
dated snapshot. Old views retain their existing stored meaning. Lost filters
cannot be reconstructed from an old view's title; ask again and save a new view.

## Supported questions

- Low stock versus a complete inventory list; positive outstanding invoice
  balances, excluding void invoices.
- A patient or the clinic, inclusive start/end dates, exact recorded category,
  status or name; exact patient species and appointment clinician ID; counts
  grouped by category, status, species, name, clinician or day.
- Patients and their appointments linked to an exact clinic owner ID, including
  primary and additional owner links. Appointment matching uses the current
  patient link within the same clinic. An owner name alone is not an identity
  key; the assistant must select the recorded owner ID before retrieving the
  complete clinic-scoped set.
Duplicate owner names require explicit identity selection rather than a guess.
For an owner-specific question, the server also checks that the model kept the
same exact owner ID in a patient or appointment query. If the model omits the
owner, selects a different one, or proposes another record kind, the answer is
a clarification without records. An unknown explicit owner ID is clarified.
- Appointments filtered or grouped by the exact recorded species of their
  linked clinic patient. Missing, malformed or foreign-clinic patient links do
  not match a requested species; grouping labels them "Not recorded".
- Observations with an exact concept code, optionally exact unit and typed
  equality. Boolean false remains distinct from zero and the text "false".
- User-supplied numeric bounds for an exact observation code and unit. No unit
  conversion, invented reference range, diagnosis or treatment recommendation.
- Externally recorded medication history separately from local prescriptions.

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

The answer shows its actual filters. Reports shows the same filters, counts and
matching-record receipts. Counts cover all matches; answers list 12 records with
30 receipt buttons and saved views return at most 100 records. Limits are visible
and ordering is stable. This is response bounding, not database pagination: the
current read layer still loads records in memory and is not clinic-scale certified.

## Acceptance

`api/tests/test_record_queries.py` checks assistant/view parity, exact species
and clinician filters, appointment-to-patient species links,
primary/additional owner links and live link changes on patients and
appointments, including clinic isolation and malformed links,
outstanding balances, timezone boundaries,
reminder due dates, exact units and typed equality, malformed/unsupported filters,
scope, native facts, bounded output and old saved-query compatibility.
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
