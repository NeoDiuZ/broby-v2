# Stripe sandbox payments

Broby New uses one isolated Stripe sandbox, bound to one configured clinic. This
release rejects live keys and live webhooks. It does not activate a merchant,
move real money, certify settlement or change V1. The existing simulated payment
adapter remains a separate diagnostic tool; Stripe sandbox payments do update
synthetic invoice balances and are explicitly marked `stripe_test`.

## Operator flow

1. In Billing, create an invoice for a synthetic patient.
2. Choose **Create test checkout**. Once ready, **Open test checkout** under
   Online payments. Enter a Stripe test card, never a real card.
3. Return to Billing. The worker independently retrieves Stripe's canonical
   payment state. A browser redirect is not proof of payment.
4. **Check payment** requests reconciliation if needed. **Cancel checkout**
   waits for provider confirmation before releasing the invoice reservation.
5. An administrator can **Refund test payment**. Only successful refunds reduce
   the invoice's recorded payment; queued, pending and failed refunds do not.

Manual payments and invoice voids are blocked while an active online checkout
reserves the balance. Manual refund records cannot change a Stripe payment. A
payment/cancellation race is resolved from the provider's current state.

## Configuration and provisioning

Backend-only variables: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`BROBY_STRIPE_MODE=test`, `BROBY_STRIPE_ACCOUNT_ID`,
`BROBY_STRIPE_CLINIC_ID=clinic-east`, and `BROBY_PUBLIC_URL` (public HTTPS origin).
No secret or publishable key is needed in the browser for hosted Checkout.

The sandbox `broby-new-payments` was provisioned through Vercel Marketplace after
explicit legal acceptance. Its resource container is `broby-new-integrations`;
no website is deployed there. The application remains on Railway Broby New.
Only the sandbox credentials were added to the Broby New backend.

Callback: `/api/integrations/stripe/webhook`. The raw request is verified with the
Stripe SDK, has a 1 MB limit and rejects live/Connect events. The callback saves a
deduplicated event and durable work item, then acknowledges it. Canonical Stripe
reads validate clinic metadata, checkout identity, currency, amount and account
before committing payment/refund records and invoice balances atomically.

Checkout/refund requests have stable provider idempotency keys. A separate local
worker thread uses persistent claims, finite retries and periodic reconciliation.
The task queue is independent of the long-running transcription thread. Missed
callbacks are caught by polling active/recent checkouts and by manual checks.

## Acceptance evidence

- Seventeen payment regression cases cover wrong signatures, stale callbacks,
  live events/keys, clinic/role isolation, balance reservation, duplicate events,
  SDK response objects, stale event ordering, payment/cancel races, pending and
  failed refunds, callback loss, interrupted acknowledgements, worker recovery,
  and refund reservation across a persistence failure.
- A real Stripe sandbox Checkout was created and retrieved successfully from an
  isolated local invoice. No mock provider was used for that check.
- PR #9 merged to `5d9f35d2ebfb3df51ba0dfb7dfdfe8917f31b6a4`; both Railway services deployed that exact revision successfully.
- Hosted browser acceptance on 24 September: synthetic invoice INV-1004, SGD 1.00. A declined test card stayed unpaid, then a successful test card marked it paid. A SGD 0.40 partial refund succeeded and left SGD 0.60 paid / SGD 0.40 outstanding.
- Independent Stripe API retrieval confirmed the completed, paid, non-live session and successful 40-cent refund. Broby persisted four matched signed events with no failed tasks. The browser showed the same invoice and refund values.

## Operational limits and recovery

The application is still a single backend replica with SQLite-backed tasks and
ledger records. This release does not claim an independent distributed worker
or finish the broader PostgreSQL/files migration.

A failed task remains visible through `/api/integrations/stripe/status` for an
administrator. Uncertain provider outcomes preserve invoice/refund reservations.
Refresh retries safely with the same key. A checkout acknowledgement older than
its creation window, or a refund acknowledgement older than 23 hours, requires
provider reconciliation instead of risking a new request after Stripe's
idempotency retention. The task worker stops retrying after five transient
attempts. More than 100 refunds for one payment is a manual-review boundary.

The sandbox is a provider development account (US default); it is not an
assertion about the clinic's business registration or an activated Singapore
merchant. Actual merchant country, legal entity, bank verification, live
credentials and live settlement acceptance remain required before real usage.
