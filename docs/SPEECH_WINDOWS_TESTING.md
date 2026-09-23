# Speech windows release — 24 September 2026

## Behavior

After a saved recording is sent for transcription, the backend verifies its chunk manifest/checksums, decodes it and submits independent windows of at most 25 minutes. It checkpoints each completed provider response. A retry or recovered job reuses those responses, merges timestamps back onto the original audio, and attaches exactly one transcript source. The original bytes are preserved. A provider request that completed remotely immediately before a crash but was not checkpointed locally may still be repeated; this is not a guarantee of exactly-once provider billing.

Speaker separation is an explicit checkbox. Speaker numbers from different windows are distinct because provider numbering does not establish cross-window identity. Silent windows are retained in the window receipt metadata; silence does not discard speech in later windows. Text remains a machine transcript requiring review. No clinical corrections, diagnoses or prescriptions are generated.

This is completed-note processing, **not continuous refinement during recording**. Supported decoding: WebM, MP4, WAV, Ogg, FLAC and MP3, capped at four hours and 512 MB for backend processing; the existing browser import cap remains 100 MB. Local FFmpeg is required; the Railway Docker image installs it. The decoder accepts local binary audio, rejects playlists/URLs and uses private bounded temporary files, which are removed on success/failure. Provider timeouts and job lease recovery remain bounded by the existing job system.

No database schema migration, Redis service, extra key or new permission is required. The new checkpoint is held in the existing durable job result, and final window receipts are held on the source record. Jobs remain single-instance with the current SQLite/file-store architecture.

## Automated verification

112 backend tests pass, including real PostgreSQL acceptance tests for the clinical spine. Most PMS/job tests use isolated SQLite. Thirteen added audio tests exercise real FFmpeg decoding and deterministic provider responses/failures:

- Browser WebM/MP4 and imported FLAC decode correctly with actual duration.
- Exact 25-minute boundary: decoded samples are neither skipped nor repeated; temporary PCM is removed and the original unchanged.
- Middle-window provider outage: persisted progress survives another worker invocation; only unfinished windows run, timestamps are offset and a single transcript source is attached.
- Silent first window; later speech retained; diarization disabled.
- Failed job reused and retry does not re-request completed windows.
- Stale lease cannot commit; revoked member cannot publish output.
- Playlist/URL-shaped input and modified chunk hashes rejected before any provider request.
- Oversize duration rejected without publishing truncated audio.
- Provider diarization flag, empty-window contract and invalid timestamp rejection.

Seven frontend recording fault tests, TypeScript and the Next.js production build pass. CI repeats the backend tests with PostgreSQL 18 and FFmpeg, builds/starts the API Docker image, and runs frontend checks.

```sh
.venv/bin/python -m pytest api/tests -q
node --test web/tests/*.test.cjs
node web/node_modules/typescript/bin/tsc --noEmit -p web
(cd web && node node_modules/next/dist/bin/next build)
```

## Live end-to-end acceptance procedure

Use only the isolated Broby New deployment. Generate a synthetic recording with a spoken “blue marker” before 25 minutes and a “green marker” after 25 minutes. The runner creates a labelled synthetic patient/consultation, uploads the original, calls the real configured speech provider and verifies both markers, two window receipts, global timestamps, one attached source, unchanged original bytes and disabled messaging. Credentials are read from the ignored local file and are never printed.

```sh
.venv/bin/python scripts/smoke-speech-windows.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --audio .local/synthetic-speech-windows.flac \
  --state .local/speech-windows-hosted.json

# After deployment/restart: reads only, no new provider call or test records.
.venv/bin/python scripts/smoke-speech-windows.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/speech-windows-hosted.json --verify-only
```

Browser acceptance: open that synthetic consultation, confirm the speaker checkbox, open Transcript, review both windows and select a timestamp after 25:00 to seek the original audio. The UI must label speaker identity limits and machine transcript review. Test a second browser-imported synthetic note with speaker separation disabled. Record the actual results and deployed commit separately; a passing procedure description is not evidence that it ran.

This does not validate physical microphone capture, simultaneous device handoff, multilingual/clinical accuracy, continuous recording refinement, offline cold-start, live customer messaging or real payment/lab integrations.

## Recorded hosted result

PR #7 was merged and deployed to both Railway application services at `4e53ca4d72d62d631e5e8a51028b3ad9de7e5fc9`. PR/main CI passed all 112 backend tests, seven recording tests, TypeScript, frontend build and API container startup. The live generated 1506.478-second fixture passed all nine checks with real Deepgram requests, including both spoken markers, exact 1500-second split, global audio timestamps and byte-identical original retention. A fresh connection passed all eight read-back checks. Another 30 existing hosted security/clinical/workflow persistence checks passed on that revision.

The hosted browser displayed the two-window transcript and per-window speaker IDs. Deepgram rendered the product name “Broby” as “Bravi”; the original audio and machine-transcript label make that inspectable. This test proves the processing path and receipts, not transcription accuracy for clinical speech. A consultation header also exposed an old unset-weight display (`0 kg`); the follow-up UI correction displays “Weight not recorded,” consistent with the patient screen.
