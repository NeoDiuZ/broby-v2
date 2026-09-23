# Clinic workflows: easy-to-medium release

Scope: the five easy and fourteen medium items in the 23 September 2026 audit.
Changes ship to Broby New only. V1 and the user's existing WhatsApp connection
are not modified. Use synthetic records for local and hosted acceptance.

## Acceptance criteria

| Spec | Workflow | Acceptance |
|---|---|---|
| 2, 26 | Patient identity and owners | Valid date of birth round-trips through create/edit, directory and owner view; future/invalid dates fail. Primary and additional owners can be linked without cross-clinic links or duplicate relationships. Changes preserve history; old owner access is revoked on an ownership change. |
| 20, 22 | Categories and ranges | Alias categories (bloods/lab, x-ray/x_ray) produce the same filtered timeline. No supplied range means no invented range or flag; exact-boundary values are not flagged. |
| 18, 19 | Timeline and dashboard | New records refresh without navigating away; search includes recorded text; native lab facts are included in the clinic clinical overview with clickable patient/source navigation. |
| 10, 12 | Voice notes and recovery | Rename notes; preserve numbering; reject incomplete and altered chunks; interrupted local uploads keep data and report errors. Repeated completion must not mutate finalized audio. |
| 15 | Speaker review | Display timestamped utterances and allow human speaker labels without changing the original transcript or provider speaker IDs; seek to the audio evidence. |
| 17 | Context preference | Display the actual preference used for each generated document, separate from subsequent settings changes; local verbatim assembly must not imply filtering. |
| 38, 41 | Owner profiles and upcoming care | Show DOB/derived age and sorted due/upcoming care. Saved access lists only pets explicitly saved by this browser, never other pets inferred from matching contact details. Each saved grant remains separately revocable. |
| 40, 42, 46 | Discharge and media | Generate a downloadable PDF from approved notes, recorded medications and due reminders. Owner audio supports seeking. A manual message can include an explicitly generated, revocable owner link to approved documents/audio. No sending or WhatsApp reconfiguration. |
| 44 | Owner intake | Reject whitespace-only submissions, permit editing while awaiting review, prevent edits after acceptance, preserve versions and idempotent retries. Staff can accept once into the correct patient's sources. |
| 33 | Reminders | Create/edit/cancel/complete with date validation. Optional scheduled draft preparation respects clinic timezone, lead time, permissions and feature locks. Repeated runs create no duplicate drafts; changed/completed/cancelled reminders cancel unsent drafts. Delivery remains manual. |
| 49 | Morning handover | Optional schedule creates one persistent daily in-app handover per clinic after its configured local time; staff can open and acknowledge it. Restarts catch up once for the current day. No external messages. |
| 52 | Roles | Nurse can capture facts and manage appointments/reminders/intake; clinical approvals remain vet/admin. Upload/chunk routes enforce capture locks. UI exposes allowed actions and the server rejects direct unauthorized calls. |

## Explicit boundaries

This release does not claim the full hard-scope database migration, verified owner
identity, external automatic delivery, physical-device offline certification,
clinical transcription accuracy, a payment gateway, lab vendor connections, or the
25-minute refinement pipeline. Saved pet navigation uses explicit per-pet grants,
not a verified household identity. Scheduling produces staff-facing drafts and
in-app handovers; provider-confirmed WhatsApp delivery remains a later dependency.

The current single-instance deployment and its persistent SQLite workflows remain.
PostgreSQL continues to hold the patient spine. Additive changes must preserve
existing data and the live first-build lab contract.

## Verification and release

1. Regression and new acceptance tests against isolated SQLite and real local PostgreSQL.
2. Frontend type checks and production build.
3. Browser user journeys: patient/owners, timeline/source/chart, reminders/handover,
   owner intake and approved discharge/audio, recording recovery and roles.
4. GitHub CI before merge; Railway deployments must report the merged revision.
5. Same-origin hosted synthetic acceptance, including permissions, persistence,
   revoked links and duplicate processing. No real owner messaging or real clinical data.
6. Publish a report separating automated contract tests, real browser checks,
   hosted execution and remaining physical-device/provider limitations.
