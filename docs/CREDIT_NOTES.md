# Credit notes and invoice balances

Credit notes reduce the recorded invoice charge without changing the original
invoice, recording a payment/refund or returning stock. Staff supply an explicit
amount before tax, an explicit tax credit (zero is valid), and a reason. The
server validates the two remaining amounts independently, using integer cents.
The existing clinic roles, feature locks, invoice versions, transaction and
idempotency checks apply. An active Stripe checkout prevents charge changes.

An issued note retains its original patient/owner/clinic identity and amounts.
Corrections use an append-only full reversal; there is no edit or delete action.
Invoices with any credit history cannot be voided. A reversal can reopen a debt
after a previously completed refund, which the review displays before confirming.

Every balance uses original total minus credits plus reversals. Outstanding and
refund due are separate non-negative amounts. A paid invoice can therefore show
refund due after a credit, until the separate external or Stripe refund completes.
Stripe checkouts charge only the remaining balance; provider reconciliation and
duplicate callbacks preserve the credited invoice status.

## Review and acceptance

Billing provides amount/reason entry followed by a confirmation review, invoice
and credit-note PDFs, an issued/reversed note history and a scoped CSV register.
Reports include credits less reversals on their actual record dates. Ask Broby
has strict proposal contracts for issue/reversal, with exact patient/invoice,
amounts, tax, reason and resulting balances. It never infers tax allocation.

Use only synthetic records for this release. In Billing, issue a credit for a
known invoice, inspect its resulting charge/outstanding/refund due, confirm and
reload. Download the note and register. Reverse the note with a reason and check
the restored balance and retained history. Repeat with a fully paid invoice:
the credit must show refund due without creating a refund by itself.

`api/tests/test_billing_credits.py` covers limits, strict inputs, append-only
history, replay, stale versions, permissions/locks/isolation, legacy invoices,
Stripe reservations and refund callbacks, saved assistant confirmations and
scoped exports. Frontend tests cover precise decimal parsing and balance rules.
`scripts/smoke-credit-notes.py` separates hosted preparation, real-model review,
Stripe checkout/test settlement, bounded planner regression and fresh-session readback. It stores progress in a private
ignored file and refuses accidental repeat mutation phases.

This is an operational credit-note register, not a general ledger, statutory tax
certification or accounting-system integration. Clinic-approved tax treatment,
accounting reconciliation/period policy and live merchant acceptance remain open.
The broader requirements in FEATURE_STATUS.md are not completed by this release.

## Verified hosted core

On 24 September, the browser issued/reversed a 218-cent synthetic credit. The real
assistant issued/reversed a 327-cent credit with explicit tax and saved reviews.
Stripe's sandbox charged 80 cents after an initial 20-cent credit, then refunded
30 cents after a second credit; both provider and app ended with 50 cents paid
against a 50-cent net charge. PDF and register readback passed. A missing-tax
response-format failure prompted the safe retry/structured-planner follow-up
tracked in RELEASE_WORK.md.

The assistant transport uses an inert structured-result collector following
[Anthropic's tool specification](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).
It returns proposal data only; all existing server validation and explicit
confirmation remain mandatory. Clinical excerpt generation is unchanged.
