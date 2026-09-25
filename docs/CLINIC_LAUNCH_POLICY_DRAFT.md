# Broby V2 clinic launch policy — proposed baseline

Prepared 25 September 2026 for the isolated Broby V2 product. This is a
clinic-operating draft for owner review. It does not bind any existing Broby
clinic, set a legal tax rate, or authorize customer messaging. The clinic's
named decision maker must approve its values before a real-clinic launch.

| Area | Proposed operating rule | Broby V2 control and launch proof |
|---|---|---|
| Booking cancellation and no-show | Staff may cancel or mark a booking. No automatic fee, forfeiture or refund is charged. Any fee or deposit needs a separately approved written schedule shown to the owner before booking. | Existing scheduler changes status without charging. Test a booked, cancelled and missed appointment against the financial register; verify zero unapproved charges. |
| Deposits | Do not require or collect a deposit by default. When the clinic adopts a deposit schedule, display amount, application, cancellation/refund terms and owner consent before taking payment. | Keep deposit collection disabled until the product can issue, apply, reverse and reconcile it against invoices and payments. |
| Tax and invoices | Default tax rate is zero; a staff member enters the clinic-approved rate explicitly. An invoice records currency, items, rate, discount and integer-cent total. No automatic tax treatment is inferred from a patient's location or service type. | Clinic accountant approves rates and rounding with example invoices; reconcile generated PDF, saved invoice and financial register. |
| Credit notes and refunds | Credit notes require an invoice, reason and authorised staff review. A credit reduces the charge; it is not evidence of money returned. Record a refund only after the provider confirms it, and review refunds due separately. | Test issue, reversal, partial refund and replay; reconcile balances and provider receipts. |
| Owner messages and recalls | Send only to a verified contact with recorded consent for that message class and channel. Respect opt-out and changed contact details at send time. Staff review message content and recipient list. A queued or provider-accepted status is not delivery. | Keep production dispatch disabled until sender, approved templates, consent provenance, signed callbacks, opt-out, retries and delivery readback pass with the clinic's own test numbers. |
| Record and audio retention | Preserve clinical records and source receipts pending an approved retention schedule and legal hold procedure. Do not promise automatic raw-audio deletion at 90 days until timed deletion, backup expiry, legal holds and restore behaviour are implemented and tested. Export and erasure requests require identity and clinic review. | Approve country-specific schedule, remove unsupported public claims, test deletion/hold and consistent database/file backups with a restore drill. |
| After-hours questions | The owner portal can accept a question and label it urgent; it is not a monitored emergency service. AI may quote only approved care and route uncertainty to staff; it must not diagnose, prescribe or promise a response time. | Keep the warning visible and verify saved staff queue, repeat handling and source revocation. |
| Emergency escalation | The clinic must name a staffed on-call rota, backup contact, hours, acknowledgement target and fallback phone line. An internal alert is not delivery to a clinician. If coverage or delivery fails, present the emergency phone instructions and do not claim monitoring. | Enable external alerts only after a controlled on-call test confirms receipt, acknowledgement, overdue escalation and staffed fallback end to end. |

## Approval record to complete before live clinic use

- Clinic legal name and operating country: **pending**.
- Decision maker and approval date: **pending**.
- Accountant-approved tax rate, rounding, credit and refund examples: **pending**.
- Booking/deposit/fee schedule and owner-facing text: **pending**.
- Retention schedule, legal hold, backup expiry and privacy notice: **pending**.
- Sender, consent wording, approved templates and opt-out path: **pending**.
- On-call roster, backup, emergency line, hours and response target: **pending**.

Until those fields are approved, the safe defaults above remain the launch
boundary. This document is not evidence that a clinic has staffed or accepted
any response obligation.
