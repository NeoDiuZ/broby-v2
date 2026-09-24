# Offline device workspace

Broby must reopen its clinic shell after a lost connection, unlock previously
saved authorized clinic data, retain typed notes and original audio on the device,
and synchronize through the same authorized/idempotent server actions after
reconnection. Offline data is a dated snapshot; clinical approval, payment,
prescribing and administration still require the server.

The device vault uses AES-256-GCM and a random data key wrapped using a
PBKDF2-SHA-256 key derived from the existing account password. The password and
unwrapped keys stay in memory. A reload requires unlocking. Each record is bound
to its store and account by authenticated encryption, including audio bytes,
drafts, pending commands and snapshots. Password changes rewrap the same key
using the previous device password; queued work is never silently discarded.

Offline access is bounded by the last verified online session, at most 12 hours.
Remote revocation cannot be learned while disconnected; reconnecting must check
the session/membership before syncing. Explicit sign-out removes offline access
while retaining encrypted unsynced work for the same account's next online login.
This does not protect against malicious same-origin code, a compromised unlocked
browser/OS, or a user deliberately altering their own client clock/code.

The service worker stores only the app shell and versioned static code/assets;
API responses, authentication, owner links and clinical media are never placed
in its HTTP cache. Updates do not reload a recording tab. Clinical data goes only
through the encrypted IndexedDB store. Browser eviction or manual site-data
clearing can still lose unsynced work; this cache is not a backup.

Legacy plaintext queues are migrated only for original clinic/actor pairs proven
by an online login. Unmatched older work is retained for its original account to
recover, never adopted/deleted by a different user. Its migration must be completed
before claiming the whole browser has no legacy plaintext. Snapshot eviction
must not remove pending audio, notes or draft edits.

Acceptance must cover real WebCrypto/IndexedDB persistence, wrong password,
wrong account, altered ciphertext, key rewrapping, expiration, revoked access,
legacy migration/no loss, storage failure/write ordering, offline cold reload,
queued typed-note synchronization and exact audio replay. Hosted acceptance must
verify the deployed build and live authenticated data flow. The overall requirement remains partial pending the full physical-device/browser
crash and eviction matrix.

References: [WebCrypto key derivation](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/deriveKey)
and [service-worker caching](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Caching).

## Verified acceptance — 24 September 2026

The backend suite passes 379 cases and browser-side suites pass 36 cases. New
coverage exercises real WebCrypto with IndexedDB semantics: ciphertext binding,
wrong passwords/accounts, old-password rewrapping, expiry/clock rollback,
revocation/relogin, legacy migration, quota failure, write ordering, snapshot
retention, and recording lock guards. Worker tests check public-shell fallback,
network-only API/auth/owner routes, static allowlisting and scoped cache updates.

An isolated password-authenticated production frontend/API was stopped entirely.
The browser cold-opened the app, rejected a wrong device password, unlocked the
saved consultation, recovered its draft and queued a typed note and synthetic
WAV. Browser diagnostics found encrypted queue rows, no clinical plaintext
markers and no clinical/password localStorage values. After reconnect/sign-in,
exactly one source note and one saved recording appeared. API readback confirmed
all 64,044 original audio bytes by SHA-256 and all 66 unrelated records unchanged.
The final build passed two consecutive offline reload/unlock/draft-recovery checks.
No microphone or simultaneous physical-device handoff is claimed by this test.

Settings → Sync & jobs shows offline readiness, expiry, queue count, legacy
migration warnings and device lock/copy controls. Lock/sign-out cannot discard
an active recording or audio still held only in memory. Failed actions display
their reason. Server actions require reconnection; offline clinic copies are dated.
An online session probe completes before login/unlock can run, avoiding a stale
session response revoking a newly unlocked device. A new online login locks other
Broby tabs on the same origin; signing out revokes device access.

To test safely, use a synthetic consultation, wait for “Saved on device” and
“App shell ready for offline reopening”, disconnect the test frontend/API, reopen
`/app`, unlock with the last verified password, and save a note. Reconnect and
check one source receipt/recording and an empty local queue. Do not disconnect
V1 or use customer audio for fault-injection testing. Browser eviction, device loss,
unsupported private browsing and forgetting the previous device password can
prevent recovery; server archives and successful synchronization remain necessary.

Exact hosted release and verification evidence is recorded in
`.local/reports/broby-offline-release-2026-09-24.md` after deployment verification.
