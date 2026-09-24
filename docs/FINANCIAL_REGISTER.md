# Dated financial register

Administrators open Reports, choose a start and end date, and load the Financial
register. The period uses the clinic's timezone, including the complete end date.
The general clinic overview export now contains patient and consultation counts;
financial exports come from the reconciled register.

The register lists original invoices, recorded payments/refunds, credit notes,
credit reversals and dated invoice voids. Amounts remain integer cents. Each row
contains a source ID, invoice ID, recorded UTC timestamp, clinic date, reason and
available provider reference. Stripe sandbox movements are labelled as test entries.
Pending checkouts and refund requests are not payments or completed refunds.

Opening net balance + period net charges - period net payments = closing net
balance. Positive invoice balances contribute to receivables; negative invoice
balances contribute to refunds due. A credit changes the charge and does not
pretend to move cash. A later void contributes a negative charge in its own period,
while the original invoice remains in the earlier period.

New voids append a receipt in the same transaction as the invoice change. Replaying
the same action key returns the original result; a second void request is rejected.
For older voids, the first existing invoice.void audit timestamp supplies the date.
If that receipt is absent, the report raises an issue instead of inventing a date.

Every report also compares all reconstructed invoice charges and cash totals to
their current saved balances. Missing or malformed movements, unresolved historical
voids and balance differences remain visible. CSV export is blocked until those
issues are resolved. Text cells are protected against spreadsheet formula execution;
monetary columns remain signed numeric cents. Missing historical tax breakdowns
remain unknown and are counted separately from known tax changes.

## Boundaries

- This is a register of recorded facts, not a double-entry general ledger, a tax
  return, a bank reconciliation, a cash drawer reconciliation or proof of settlement.
- Current writers and this register use SGD. Other currencies are rejected rather
  than mixed. Clinic-approved tax/accounting policies remain outstanding.
- A provider movement uses the date Broby verified and stored it, which can differ
  from the provider's transaction date or bank payout date.
- A report is an explicitly loaded snapshot. Refresh it after changes. CSV export
  takes a new consistent database snapshot and includes its generation timestamp.
- Periods cover at most 366 days. The server returns paged entries but computes
  totals from the complete clinic ledger within a 50,000-record safety bound. It
  fails rather than silently truncating totals. Canonical PostgreSQL ledger and
  clinic-scale performance work remain open.
- Synthetic records and Stripe test payments remain the authorized release scope.

## Acceptance

Regression cases cover clinic midnight boundaries, independent charge/cash totals,
credits, reversals, refunds due, later voids, action replay, missing older receipts,
unknown tax, imported balance differences, foreign references, administrator scope,
pagination, CSV formula protection and explicit capacity/currency failures.

Isolated and hosted browser/API acceptance and exact release IDs are recorded in
RELEASE_WORK.md and the private release report once verified.
