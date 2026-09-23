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

The first transfer creates a patient/primary owner, never a name-based merge.
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
reconciliation. Request tokens and filesystem paths are not displayed.

Verified owner login/identity and reconciliation of independently created
destination patients remain separate unfinished requirements. This release uses
revocable owner capability links, not proof of legal identity.

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
