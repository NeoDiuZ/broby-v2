# Earlier web preview guide

The PostgreSQL first-build changes in FIRST_BUILD.md supersede the storage and backup descriptions below.

# Broby v2 — local working preview

A separate codebase for reviewing the v1-inspired interface and the first v2 patient-record and clinic-operation workflows. The original `BrobyProduction-main` checkout is unchanged.

**This is not the completed v2 replacement or a production deployment.** It uses synthetic data, a local role selector, SQLite, deterministic record retrieval and verbatim note assembly. Optional Deepgram and Anthropic adapters are implemented and mock-tested, but no live providers are configured. Password sessions, owner pre-consult intake, calendars, PDFs and backup/restore are now available. Native mobile and the extension are deferred. Exact remaining work is listed in [feature status](docs/FEATURE_STATUS.md).

## Open locally

- Workspace: http://127.0.0.1:3100
- Live-design website preview: http://127.0.0.1:3101
- API reference: http://127.0.0.1:8100/docs

Run from this directory:

```sh
./scripts/start-local.sh
```

The script starts only missing local services, uses the installed production builds, and stops only its own processes on Ctrl-C. Node 20.9+ and Python 3.12+ are needed; on this computer it also detects Codex's bundled runtimes. It never deploys or contacts production. Existing services started by Codex remain independent of the script.

If dependencies or builds are missing:

```sh
./scripts/setup.sh
./scripts/build.sh
./scripts/start-local.sh
```

## Try the workflows

1. Open **Patients → Luna → Visits → Appetite follow-up** to inspect the browser-tested consultation and its receipt. Start another consultation to try note entry, assembly, editing, approval, and draft recovery.
2. Search **Bella** to see two distinct animals with independent owners and histories.
3. Open **Olive → Observations** for a measured result flagged against its supplied reference interval. No diagnosis is inferred.
4. Open a patient's **Owner access** to inspect a seven-day private preview link. Approve files explicitly in **Documents** before they appear there.
5. Explore **Billing**, **Inventory**, **Templates**, **Messages**, and **Reports**. Payments record money received elsewhere; they do not charge a card. Sending a message requires your manual action; queueing never sends it.
6. Use **Settings → Clinic → Preview as** to test veterinarian, nurse and administrator permissions. Switch clinics in the header. These are simulated identities, not authentication.
7. Under **Settings → Team & access**, use administrator mode for memberships, feature locks and the audit list. Under **Data & migration**, preview and commit a patient CSV.

Microphone capture requires your browser's permission. Audio uploads are numbered and checked for missing chunks; note drafts and pending audio are retained in this browser's IndexedDB. An unexpected browser shutdown can lose the last unflushed recorder segment; recovered recordings are flagged for review. Offline support covers an already-loaded workspace, note drafts and audio queues, not a guaranteed cold launch without the local frontend server.

## State and storage

- `api/data/broby.sqlite3`: local records, durable document jobs, idempotency responses, audit entries and owner grants.
- `api/data/audio`: numbered audio chunks; `api/data/files`: attachments.
- Browser IndexedDB: unsent notes and audio. Browser local storage: identity selection, cached records and text/document drafts.
- `BROBY_DATA_DIR` can select another API data directory. An empty directory receives synthetic seed records. Back up the whole directory with the server stopped if you want to retain files as well as records.
- CSV migration imports patients/owners; lab CSV imports source-linked numeric results. Structured clinical JSON validates references and rejects existing IDs. Settings offers a ZIP backup containing records, revision history, ontology, audit, attachments and audio. Restore into an empty directory with `.venv/bin/python api/restore_backup.py backup.zip /absolute/empty/destination`. Credentials, owner access grants, browser drafts and job/mutation queues are excluded; provision credentials again and issue new owner links.

The API binds to loopback. Do not expose these preview servers to a network or put real client records into the demo: the role headers/default identity are test controls, owner links are local capability previews, and optional password sessions have not had production hardening, and encryption, legal retention automation and managed backup operations are not implemented.

## Validation

```sh
.venv/bin/python -m pytest -q
./scripts/build.sh
```

39 backend regression tests cover identity isolation, idempotency, stale jobs/edits, source ownership, permissions, transactional stock/payments/imports, appointment overlap, owner grants/files, feature locks, audio gaps and numeric validation. TypeScript and both Next.js production builds pass. Browser verification covered each navigation section, the note → document → edit → reload → approval flow, and the dashboard at 390px width.

Browser verification also covered calendar booking, owner intake through Handover into a patient receipt, and lab CSV results. PDFs were rendered and visually checked. Actual microphone permission/capture, external AI and provider integrations have not been verified. Native mobile and extension work is deferred. The Python test runner emits one upstream Starlette/AnyIO deprecation warning.

See [architecture](docs/ARCHITECTURE.md) and [feature status](docs/FEATURE_STATUS.md) for exact boundaries and next implementation work.

Website correction (2026-09-23): the main-branch website differed from brobyvets.com. The homepage now serves `website/public/live/index.html`, captured from the live site with its local image/sprite assets. Fonts use the live Google Fonts stylesheets. Sign-in points to the local app and onboarding saves only a local draft. Original repository subpages remain, so this is not a mirror of all live legal/contact pages.


## New web workflows

- **Clients**: create/edit contacts, link patients, and merge duplicate owners as an administrator.
- **Appointments**: day/week/month views, clinician filter, rescheduling and recurring series.
- **Handover**: review owner submissions, accept them as patient source notes, and prepare due-reminder drafts.
- **Patients → Observations**: typed observations, trends, and atomic laboratory CSV imports (`name,value,unit,low,high`).
- **Consultation**: revision history, PDF export, optional transcript speaker timestamps and excerpt organization; omitted source text remains visible for review.
- **Billing/Inventory**: invoice PDFs, recorded refunds/voids and stock receipt metadata.
- **Owner view**: intake, recorded-care retrieval, approved audio, referral links and saved browser access. Saved access is not verified owner identity.

## Optional provider and password configuration

Copy `.env.example` to `.env` and set values locally. `BROBY_ENABLE_AI=1` plus `DEEPGRAM_API_KEY` enables explicit transcription requests. `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` enable source-excerpt organization and assistant intent parsing. This sends selected records/audio to those providers when the operator requests the feature. No keys are embedded in browser assets. Without configuration, local verbatim assembly and record search remain available.

For local password sessions, provision an account from the API directory:

```sh
../.venv/bin/python auth.py create --username clinician --clinic clinic-east --member clinic-east-vet
# Optional additional clinic membership for the same account:
../.venv/bin/python auth.py link --username clinician --clinic clinic-river --member clinic-river-vet
```

The create command prompts privately for a password of at least 12 characters. Set `BROBY_AUTH_MODE=password` in `.env`, then restart the API. Password mode uses server-side membership and ignores the demo actor header. Session cookies expire after 12 hours. It remains a loopback development service, not an internet deployment.
