# Read-only V1 patient export preparation

The original Broby repository defines patients with embedded owner name,
contact and address fields. V2 has separate patient and owner records. The
V2-only converter in `scripts/prepare-v1-patients.py` reads a **supplied,
approved** CSV or JSON export of that V1 patient table. It never opens a V1
database, calls a V1 service or changes the original repository. No V1 data is
included in this repository.

The export must contain the model's exact field names, including `id`,
`clinic_id`, `name`, `species` and `owner_name`. Run one source clinic at a time:

```sh
.venv/bin/python scripts/prepare-v1-patients.py /private/approved-v1-patients.json /private/v2-preview.json --source-clinic-id <v1-clinic-uuid>
```

The output is a new file with mode 0600 and cannot overwrite an existing file.
It contains private contact and clinical data; store and delete it under the
clinic's approved process. Supply only its `source_system` and `records` fields
to the existing V2 administrator `migration.preview` action. Review the digest,
counts, identities and history before a separate `migration.apply` with that
exact expected digest. Never apply directly to the hosted V2 clinic from a
fresh converter output without reconciliation and a rollback rehearsal.

## Mapping and safety limits

- V1 patient UUIDs become stable V2 source IDs and deterministic target UUIDs.
  A repeat preview or apply detects unchanged content; a changed source row
  conflicts instead of overwriting the first import.
- Each V1 patient gets a distinct provisional V2 owner. Equal names, phones or
  emails are **not** merged as proof of household identity. Staff must later
  reconcile the owner links before live owner claims or messages.
- Explicit kilogram weights are imported. Missing weights display as not
  recorded; pounds, unknown units or malformed values stop the preparation.
  General patient notes become exact, unapproved staff source records. V1 last
  visit and original timestamps remain provenance metadata; no visit is
  fabricated from them.
- Mixed clinics, duplicate IDs, missing names/owners, soft-deleted patients,
  inactive/deceased status and unknown columns stop the entire preparation.
  These cases need reviewed mappings before a complete cutover. No row is
  silently skipped.
- This prepares patient identity, contact and general notes only. It does not
  transfer consultations, audio/files, financial records, stock history,
  consent, appointments or owner accounts. Those need separate approved
  export contracts, reconciliation and whole-clinic cutover testing.

Synthetic tests exercise converter refusal, file privacy, deterministic V2
preview/apply/replay and non-merging of same-contact owner rows in both SQLite
and PostgreSQL PMS modes. They do not constitute a live V1 migration or proof
that a real export is complete.
