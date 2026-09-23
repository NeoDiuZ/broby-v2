# Clinic workflows: release and test guide

The [acceptance specification](CLINIC_WORKFLOWS_SPEC.md) maps this release to all
five easy and fourteen medium audit items. This is a bounded workflow release;
external WhatsApp delivery, clinical speech accuracy, physical-device offline
certification and the hard-scope shared-database transition remain separate.

## Changed behavior

- Patients accept a validated date of birth and show derived age; estimated age
  remains available when DOB is unknown. Multiple owners are visible in Clients;
  a primary owner remains the contact. Ownership changes revoke existing pet links.
- X-ray and laboratory category aliases filter consistently. Timeline search also
  searches recorded text, and newly saved records refresh immediately. The clinical
  overview includes PostgreSQL-native laboratory measurements and source links.
- Voice notes can be named. Transcript speaker labels can be reviewed without
  changing machine evidence. Finalized manifests are immutable. Local storage and
  upload errors preserve retryable audio; byte ranges support owner audio seeking.
- Generated documents show the context preference used at request time. Verbatim
  assembly explicitly preserves all source text and does not claim AI filtering.
- Owners can save multiple explicitly granted pets in one browser. Each grant is
  independently checked/revoked. DOB, sorted due care, approved files/audio and a
  printable care PDF are available. Pending intake can be edited; accepted intake
  cannot be overwritten by the owner.
- Reminder edits, completion and cancellation invalidate unsent previous drafts.
  Optional scheduled preparation creates drafts, never sends them. Daily handovers
  can be scheduled in the clinic timezone, persisted once per day and acknowledged
  by each staff member. The current handover screen remains live.
- A care package can be prepared in Messages from approved records with a revocable
  owner link. Cancelling that draft revokes its link. Existing WhatsApp is untouched.
- Capture permissions and locks also apply to uploads/chunks and dependent actions;
  approval controls remain limited to vet/admin.

## Automated checks

From the repository root:

```sh
.venv/bin/python -m pytest -q --tb=short
cd web
pnpm test
pnpm typecheck
pnpm build
```

PostgreSQL tests create isolated, randomly named schemas and remove only those
schemas. They cover primary-owner projection, native lab overview, categories,
range boundaries, and upgrading an existing `0001` database without losing events.
The recording tests simulate network loss, storage quota failure, failed final
metadata persistence and overlapping recording attempts. These are fault-injection
contract tests, not certification of physical browsers or microphones.

Run same-origin acceptance against the local preview:

```sh
scripts/start-local.sh
.venv/bin/python scripts/smoke-workflows.py http://127.0.0.1:3100 \
  --state .local/workflow-local.json --audio .local/synthetic-speech.wav
```

For the hosted synthetic workspace, supply the private local credentials file:

```sh
.venv/bin/python scripts/smoke-workflows.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/workflow-hosted.json \
  --audio .local/synthetic-speech.wav
```

The script creates clearly named synthetic patients, notes, intake and recordings;
checks the real scheduler; restores schedule preferences; and leaves owner links
available temporarily for browser checks. It never sends messages. With an audio
file and configured speech provider, it makes one real transcription request.
State files contain access capabilities: keep them private and out of Git.

After browser testing, revoke the test links and check persistent state:

```sh
.venv/bin/python scripts/smoke-workflows.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/workflow-hosted.json --close-links
```

Use `--verify-only` on the same command after a deployment/restart. Synthetic
records remain as reproducible evidence; cancelled drafts are not deliveries.

## Browser acceptance walkthrough

1. Home → New patient: create a clearly named synthetic patient with a DOB. Verify
   age/DOB in its record. Edit the DOB; try a future DOB and confirm rejection.
2. Patient → Manage owners: add another synthetic owner. Verify both in Clients
   and confirm the primary contact remains correct. Create fresh sharing links
   after any ownership change.
3. Patient → Record: create an X-ray note. Filter X-ray, search a phrase from its
   body and open the original source. Add a lab result using the test script;
   Reports → Clinical record overview must include it and its supplied range.
4. Consultation: import synthetic audio, rename it and transcribe if enabled.
   Open Transcript → Review speaker labels. Label a speaker and replay its timestamp.
   Assemble/approve a synthetic note and inspect the context-preference notice.
5. Messages → Reminders: create, edit, cancel and complete synthetic reminders.
   Settings → Clinic → Scheduled clinic preparation (admin): enable drafting,
   wait for the next 30-second tick, verify one draft, then restore the setting.
6. Handover → Prepare today's handover: open its snapshot, acknowledge it and
   reload. The acknowledgement remains; the live handover remains current.
7. Messages → Compose message: select a synthetic patient and prepare an approved
   care package. Review its link, documents and audio; do not send it to an owner.
8. Open a synthetic owner link. Save access; repeat with another pet's link.
   Switch between Saved pets. Submit intake, edit it while pending, and accept it
   in the clinic Handover screen. The owner can no longer edit the accepted entry.
9. Download care instructions; verify approved text and medication instructions.
   Play/seek shared audio. Revoke the test grant: data, PDF and media must all deny
   further requests while the separately granted second pet remains available.
10. Local preview → Settings → Preview as nurse: verify capture/reminder/intake
    actions work while clinical approval and sharing controls are unavailable.
    Server tests also call forbidden routes directly and assert rejection.

## Release boundary

Schedule switches default off. Railway hosts the existing authenticated synthetic
workspace. The additive PostgreSQL migration adds only primary-owner metadata and
invalidates derived projection checkpoints; original records are retained. The
existing single-instance worker/data-volume deployment remains required.

The owner PDF and care package cover approved PMS records. PostgreSQL-native lab
sharing still depends on the later unified record/approval work. The new clinical
overview covers native labs, but this release does not claim that every assistant,
owner or financial reader has already moved to PostgreSQL.
