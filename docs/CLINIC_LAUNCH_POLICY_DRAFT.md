# Broby V2 clinic launch rules — decision draft

Prepared 25 September 2026 for the isolated Broby V2 service. **Status:
proposed, not approved for a real clinic.** This is an operating decision sheet,
not a privacy notice, tax opinion, contract, or authority to message customers.
Do not copy the original Broby clinic's identity, legal text, contacts, sender,
or retention promises into V2 without that clinic's express approval.

The proposed defaults below let staff rehearse safely with synthetic records.
The clinic decision maker must fill in the decisions and sign the approval
record before real patient onboarding. The product owner must then verify that
the approved wording, configuration, receipts, and public pages agree.

These are operating restrictions, **not all automatic software gates**. V2
currently permits staff to enter a zero-tax invoice in its synthetic workflow.
The V2 public privacy page still contains an older 90-day audio-deletion claim
that the current retention implementation does not support. Resolve that public
discrepancy through an approved V2 legal notice before real-clinic onboarding;
this draft does not silently replace the published page. See
[`V2_PUBLIC_LEGAL_COPY_REVIEW.md`](V2_PUBLIC_LEGAL_COPY_REVIEW.md).

## Proposed operating rules and decisions

| Area | Proposed V2 rule until approval | Decision required for real clinic use |
|---|---|---|
| Cancellation and no-show | Staff may change booking status. Charge **no automatic cancellation or no-show fee**; do not imply that marking a booking cancelled moves money. | Clinic timezone, notice window, any fee, exceptions, who may waive a fee, exact owner-facing terms, and effective date. |
| Deposits | **No deposit is required or collected through V2.** A booking is not evidence of a payment. | If deposits are wanted: amount, when consent is obtained, how it is applied to an invoice, cancellation/refund terms, receipt and reconciliation process. Enable only after the complete payment/refund path is accepted. |
| Tax and invoices | The UI currently starts at zero tax. Treat this as a **synthetic-workflow placeholder**, not the clinic's tax rate. Do not issue real invoices until the clinic accountant approves the jurisdiction, tax treatment, rounding, examples and responsible staff review. | Legal entity and country, currency, approved rates/exemptions, item treatment, invoice numbering, rounding, sample invoice/PDF/register reconciliation, and effective date. |
| Credit notes and refunds | Require an invoice, reason, authorised staff review and an immutable credit/reversal receipt. A credit reduces charges; it does not prove a refund. Record a refund as completed only after provider or external-payment evidence is reconciled. | Who may authorise each amount, when a credit versus refund is used, treatment of tax on partial credits, refund method, owner notice, and reconciliation sign-off. |
| Owner messages and recalls | Keep customer dispatch disabled. A staff-reviewed draft is not delivered. For any future send, verify the exact destination and record channel-specific consent and purpose; recheck opt-out and changed contact details at send time. Distinguish provider acceptance from delivery. | Sender and provider account, consent wording/source/time, service versus recall versus marketing classes, approved templates, quiet hours, opt-out route, review authority, retry policy, delivery callback and incident contact. |
| Clinical records and audio | Preserve clinical records, original receipts and audio while the clinic's retention, legal-hold and deletion process is undecided. **No automatic 90-day audio-deletion promise applies to V2.** An access, export or erasure request needs identity and clinic-authority review. | Country-specific schedule for each data class, legal-hold owner, request workflow, deletion timing, backup expiry, restore behaviour, and the exact public privacy notice. |
| After-hours owner questions | The portal may save a question and flag urgency. Until a staffed rota and tested external alert are enabled, it is **not an emergency monitoring service** and must show the clinic's approved emergency phone instructions. AI may retrieve approved care information but must not diagnose or prescribe. | Coverage hours/timezone, emergency number and alternative facility, owner-visible wording, what counts as urgent, and who monitors the queue. |
| Emergency escalation | An internal alert is not proof that an on-call clinician received it. Keep external escalation disabled until a named primary, backup and fallback have acknowledged a controlled test. Do not promise a response time before that test. | Primary/backup rota, alert channel, acknowledgement target, overdue interval, fallback phone, escalation owner, outage procedure, and test date. |

## Acceptance before enabling a real-clinic flow

Record the test evidence and approver beside each gate. A passing synthetic test
is useful engineering evidence, but it does not prove owner consent, tax
treatment, an on-call response, or provider delivery.

| Gate | Required acceptance | Evidence / approver |
|---|---|---|
| Booking and billing | Book, cancel, mark no-show, issue an approved invoice, credit it, record a real-provider or verified external refund, and reconcile the PDF, register and balance. No unapproved fee or tax appears. | **Pending** |
| Customer messaging | On clinic-owned test numbers, confirm consent provenance, template approval, exact recipient, provider send/receipt, delivery or failure callback, opt-out and duplicate/uncertain-send handling. | **Pending** |
| Retention and privacy | Approve public wording; test timed deletion only if promised, legal hold, backup expiry and a restore. Verify access/export/erasure requests with clinic authority. | **Pending** |
| After-hours escalation | With a staffed primary and backup, generate one urgent synthetic question; confirm external receipt, acknowledgement, timeout escalation and fallback phone instructions. | **Pending** |
| Original-data migration | Obtain an approved read-only export and staff identity crosswalk; reconcile source counts, files, balances and patient/owner links, then rehearse cutover and rollback without changing original Broby. | **Pending** |

## Approval record — clinic owner to complete

- Clinic legal name, operating country and currency: **pending**.
- Named clinic decision maker, role, signature/approval reference and date: **pending**.
- Accountant and approved tax/credit/refund examples: **pending**.
- Cancellation, no-show and deposit schedule plus owner-facing text: **pending**.
- Messaging consent wording, sender, templates and opt-out contact: **pending**.
- Record/audio retention schedule, legal hold, backups and approved privacy notice: **pending**.
- On-call primary, backup, emergency line, coverage hours and response target: **pending**.
- V2 product owner confirmation that configuration and hosted acceptance match
  these decisions: **pending**.

Until these fields and the acceptance evidence are complete, this document is a
proposal for V2 synthetic testing only. It does not approve real billing,
customer messaging, retention deletion, or emergency monitoring.
