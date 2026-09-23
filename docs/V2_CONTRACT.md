# Broby v2 first-build API contract

All `/api/v2` endpoints are clinic scoped using the existing session/member boundary. IDs are opaque stable strings; never match a patient by name. The existing local PMS keeps its IDs during migration. Dates use ISO 8601 UTC, and numeric reference ranges come only from the submitting laboratory. No AI runs on this path.

## Read contracts

`GET /api/v2/patients?q=&limit=50&cursor=` returns `{items: [{id,name,species,breed,sex,date_of_birth,owner:{id,name},last_seen}],next_cursor}`. Search includes owner names. Cursor pages use stable `(name,id)` ordering.

`GET /api/v2/patients/{id}/timeline?limit=25&cursor=` returns `{items:[{id,event_type,occurred_at,summary,actor:{kind,name},source:{kind,id,page?,start_ms?,end_ms?}|null,body,flags:[{type,observation_id?}],observations:[]}],next_cursor}`. Newest first, stable `(occurred_at,id)` cursor; optional `category`, `q`, `start`, `end` filters. Missing provenance returns `missing_source`, measured excursions return `out_of_range`. Additional body keys and event types need no schema migration.

`GET /api/v2/patients/{id}/observations?concept=potassium` returns `{concept:{id,name,unit},series:[{observed_at,value,ref_low,ref_high,flag,event_id,source}]}`. `flag` is `high`, `low` or null, with no diagnosis. `GET .../concepts` lists available numeric series; same marker with different units is a distinct concept.

`GET /api/v2/patients/{id}` returns a patient. `GET /api/v2/patients/{id}/events/{event_id}` returns one event. `GET /api/v2/sources/{id}` resolves a source in the current clinic, returning provenance and a local content URL when a corresponding document/audio asset exists.

## Deterministic ingestion

`POST /api/v2/ingest/lab`

```json
{
  "patient_id":"milo",
  "dedupe_key":"laboratory:report-123",
  "occurred_at":"2026-09-18T09:14:00Z",
  "summary":"Biochemistry",
  "actor":{"kind":"system","name":"Laboratory import"},
  "source":{"kind":"document","id":"report-123","page":1,"text":"Potassium 5.8 mmol/L; reference 3.5–5.1"},
  "body":{"accession":"report-123"},
  "observations":[{"concept":"potassium","name":"Potassium","value":5.8,"unit":"mmol/L","ref_low":3.5,"ref_high":5.1}]
}
```

Returns `{id,event,duplicate}`. A clinic-scoped dedupe key creates one event across requesters and retries. Reuse with changed input returns 409. Event, sources and observations commit in one database transaction. A missing source is accepted and visibly flagged rather than silently attributed. Supplied reference bounds may be null. A source on an individual observation overrides the event source.

`POST /api/v2/events` adds `event_type` to the same payload. Supported types are open strings, initially lab_result, consult, vaccination, invoice and message. This endpoint shares the same ingest function.

Validation: finite numeric values; low <= high; timezone-aware timestamps; source kinds document/audio/event/human, valid page/audio position; known clinic patient; authenticated active member with applicable capture permission. No remote fetching of source URLs.

## Transition boundary

The normalized PostgreSQL spine is authoritative for v2 ingestion. Existing SQLite PMS records remain preserved while their patient, owner, clinical and membership records are projected into the spine using a durable change sequence. V2 reads consume PostgreSQL, not full client bootstrap data. Imported v2 events are visible in the new patient record, but have not yet been wired into every older assistant/owner/reporting workflow. Replacing the remaining PMS storage is separate migration work, explicitly reported rather than disguised as completed.
