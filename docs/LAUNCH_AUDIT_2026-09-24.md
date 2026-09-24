# Broby V2 launch audit — 24 September 2026

This audit uses both tabs of the linked Google Doc, the current `main` checkout,
the live **Broby New** Railway deployment and the detailed [58-item status
table](FEATURE_STATUS.md). The document's **FIRST BUILD** tab is an older,
narrower milestone. The counts below describe implementation in the isolated
synthetic-data scope; they are not a certification for real-clinic use.

| Classification | Count | Google Doc items |
|---|---:|---|
| Implemented in the stated V2 scope | 39 | 2–4, 6, 9–10, 12, 14–22, 25–26, 29–32, 37–42, 44, 49–58 |
| Partial | 18 | 1, 5, 7–8, 11, 13, 23–24, 27–28, 33–35, 43, 45–48 |
| Not implemented with a real provider | 1 | 36 — direct laboratory/analyser feed |

The detailed table explains the limits for every item. In particular, #29 is
verified **Stripe sandbox** payment, #45 is a restricted **Twilio trial** adapter,
and #49 is a **portal** morning handover. Those are not equivalent to live
merchant settlement, production WhatsApp sending or a staffed emergency service.

## What this launch change addresses

- The public onboarding form and `/contact` page previously saved enquiries only
  in the visitor's browser. The new path saves them in the PMS PostgreSQL store,
  checks format and repeat submissions, and exposes a private site-owner review
  queue with a manual contacted status. The public form reports success only
  after the server confirms storage. It does **not** send an email or WhatsApp
  notification; the site administrator must review the queue.
- The public landing page advertised an ezyVet sidebar, unrestricted mobile
  recording, automatic WhatsApp delivery, automatic audio deletion, a drug dose
  calculator and guaranteed language/clinical accuracy. Current V2 evidence
  does not support those claims. The copy and feature illustrations now describe
  the browser workspace, vetted medication instructions, owner portal, source
  receipts and current integration limits.

## Remaining launch gates, in order

1. **Real laboratory feeds (#36):** choose a vendor/analyser, obtain its test
   feed and specification, implement exact patient matching, units, range and
   receipt mapping, then pass duplicate/error and live delivery acceptance.
2. **External communication (#7, #33, #45–48):** finish BSP/sender/template and
   callback setup, prove actual own-number send/receive/delivery, then agree
   consent, on-call coverage and escalation policy before any customer send.
   A Twilio trial screen has not exposed the required setup; Content API was
   refused on the trial account. Internal alerts are not emergency delivery.
3. **Real clinic migration (#1, #35):** obtain the approved V1 export and binary
   files, map identities and full financial/stock history, reconcile counts and
   bytes, then rehearse rollback. No V1 customer data has been moved.
4. **Clinic and provider acceptance:** activate a live Stripe merchant and
   settlement only after the clinic billing/tax policy is signed off; agree
   cancellation, retention and escalation rules; test representative clinical
   speech, long recordings and physical cross-device handoff (#5, #11, #13,
   #23–24, #27–28).
5. **Operational recovery:** independently test cloud restore of PostgreSQL and
   the file volume at matched recovery points, external alerts and a staffed
   response. The present single backend process and mounted file volume limit
   scaling and continuity during redeploys.

## Public legal-text discrepancy

`web/content/legal/privacy.md` says raw audio is automatically deleted after
90 days, and describes account deletion and backup-retention behavior. The
current V2 product audit says timed source deletion is not implemented, and
the hosted backup arrangement is a separate, unsynchronised schedule. These
public terms need legal/product-owner reconciliation and a matching tested
implementation before a real-clinic launch. This change does not silently
rewrite contractual terms.

## Current verification boundary

Before this change, the live site loaded and the existing 17-check hosted
read-only smoke passed, including authenticated access, PostgreSQL readiness,
stored patient/lab/file/job persistence and logout. Railway reported all three
services healthy. Neither result establishes the full 58-item specification.
This launch change must pass local backend/frontend checks, PR CI, deployed
revision comparison, public browser submission, authenticated queue readback
and post-deploy health before it is marked shipped.

**Release decision:** the isolated synthetic demonstration can remain live.
Do not describe Broby V2 as ready for a real-clinic cutover until the gates above
are closed with evidence.
