# Architecture update: PostgreSQL patient spine

`api/spine` owns the normalized first-build schema, deterministic ingestion and v2 API contracts. A frozen Alembic 0001 creates patients, owners, owner_patients, clinics, people, clinic_members, events with JSONB, concepts, observations and positioned sources. Clinic-wide unique dedupe keys plus PostgreSQL ON CONFLICT enforce one event across concurrent senders; changed payloads are rejected. Numeric flags and missing-source flags are computed deterministically on reads.

Existing SQLite PMS writes remain authoritative for legacy records. SQLite triggers append durable clinic change sequences. Before v2 reads, `projection.sync` serializes per clinic with a PostgreSQL advisory transaction lock, reads a consistent legacy snapshot and projects normalized facts. Its checkpoint commits with those facts. Native v2 events have independent IDs/dedupe namespaces and are not overwritten. The projection is transitional: it does not yet make native events visible to older assistant/owner/reporting readers. Membership identity is separated from clinic membership; legacy demo members remain distinct until explicitly linked to a password account.

New patient screens consume `/api/v2` directly, with race-safe request invalidation and cursor paging. The reference chart uses observation timestamps rather than import order; each point opens its event and its receipt. The document's design constants live in `web/app/tokens.css`. Tailwind utilities are compiled through PostCSS without preflight resetting preserved older screens.

See [FIRST_BUILD.md](FIRST_BUILD.md) for startup, acceptance, limitations and coordinated backups. The sections below describe retained legacy modules and are not claims that all storage has migrated.

---

# Architecture and invariants

## Layout

- `web/`: Next.js/React/TypeScript single workspace, locally served fonts, v1-inspired warm palette, timeline and consultation panels. The owner page is separate.
- `api/`: FastAPI, SQLite WAL, Python durable worker.
- `website/`: the homepage mirrors the live brobyvets.com design captured on 2026-09-23. `public/live/index.html` contains its self-contained markup/styles/scripts; pixel images and animation frames are hosted locally. Fonts retain the live Google Fonts links. A root rewrite serves it without an iframe. Sign-in opens the local workspace; onboarding saves a local draft. Original repository subpages remain as historical references. Marketing copy is not a guarantee of feature availability in the new workspace.
- `scripts/`: repeatable setup, build, start; no deployment scripts.

## Writes

`POST /api/actions` carries action, payload, and idempotency key. `actions.execute` checks clinic membership, role and feature locks, opens a serialized SQLite transaction, replays identical prior requests or rejects reused keys with different payloads, dispatches the action, records an audit entry, and commits atomically. The UI and assistant's confirmed proposed actions use this same entry point. File upload and chunk endpoints are specialized local transport operations; they are not independently audited like actions yet.

Patient IDs and clinic scope are required for every clinical relationship. Names are presentation, never join keys. Source notes are immutable. Source receipts on a document must belong to its patient. Invoices store integer cents. Dispensing updates inventory and creates the medication record in the same transaction.

Mutable records carry an integer version. A stale write fails with HTTP 409 rather than overwriting a newer record. The browser keeps unsaved document drafts and exposes a conflict message when the authoritative version changes. Duplicate financial submissions with the same key replay once; a retry with an obsolete version also fails.

## Background jobs

A document job snapshots the consultation version, exact source IDs, template sections and input revision. The worker quotes those source facts into sections. It does not invent text, diagnose, or claim AI transcription. Before committing, it rechecks the consultation version. A concurrent edit or appended source creates a conflict result, preserves the newer record, and leaves all source notes untouched. Queued/running jobs survive API restarts.

Optional provider adapters now exist. Speech produces one immutable transcript source with speaker timestamps linked to retained audio. Anthropic selects exact contiguous source excerpts; the server rejects unknown receipts/invented text and preserves omitted source material for review. This verifies textual provenance, not clinical completeness or meaning: vet review remains required. The assistant interprets read/action intent and requires operator confirmation before the shared action layer executes. Mock HTTP tests cover adapter contracts; no live provider has been validated. The specified periodic 25-minute refinement pipeline is not implemented.

## Browser state

Workspace refresh uses a sequence counter to reject older responses, including when changing clinic. Clinical document drafts hold their base server version. New notes queue in IndexedDB with stable idempotency keys. Audio is written as blobs before upload, server manifests identify acknowledged chunks, and completion fails if indices have gaps or unexpected chunks. Local audio is removed only after acknowledgement. The recorder lives outside a page component so routing does not stop it. Identity changes are blocked while capturing/saving.

Interrupted capture metadata uses a heartbeat; recovered files are labeled. This does not guarantee recovery of a segment the browser/OS never emitted, nor implement native device handoff. Imported files wait until all browser writes finish before becoming uploadable.

## Local boundaries

Loopback-only processes and an origin check reduce accidental exposure, but simulated actor headers are not real authentication. All staff in a clinic can read the clinic's local records; role permissions constrain mutations. Owner endpoints filter approved records, approved attachments, prescriptions and reminders and check grant expiry/revocation. Anyone with access to the demo machine can still open its staff preview, so this is not an isolated production owner-access deployment.

Before production: replace simulated identities with verified sessions and clinic membership, design formal schemas/migrations and indexes, add retention and deletion policies, encryption, backups/restoration, attachment scanning, rate limits, tamper-resistant audit history and proper access tests. Validate deployment and record migration against real service contracts. No part of this preview changes the production deployment.


## Added web modules

`workflows.py` extends the same shared transaction dispatch with scheduling, owner intake, ontology, refund, stock receipt and import actions. `reads.py` defines date filtering and handover projections. `schema.py` adds repeatable local migrations and a record-version trigger. `import_validation.py` rejects malformed/cross-patient clinical references; financial migration is excluded until reconciliation exists.

`auth.py` provides optional scrypt passwords, expiring hashed sessions, username/clinic memberships and failed-login throttling. Password mode ignores caller-supplied actor identity. Demo mode remains the default. Owner saved access uses a separate HttpOnly cookie capability, expires after 90 days, and stays tied to root grant revocation. It is not verified person/household identity. Approved owner media is available through both short-lived grant and saved-access routes.

ZIP backups include clinic records, revision history, ontology definitions, audit entries, files and audio with checksums. They exclude authentication, sharing grants, browser state and job/mutation queues. Restore requires an empty destination. Production recovery procedures, scheduling and storage encryption are separate work.
