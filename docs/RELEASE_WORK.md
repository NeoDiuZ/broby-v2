# Completion work in progress

This follows the 58 requirements in FEATURE_STATUS.md. A shipped feature must have
its code, failure-path tests, hosted verification and exact deployed revision
recorded before its status is changed to complete.

## Confirmed release decisions

- Broby New remains separate from V1, using synthetic records.
- Stripe is the selected payment provider: one clinic merchant, starting in a real
  Stripe sandbox. Live account activation and real settlement are separate gates.
- The user authorizes a controlled WhatsApp test to their own number. Existing
  V1 WhatsApp routing and its registered number must remain intact.
- The user authorizes provisioning required services and accounts. Provider
  verification, legal acceptance and security prompts are handled when reached.

## Work sequence

1. Real Stripe Checkout, signed durable callbacks, reconciliation, refunds,
   duplicate/concurrent/failure tests, deployment and browser payment test.
2. WhatsApp test sender onboarding, bounded recipient access, inbound/outbound
   delivery state and retry/reconciliation; real recipient receipt verification.
3. Durable assistant conversations and complete permitted action contracts.
4. Offline cold launch and encrypted local clinical storage; continuous recording
   refinement; cross-device and transfer reconciliation.
5. Canonical PostgreSQL PMS, external files, independent worker, pagination and
   operational monitoring, with recovery and load acceptance.
6. Remaining billing/rota/retention/owner identity/reporting requirements and
   vendor-specific lab/migration work once the actual inputs are available.

Do not label placeholders, a healthy deployment, test-mode money or an internal
notification as verified live delivery, settlement, clinical acceptance or a V1
cutover. See FEATURE_STATUS.md for the complete open requirement inventory.
