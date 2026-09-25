# Broby V2 public legal copy — product-fact review

Prepared 25 September 2026 for the isolated Broby V2 site. This is a factual
review queue, not a replacement privacy notice, terms of service or legal
opinion. The V2 clinic decision maker and legal reviewer must approve exact
published wording before real-clinic onboarding. The V1 repository, site and
services are outside this review and must remain unchanged.

The hosted V2 `/privacy`, `/terms` and `/dpa` pages were read on 25 September.
The served pages contain the older claims listed below. The corresponding
markdown is duplicated in `web/content/legal/` and `website/content/legal/`;
the V2 frontend's `web/marketing/lib/legal.js` reads the first copy. The
deployment target of the second copy must be checked before editing it, so an
approved V2 change cannot affect the original Broby site. Verify the resulting
V2 public pages after any approved deployment.

| Public claim or contract area | Current V2 evidence | Review decision needed |
|---|---|---|
| Privacy: raw audio is automatically deleted from production after 90 days; backup audio is deleted 30 days later | V2 has a clinical-context preference, but no tested timed audio deletion, legal hold, matching backup-expiry and restore process. | Approve an accurate retention schedule and its implementation and restore test before promising a deletion time. |
| Privacy: account deletion control permanently deletes consultations, audio and templates | V2 has staff account revocation and session controls. A verified in-product erasure workflow for those clinical records is not evidenced. | Specify request, identity check, clinic authority, record-preservation duties and exact deletion workflow. |
| Privacy, terms and DPA: differential diagnosis, autonomous radiology analysis and old correction flows | V2 intentionally removed radiology/differential agents and the old corrector; its AI path uses receipt-backed draft assembly and factual retrieval. | Replace the feature descriptions throughout all three documents with the approved V2 scope. |
| Privacy and DPA: named AI, speech, monitoring and hosting subprocessors and storage regions | The lists describe older product integrations and deployment claims. The V2 runtime/provider inventory and contracts have not been reconciled against them. | Verify every provider, data category, processing region, retention term and onward transfer with the V2 operator and signed agreements. |
| Terms and DPA: de-identified data licensing, exports, return/destruction and support commitments | These are contractual promises beyond the audited V2 feature set. No V2 implementation/acceptance evidence has been recorded for every promise. | Have the legal/product owner confirm the commercial terms and the operational process that fulfils each one. |
| Privacy, terms and DPA: historic effective dates and product identity | The served V2 pages carry May 2026 language for the older BrobyVets/AI-scribe product. | Approve the V2 entity/product scope, effective date, version, notice and acceptance process. |

The existing V2 clinic policy draft is in
[`CLINIC_LAUNCH_POLICY_DRAFT.md`](CLINIC_LAUNCH_POLICY_DRAFT.md). Its proposed
zero-default fees/tax, verified owner-message consent, retention caution and
staffed on-call requirements also need a named clinic decision maker, accountant
where applicable, and legal review. The public legal pages should be updated
only from that approved decision, with a rendered page comparison and hosted
readback. Until then, the synthetic V2 preview can be tested, but real-clinic
onboarding must remain gated.
