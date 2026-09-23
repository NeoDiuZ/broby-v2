# Hard workflow release contract

Source: the two-tab Broby V2 requirements document, rechecked 23 September 2026. The full-product vision governs this release; the first-build tab describes the earlier foundation milestone.

## Release boundaries agreed with the owner

Use Broby New and synthetic data. Messaging transmission is disabled. Payment and laboratory vendors are unselected: adapters must explicitly identify simulated results. Existing V1 and its WhatsApp connection are not changed. No real patient migration or real payment is authorized by a synthetic test.

## Acceptance stories

1. A numeric, text or boolean lab observation arrives without a consultation. Retries create one event. A conflicting retry fails. Numeric limits are supplied by the lab; text and boolean values never acquire invented normal ranges. Patient timeline, factual assistant, saved views and approved owner vault read the same clinical facts and receipts.
2. Every authenticated event ingest uses shared authorization, clinic locks, idempotency and audit. Clinical facts missing receipts remain visibly flagged. Ontology changes are explicit, versioned proposals; existing concepts cannot silently change type or unit.
3. Long recordings and document jobs survive restart. Workers claim jobs with leases, preserve newer edits, retry transient failures with bounded backoff and expose terminal failures. A new device creates a new numbered note without stopping an existing recording.
4. Inventory has receipt lots, remaining quantities and expiry. Dispensing consumes eligible lots atomically; expired stock cannot be dispensed. Stocktakes require reasons and preserve an audit history. Scheduling validates configured staff availability and room collisions. Billing stores explicit discounts and tax rates with integer-cent reconciliation.
5. Synthetic payment, lab and message adapters exercise duplicate callbacks, failures, retries and reconciliation. Production sending and money movement remain disabled. Delivery, provider acceptance and manual completion are separate states.
6. Saved dashboards persist a validated, clinic-scoped query and refresh from current facts. Provider/job/queue diagnostics expose failures without secrets or clinical payloads.
7. Staff access can be provisioned and revoked through a controlled account lifecycle; clinic and organization policies apply at shared action boundaries. Owner cross-device access and receiving-clinic transfers require verified identity, explicit consent and revocation.
8. Migration tooling previews stable source identities, collisions and reconciliation before import. A synthetic rehearsal and restore exercise must preserve patient links, totals and provenance. A real V1 cutover remains gated on an approved export and clinic policies.

## Verification and reporting

Run the existing regression suite plus focused concurrency, isolation, replay, expiry, rollback and restart tests against PostgreSQL. Verify browser-to-API-to-persistence workflows on the Mac and the deployed Broby New revision. Record which stories are implemented and evidenced, which are partial, and which depend on external enrollment or clinic decisions. A passing health check is not evidence of real message delivery, payment settlement, a physical analyser feed or clinical accuracy.

## Implementation status for this release

Implemented: typed clinical values across PostgreSQL, timeline, assistant and approved owner vault; authenticated ingest through shared actions; live saved queries; leased jobs with bounded retries; explicit billing adjustments; lots/expiry/stocktake/purchase orders; configured rooms/availability; single-use staff invitations, MFA/recovery and password changes; organization clinic provisioning/master restrictions; reviewed dictionary proposals; signed synthetic adapters; internal urgent-submission acknowledgement; owner-consented clinical transfers; stable-ID clinical migration preview/apply.

Partial: the clinical readers now include native PostgreSQL facts, but the PMS still uses SQLite and a projection. Transfers currently carry approved events and approved attached files, not original audio binaries or a complete active-medication reconciliation. Migration rehearsal validates clinical records, not financial or stock-history imports. Emergency requests are an internal queue with sending disabled, not an on-call alert service.

Unfinished: offline cold-launch/device privacy controls; continuous 25-minute refinement and real device handoff trials; verified cross-device owner/household identity; production payment/WhatsApp/lab onboarding; clinic-approved credit-note/accounting rules; approved V1 identity/financial/stock migration and cutover; full single-store transition, load testing and operational alerting. These are not marked production-ready by the synthetic release.
