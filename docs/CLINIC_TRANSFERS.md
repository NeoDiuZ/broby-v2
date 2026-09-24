# Reviewed clinic transfers

Owners can request that another registered clinic receive their pet's approved
notes and files plus the source clinic's patient and primary-owner details.
Separate unchecked controls opt into structured medication history and finished,
approved original audio. Approved notes can themselves mention medicines; the
owner screen makes that distinction explicit. Consent scope cannot expand while
a request is pending. The owner can see the request after reloading and withdraw
it until acceptance. Requests expire within seven days and remain bound to a
valid source grant and the exact source patient/clinic.

Receiving vets and administrators use Settings → incoming records → Review
transfer. The preview shows source identity, destination identity, exact payloads,
new/changed/already-copied counts, original IDs and dates. Acceptance requires the
preview digest. Changed source data requires a further explicit acknowledgement.
A changed source, consent, approval, or receiving copy invalidates an old preview.
All imports pass through the shared role/feature-lock, audit and idempotency layer.

The first transfer defaults to creating a patient/primary owner. Receiving staff
can instead explicitly select and review an independently created clinic patient
using the procedure below. Names alone never establish a match.
Later transfers use the source-clinic/source-patient/receiving-clinic mapping.
Identical origin payloads are skipped, including files and observations. New facts
append. Changes append an immutable origin revision and a new receiving record;
local clinical edits, earlier copies, patient details and contact details are never
overwritten. Changed identity/contact information appears in a source receipt for
manual reconciliation. Missing or unapproved source items do not delete medical
copies already accepted by the receiving clinic.

Structured medication copies use `medication_history`, labelled externally
recorded in the timeline, with the original dose/frequency/instructions and date.
They do not create a prescription, dispense stock, copy stock/lot IDs, or change
billing. Original approved audio is copied into a transferred consultation and
linked from a timeline audio receipt. Every chunk must exist in a contiguous,
finalized manifest and match its SHA-256. Owner approval of audio does not expose
private transcript text, speaker identities or provider jobs; those are excluded.
Receiving staff can separately transcribe/review the original copied audio.

All imported events, files and audio start private to the receiving clinic. Typed
observations retain their exact values, supplied units and reference bounds.
Revoking a source grant after acceptance leaves the independent copy accessible
only under the receiving clinic's permissions.

Limits: 1,000 origin items / 5 MB of metadata, 25 attachments, 25 voice notes and
100 MB of combined media per request. Files are exclusively created and fsynced
before the database commit. Any handled transaction failure removes only files
created by that transaction. A process/power failure before commit can leave
unreferenced files; automated orphan collection and cloud restore rehearsal remain
operational follow-ups. Imports still use the existing single-backend SQLite
transaction alongside the PostgreSQL clinical projection.

## Earlier imports without revision history

Earlier transfers did not retain a reliable source manifest. A receiving vet or
administrator can now review the existing patient/owner and clinical records,
then explicitly establish a **new current-source baseline**. The source owner
must still make a valid, unexpired transfer request. Settings → Data & migration
→ Review transfer shows the earlier copies beside the current approved source.

Acceptance requires both identity confirmation and a separate duplicate-risk
acknowledgement, plus a 10–1,000 character review reason. All currently shared
source items are appended to the already-mapped receiving patient. Earlier copies,
files, local edits, contact details, and inventory remain unchanged. This can
produce duplicate facts: it does not reconstruct the historical source payload,
automatically match old facts, or assert that old and new records are equivalent.
Future requests compare to the new baseline and skip unchanged origins normally.

An immutable baseline receipt records the reviewer, reason, preview digest, prior
accepted request IDs, preserved receiving record versions/fingerprints and the
new origin fingerprints. A private timeline event explains the decision. The
preview includes native PostgreSQL receiving facts as well as PMS records; changes
to any reviewed receiving record, owner or source invalidate acceptance. Review
context is bounded to 1,000 records and 5 MB; larger histories require an archive
reconciliation. Existing receiving media is listed by stored metadata; only newly
copied source binaries are checksum-verified during acceptance. Request tokens and
filesystem paths are not displayed.

## Link an independently created receiving patient

For an unmapped first transfer, search by patient, owner or reference, select the
receiving patient and load its review. The preview includes source identity,
current receiving identity, every receiving owner and the existing clinical
history, including native PostgreSQL facts and recorded dispensing. Staff must
confirm the patient identity, acknowledge possible duplicate facts and enter a
10–1,000 character reason. Changing the selection or reloading clears approvals.
Changes to reviewed source, patient, owner links or history invalidate acceptance.

Acceptance preserves the existing patient, owners, local records, media and stock.
It appends the currently consented records and creates an immutable identity-link
receipt containing the reviewer, reason, digest and preserved record fingerprints.
A private timeline entry explains the decision. Future transfers use the saved
origin mapping and skip unchanged origins. The operation and copied files roll
back on a handled failure; competing destination choices cannot both succeed.

Known species mismatches and a receiving patient already linked to a different
patient at the same source clinic are rejected. Established mappings cannot be
retargeted through this workflow. A correction/relink procedure, clinical-fact
equivalence review and verified owner login/identity remain unfinished. This is a
staff assertion of animal identity, not an owner merge or proof of legal identity.
The owner consent mechanism still uses revocable capability links. Existing media
is listed by metadata; newly copied source binaries are checksum-verified. The
same 1,000-record / 5 MB receiving-context review limits apply.

## Verification

`api/tests/test_transfers.py` covers consent scope, strict opt-in, role isolation,
revocation/expiry/patient binding, stale source/destination previews, append-only
changed content, idempotency across new requests, exact media bytes, exclusion of
private transcript metadata, stock invariance, unapproved destination copies,
source revocation after acceptance, typed observations, gaps/checksum/size/limit
failures and rollback after files are written. The previous transfer test now uses
the reviewed preview contract. `scripts/smoke-clinic-transfers.py` provides the
hosted synthetic two-clinic rehearsal. See RELEASE_WORK.md for release evidence.

`api/tests/test_transfer_baselines.py` adds pre-revision recovery, acknowledgement
and reason validation, permissions, stale owner/local/native/source checks,
patient isolation, limits, transaction/file rollback, concurrent request rejection,
immutable history and repeat-request deduplication. The isolated production browser
rehearsal covers disabled acceptance, stale owner rejection, reload/review reset,
acceptance and persistence. API/database readback checks the PostgreSQL timeline,
old file bytes, one baseline, unchanged records/stock and the next deduplicated
transfer. No old-format mapping is present in the current hosted synthetic fixture;
that historical path is verified in the isolated local database, with hosted
normal-transfer regression checked separately.

`api/tests/test_patient_links.py` adds 31 cases covering explicit selection,
all-owner/history preservation, strict acknowledgements, stale reviews, species
and origin conflicts, clinic/role isolation, consent, replay, concurrency and
file/database rollback. `test_spine.py` also verifies native PostgreSQL changes
invalidate the review, and preserved owner links and native history survive the
accepted import. The isolated production browser checks selection gating, stale
additional-owner rejection, reload/reset, acceptance into the same patient and
persistence. Sixteen API/database checks verify unchanged receiving records,
immutable receipt, exact media, private copies, no new stock/dispensing, repeat
deduplication and retained copies after source revocation. Hosted release evidence
is recorded in the private patient-link release report.
