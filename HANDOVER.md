# Broby v2 handover

## Purpose and boundaries

This repository contains the complete v2 source workspace, including the active combined frontend, Python API, schema migrations, tests, scripts, and preserved website reference. Dependencies, generated builds, actual local databases/uploads, credentials and the separately extracted v1 checkout are intentionally excluded. Recreate synthetic data using the seed scripts; this is not a backup of runtime data.

**Do not modify or redeploy v1.** The customer's existing Railway Broby project, production domains, PostgreSQL, Redis, volumes and GitHub deployment source are outside this handover. Create a separate Railway project and separate PostgreSQL service for v2. Do not copy production credentials, connect to its database, or switch DNS. Supabase has been dropped from the plan; do not configure Supabase dependencies or delete its existing project as part of this handover.

## Read in this order

1. README.md — local startup and test commands.
2. docs/FIRST_BUILD.md — patient-record milestone and acceptance evidence.
3. docs/V2_CONTRACT.md — implemented API contract.
4. docs/DATABASE_HANDOVER.md — two-store transition, schema, migration sequencing and backup limitations.
5. docs/FEATURE_STATUS.md — full feature-by-feature done/remaining checklist.
6. docs/DEPLOYMENT.md — Railway plan and blockers.

Specification: https://docs.google.com/document/d/1Oca1mRqo32iZ7OjH_nz24OjChAuxAUo369uWJmq1kR0/edit
The document describes both a broad 58-item product and a narrower FIRST BUILD. The patient foundation is substantially implemented; the complete product is not finished. Extra PMS screens were preserved at the owner's request despite the first-build scope excluding them. Referenced mockups at ~/broby-v2-mockups were unavailable. Native mobile and the extension are deferred; radiology/differential/general-knowledge agents are excluded.

## Implemented

- Single frontend: website `/`, clinic `/app`, owner `/owner`, API `/api/*` on localhost:3100. Old root clinic hash links redirect to `/app`. `website/` is a reference, not a second service.
- Normalized PostgreSQL patient/owner/membership/event/observation/concept/source model, frozen Alembic 0001, lab ingestion, dedupe and positioned source receipts.
- Searchable patient directory, paginated day-grouped timeline, reference-band chart and point-to-event navigation; synthetic lab history and incoming-result simulator.
- Local persisted PMS workflows: appointments, clients, notes/templates, billing bookkeeping/PDFs, stock, manual message drafts, owner grants/intake, staff roles and handover. These are not all backed by the normalized database yet.
- Browser draft/audio queues and recovery logic; optional AI/speech adapters disabled by default. Provider tests use mocks.

## Not finished

The highest priority is a consistent record across all readers/writers: native v2 lab events currently do not feed every older assistant/report/owner/document workflow. Complete SQLite-to-PostgreSQL migration, durable file storage and job processing before describing the product as unified.

Other gaps: periodic ~25-minute refinement, offline cold launch and real-device handoff testing; real speech/model evaluation; ontology curation; richer assistant/dashboard queries; household/cross-device owner identity; WhatsApp delivery/webhooks/retries/after-hours/escalation; payment gateway/tax/credit notes; inventory lot quantities/expiry/purchasing/stocktake; scheduling availability and full reporting; master organization controls, staff invitations/reset/MFA; actual lab adapters and migration reconciliation. See FEATURE_STATUS.md for precise boundaries.

## Validation and limits

At handover preparation: 51 backend tests pass (39 existing workflow tests + 12 real PostgreSQL tests); TypeScript passes. The unified frontend production build previously passed. Required first-build behaviours are tested: independent lab event, duplicate delivery, missing-source flag, supplied-range flag and new event type without migration.

Earlier browser checks covered the main patient/source/chart flow, appointments, owner intake, lab CSV and PDFs. There is no comprehensive automated browser suite. Real microphones/device interruption, real providers, load/security testing and cloud deployment remain unverified. Do not equate test counts with full specification compliance.

## Recommended next PRs

1. Add dedicated CI PostgreSQL test service and browser smoke coverage, reproduce the current baseline on a clean checkout.
2. Migrate SQLite persistence with audited ID/history preservation and cross-feature integration tests; remove the projection bridge only after all consumers move.
3. Add durable upload storage, production authentication/authorization and origin configuration, and an independent retryable worker.
4. Prepare and deploy isolated Railway staging using synthetic data; verify persistence through redeploys and restoration from backup.
5. Implement the remaining agreed product scope and vendor integrations against sandbox accounts.

Before accepting handover, run the test suite, inspect the database transition, rehearse the colleague demo, and agree the release scope. Keep live customer migration and production cutover as separately authorized work.
