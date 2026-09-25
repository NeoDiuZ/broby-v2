# Read-only V1 consultation export preparation

The original Broby consultation table is separate from its patient table.
Its `patient_id` can be a consultation-thread UUID or `NULL`; it must not be
treated as a V2 patient ID or matched by pet name. This V2-only converter reads
a **supplied, approved** full-table CSV or JSON export and a staff-reviewed
identity crosswalk. It never opens a V1 database, calls a V1 service or edits
the original repository. No real V1 data has been imported.

## Review file and rehearsal

The review file is JSON with `source_clinic_id` (V1 UUID), `target_clinic_id`
(exact V2 clinic ID), `reviewer`, a timezone-aware `reviewed_at`, `patients`,
and `consultations`. Every consultation ID in the export must appear exactly
once in `consultations`, with a `patient_key` and a 10–1,000 character review
reason. Each patient key needs a corresponding reviewed patient mapping and
reason. Repeated names or contact details never merge patients automatically.

A patient mapping may create a **provisional** patient and separate provisional
owner with `key`, `name`, `species`, `owner_name`, `reason` and
`reviewed_status: "active"`. Inactive, deceased and unknown statuses cannot be
silently presented as active V2 patients. Alternatively, it can link to an
existing V2 patient using `key`, `target_patient_id`,
`target_name`, `target_species`, `target_version` and `reason`. Those four
target values must match the actual clinic patient at preview and Apply.
Multiple original patient-thread IDs assigned to one key require
`confirm_thread_merge: true`; a species conflict requires
`confirm_species_conflict: true`. Both also require the written reason.

Synthetic crosswalk example (replace every identity after a real staff review):

```json
{
  "source_clinic_id": "11111111-1111-4111-8111-111111111111",
  "target_clinic_id": "clinic-east",
  "reviewer": "clinic-east-admin",
  "reviewed_at": "2026-09-25T09:00:00+08:00",
  "patients": [{
    "key": "reviewed-pet-1", "name": "SYNTHETIC Historical Pet",
    "species": "Cat", "owner_name": "SYNTHETIC Owner",
    "reviewed_status": "active",
    "reason": "Staff reviewed the original animal and owner identity."
  }],
  "consultations": [{
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "patient_key": "reviewed-pet-1",
    "reason": "Staff confirmed this visit belongs to the reviewed animal."
  }]
}
```

The approved export must include **all columns** of the V1 consultation model,
including nullable columns, original timestamps and deletion markers. This
prevents a partial `SELECT` from silently omitting history. Use one source
clinic and at most 2,400 consultations per batch. Keep the same patient keys,
review metadata and source clinic across batches. The V2 preview limit is
5,000 output records; split a larger batch if the converter refuses it.

```sh
.venv/bin/python scripts/prepare-v1-consultations.py \
  /private/approved-v1-consultations.json \
  /private/reviewed-patient-crosswalk.json \
  /private/v2-consultation-preview.json
```

The converter creates a **new** 0600 output file and will not overwrite one.
It contains private clinical text and contact data. Send its `source_system`,
`target_clinic_id`, `reference_assertions` and `records` fields to the V2
administrator's `migration.preview` action. Inspect the record counts,
existing patient ID/version fingerprints, source text, identity mapping and
digest. Apply only the same payload with that exact `expected_digest` after
review and rollback preparation. A change to an existing linked patient or
source invalidates the digest. A clinic mismatch, target name/species/version
mismatch, duplicate source, missing assignment or changed import content
fails closed.

## Scope and remaining cutover work

This path imports exact **text history** as staff-private, unapproved source
and timeline event records. It preserves the V1 row and original status/date;
historical AI suggestions are labelled as such, not accepted as V2 diagnosis.
It does not fabricate an active V2 consultation or publish a note to an owner.
The owner portal exposes only ordinary patient profile fields; migration
provenance, review reasons, original custom fields and unapproved events stay
internal even if a clinic creates a synthetic share link during rehearsal.
Repeated preparation and Apply are deterministic; changed source content
conflicts instead of overwriting prior medical records.

A row with recording sessions/count or nonempty consultation metadata is
refused until the linked media/files and metadata have a reviewed export and
checksum mapping. Soft-deleted rows require an explicit retention decision.
Audio, attachments, entry tables, owner-message delivery receipts, financial
and stock history, patient/owner reconciliation, full-clinic export
completeness and real cutover/rollback acceptance remain unfinished. A text
preview is **not** evidence of a full V1 migration.

`api/tests/test_v1_consultation_mapping.py` uses synthetic CSV/JSON exports to
test exact text, missing V1 thread IDs, duplicate-name isolation, existing V2
patient assertions, replay, stale reviews, refusals and private file output
in both SQLite and PostgreSQL modes. Real export acceptance must compare V1
table counts and IDs to the complete approved export without writing to V1.

## Hosted synthetic acceptance — 25 September 2026

V2 backend and frontend revision `5adab61f9359dccf9ad5ad62c714d01ed3fed472`
was deployed successfully. An isolated synthetic V1 row and reviewed crosswalk
were prepared with the CLI, previewed in the V2 migration API and applied to a
synthetic receiving clinic. Editing the target patient invalidated the old
preview digest; Apply rejected it with HTTP 409. A fresh preview and Apply
succeeded, and a repeat preview reported both records unchanged. A second
authenticated staff session read back the exact original complaint, private
historical AI suggestion and patient link. The staff browser showed the dated
historical consultation in the patient's timeline and its full source detail.
The owner API and browser showed the ordinary pet profile without the private
suggestion, review reason or migration provenance. No real V1 data or service
was accessed in this hosted rehearsal.
