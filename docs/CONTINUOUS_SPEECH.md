# Continuous speech refinement

With automatic transcription enabled before Record, Broby stores every original
browser chunk locally and uploads a contiguous prefix after the first 25 minutes.
Completed 25-minute sections appear as a clearly marked preview while capture
continues. Finish uploads the remainder and automatically attaches one transcript.
Language and speaker separation are fixed when the note starts. Imported files
and notes captured with automatic transcription off keep the manual Transcribe
workflow. No new provider, service or credential is required.

The original is never replaced. A preview is not a source and cannot be assembled
into a clinical note. Final decoding must exactly match the decoded bytes of every
previewed section before any source is published. Speaker labels stay separate
per section. Machine speech still requires review against the original audio.

## Recovery and boundaries

- Immutable checksummed chunks and contiguous manifests protect the original.
  Local chunks are deleted only after the complete manifest is acknowledged.
- One durable job follows the recording. Finish/appends arriving during a provider
  request schedule the next pass without losing progress or producing another source.
- Completed sections are checkpointed with a decoded-audio hash and provider
  receipt. Retries reuse them; stale workers and revoked members cannot publish.
  A remote response lost before checkpointing can still cause a repeated provider
  request and charge. This is not exactly-once provider billing.
- Preview decoding permits an unfinished container tail, holds back two seconds,
  and waits when packets are not decodable. Final decoding is strict. Browser
  upload checks run every 15 seconds; a pending section retries at most once a
  minute. Once a section is saved, decoding waits for the next boundary.
- Offline capture continues locally. Reconnection uploads completed sections;
  finishing offline keeps the entire queue for retry. A failed job requires an
  explicit Retry saved sections. Capture itself continues independently.
- Limits remain four hours / 512 MB server processing, 100 MB browser imports,
  single backend worker/replica. This does not implement offline cold launch or
  encrypted device storage, certify clinical accuracy or validate every physical
  browser/device. Some containers expose no preview until complete packets arrive.

## Verification

Eleven added backend scenarios exercise real WAV/WebM/fragmented MP4 decoding,
preview isolation, exact decoded-byte reuse, concurrent Finish, provider retry,
permission/lease revocation, gaps/checksums, silent sections and incomplete media.
Fourteen frontend fault tests include active upload, Finish/upload races, offline
recovery, storage gaps, cleanup failure, pause timing and avoiding repeated work.
The complete backend suite has 161 tests. TypeScript and the production build pass.

Reproducible live provider acceptance uses only a synthetic growing WebM fixture
with a blue marker before 25 minutes and a green marker after it:

```sh
.venv/bin/python scripts/smoke-continuous-speech.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/continuous-hosted.json \
  --phase preview --audio .local/continuous-speech.webm --prefix-bytes <packet-offset-after-1502-seconds>
# Inspect the open recording and preview in the authenticated browser.
.venv/bin/python scripts/smoke-continuous-speech.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/continuous-hosted.json \
  --phase finish --audio .local/continuous-speech.webm
# Fresh read-only confirmation, including after restart/deployment:
.venv/bin/python scripts/smoke-continuous-speech.py https://frontend-production-1283.up.railway.app \
  --credentials .local/hosted-access.json --state .local/continuous-hosted.json --phase verify
```

This fixture replays growing audio through the real API/provider; it does not
represent a physical 25-minute microphone session. Record the executed hosted
results and deployed revision separately before marking the release verified.

Browser timing is a scheduling hint, not the authoritative audio duration.
[MediaRecorder chunk timing is not exact](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/dataavailable_event);
server decoding establishes each sample boundary and the final duration.


## Executed hosted acceptance — 24 September 2026

PR #12 deployed to both Railway services at `7a87357d117c778ce434fb1a07247a7aba9fe125`.
Eight real-provider preview checks and ten final checks passed. A 1503.0135-second
WebM prefix produced the first 1500-second preview while its recording stayed
open and the consultation had zero sources. Appending the tail produced a
1506.4783125-second final recording and exactly one transcript source. The first
window retained the identical provider request ID and decoded-byte hash; both
spoken markers, the 1500-second boundary and unchanged original bytes passed.
A repeated final upload confirmation succeeded after decoded duration changed.
Private evidence: `.local/continuous-hosted.json` and the preview/finish logs.

The deployed browser showed the preview with its provisional warning and zero
Sources, then changed automatically to one final machine transcript with both
markers and separate speaker labels. Selecting the 25:00 receipt opened playback
of the original tail. No browser warnings/errors were reported. The provider
spelled the synthetic product name “Broby” as “Bravi”, so this is workflow evidence,
not an accuracy certification.

An isolated browser harness also ran the actual `recording.ts`, browser
MediaRecorder and IndexedDB against a generated tone: 11 seconds of active audio,
three WebM/Opus chunks, pause time excluded, one complete manifest and local
cleanup after acknowledgement. Its upload endpoint was simulated; the hosted
fixture above separately exercised the real server/provider. No ambient
microphone audio was captured. Physical microphone and long-running mobile
acceptance remain unverified.


### Fixture clinic binding (2026-09-25)

The staged acceptance state now pins the host, clinic and actor. Adding another clinic can change the login default, because login chooses the first clinic identifier in sorted order. Existing recordings must never follow that changing default.

A legacy state without binding is recovered only after exactly one active authorized clinic proves the saved recording, patient, consultation and (when saved) transcript-source relationship through a read-only history request. The verified binding is persisted atomically with private file permissions. Ambiguous/missing identity, changed membership, partial state or a different host fails closed. New previews require a fresh state path. Current clinical holds/read restrictions are checked independently; locating preserved history never makes it available for current use.

The September 25 old-fixture failure was reproduced as login-default drift: the fixture remained in clinic-east, while a newly created synthetic clinic became the login default. Read-only checks found all original fixture records, a completed job without reconciliation qualification, and the exact original audio checksum in clinic-east. The corrected verify phase passed using a private copy of the legacy state, with no audio upload, clinical changes or new speech-provider request. The original state remains available for comparison.
