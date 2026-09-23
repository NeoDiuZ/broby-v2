# Full-product status — 23 September 2026

**Update:** The exact first-build implementation and acceptance results are now tracked in [FIRST_BUILD.md](FIRST_BUILD.md). The PostgreSQL spine, v2 contracts, paged patient screens, missing-source flags and reference-band charts are implemented. The older whole-product workflows below are still in transition; native v2 events are not yet consumed by every older module.

Scope: preserve the v1 website/interface direction and core web workflows, add the v2 patient-record/PMS/owner workflows, and remove autonomous radiology, differential diagnosis and general-knowledge clinical agents. Native mobile and the extension are deferred by the user. This is a substantial local implementation, not a finished production replacement.

“Local” means a real persisted workflow against the synthetic SQLite dataset. “Adapter” means code and mocked tests exist but no live provider has been exercised. The original checkout remains unchanged.

| V2 items | Implemented | Still required |
|---|---|---|
| 1–3: patient, owner, events | Stable clinic-scoped IDs, patient/owner editing, owner merge, patient events, record revisions | Reconcile actual v1 identities and finish migrating all PMS writers/readers to the new PostgreSQL spine |
| 4–6: observations, ontology, receipts | Number/text/boolean definitions, immutable codes, numeric reference flags, original source receipts, document and transcript links | Ontology suggestions/curation lifecycle, clinical validation of provider-selected excerpts |
| 7–9: outbox, actions, reads | Audited idempotent shared action layer, role/feature checks, manual outbox, clinic-scoped search/timeline/observation APIs | Provider delivery worker/webhooks; new patient screens use cursor paging; remaining older modules still use full bootstrap |
| 10–13: capture, offline, gaps, handoff | Numbered notes, durable browser audio chunks, manifest gap checks, offline note queue, route-independent capture, interrupted-note recovery | Offline cold launch, tested simultaneous physical-device handoff and OS/browser crash matrix; native capture deferred |
| 14–17: pipeline, diarization, generation, retention | No 10-second live pipeline; optional full-recording Deepgram adapter with speaker timestamps, source-linked Anthropic excerpt organization, visible omitted text, medical/context selection; local verbatim fallback | The specified periodic 25-minute refinement pipeline, real multilingual speech evaluation, translated documents; originals are preserved, not automatically deleted |
| 18–22: timeline, analytics, categories, flags | Search/date/category filters, numeric trends, typed observations, lab CSV import, source-neutral reference-range flags | New v2 charts use observed timestamps and reference bands; older imported records may lack sample dates. Vendor mappings and unit reconciliation remain |
| 23–25: assistants/dashboard | Deterministic retrieval; optional model intent parsing and confirmed shared actions; exact patient disambiguation, date windows, receipts and saved count charts | Live model evaluation, durable conversational memory, richer query composition and automatically refreshed dashboards |
| 26–27: clients/scheduling | Client edit/merge, day/week/month calendars, recurring appointments, collision checks, rescheduling and visit statuses | Staff availability/rooms/rota, cancellation policy workflows |
| 28–29: billing/payment | Integer-cent invoices, externally received payments, externally completed refunds, voiding, invoice PDF, net-payment reporting | Payment gateway, tax/credit-note rules and accounting reconciliation |
| 30–31: inventory/dispense | Stock adjustments, receiving records with supplier/batch/expiry metadata, atomic dispensing and prescribed instructions | Remaining quantity per lot, expiry-enforced dispensing, purchase orders and stocktake reconciliation |
| 32–34: staff/reminders/reports | Membership editing, nurse/vet/admin roles, due-reminder draft preparation, clinical/financial counts, CSV export, handover | Automatic reminder scheduling/delivery, complete financial/operational reports |
| 35–36: migration/labs | Patient CSV preview/import, validated clinical JSON import, lab CSV receipt import, ZIP backup of records/history/ontology/audit/binaries, restore into empty directory | Actual v1 migration mapping and reconciliation; lab vendor feeds. Financial/stock-history JSON import intentionally rejects unreconciled records |
| 37–44: owner web | No signup wall for shared records, pet profile, approved notes/files/audio, medications/reminders, 90-day saved browser access, referral links, pre-consult intake accepted into clinic sources | Verified cross-device identity, multi-pet/household account management, receiving-clinic identity/consent. Saved access is a browser capability, not a verified account |
| 45–49: communication | Manual WhatsApp opening/copy, draft edit/cancel, shareable approved media, recorded-care retrieval, emergency contact notice, morning handover | BSP onboarding, inbound/outbound webhooks, delivery retries, full after-hours assistant and actual emergency escalation. Urgent forms are flagged but never claim emergency monitoring |
| 50–53: administration | Isolated clinics, active memberships, optional password sessions, multi-clinic membership linking, server-side mutation permissions and locks | Master organization administration, staff invitations/reset/MFA, granular read access and production security operations |
| 54–58: removals | No radiology/differential/general-knowledge agent or medical corrector in the new app; no legacy live chunk pipeline or duplicate AI action executor | Continue regression validation as providers are activated. Manually recorded imaging findings remain part of records |
| V1 presentation | Warm app typography/layout, locally preserved live-site design, clinical workspace/navigation, source editor, templates, browser capture | Full screen-by-screen v1 parity audit, dark mode/localization and remaining accessibility checks. Homepage radiology/differential promotions removed; remaining marketing depicts the product vision, not verified local capabilities |
| Excluded for now | Native mobile and Chrome/ezyVet extension source retained in original checkout | Rebuild deferred by user |

## Validation performed

- 51 backend tests, including 12 PostgreSQL acceptance tests plus the earlier coverage: concurrency/idempotency, patient/clinic boundaries, role/locks, source receipts, transactional stock/payments/refunds/imports, calendar collisions/series, record history, owner intake/grants/saved media, AI excerpt rejection and provider HTTP contracts, backup/restore and PDF responses.
- TypeScript and both Next.js production builds pass.
- Browser: all earlier navigation/document workflows; new calendar booking; owner pre-visit submission → Handover → accepted patient receipt; laboratory CSV → two stored observations and source; visual calendar check.
- Consultation and invoice PDFs rendered and visually inspected.
- Live microphone, external providers and real multi-device capture have not been exercised. Provider tests use mock HTTP transports; no production data/messages/payments were sent.

## Remaining web work in priority order

1. Complete browser offline cold-start and real-device capture/refinement testing, then evaluate configured speech/AI with approved test recordings.
2. Finish the remaining v1 visual/accessibility parity and web owner account workflows.
3. Connect chosen WhatsApp BSP, payment and laboratory vendors against test accounts; implement delivery, webhook and reconciliation contracts.
4. Complete inventory/financial/organization workflows and reconcile a copy of actual v1 records.
5. Production storage/authentication/observability/security, retention policy and deployment validation.

Do not treat the unavailable external integrations or any items in the right column as completed.
