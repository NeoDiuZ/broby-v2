# Conditional workspace refresh

Visible tabs still check the server every six seconds. A signed-in request may
send the opaque revision of its current, in-memory clinic snapshot. The server
authenticates the session and active membership and recomputes effective read and
write permissions on every request. The revision is bound to the exact clinic,
actor, permissions, memberships, clinic metadata, provider availability, latest
twenty jobs, current native clinical representation and PMS record revision.
It grants no access and is not an HTTP or shared response cache.

When all those values match, the API returns an `unchanged` response instead of
materializing every PMS record. The browser keeps its existing records, continues
syncing pending notes and avoids encrypting another copy of identical data. A
failed device cache save is retried even after an unchanged response. Missing,
foreign or unexpected tokens require a full read. Reconnection after a failed
read also forces a full verification. Existing offline lease expiry, encrypted
unsynced notes/audio and policy-change rejection of an older cache are preserved.
An unchanged response does not renew the offline lease or saved-copy timestamp.

Record INSERT, UPDATE and DELETE triggers advance a durable per-clinic revision
inside the same write transaction. A clinic move advances both clinics. The
revision, policy metadata and PMS payload are read in one consistent transaction;
a concurrent commit cannot stamp unseen data with a newer revision. Rollbacks do
not advance it. Job rows and native clinical rows are read afresh, so direct job
transitions, native ingest, approval, observation, source and concept changes do
not depend on a PMS mutation hook. An API process identifier invalidates tokens
after restart or restore. Different API processes can cause extra full reads;
this does not claim an efficient shared cache across replicas.

If a mutation asks to refresh while an older request is in flight, the browser
waits for a follow-up read. An old clinic response cannot replace a newly selected
clinic. Authorization failures clear the view and revoke offline access through
the existing device boundary. Each group of waiting callers finishes after its
own read; continued polling cannot keep an earlier action waiting indefinitely.

## Reconciliation fallback and limits

**Any clinical reconciliation review disables unchanged shortcuts across the
entire deployment.** Retained originals and accepted onward provenance can change
eligibility across clinics and stores without a local record or ledger update.
An indexed existence check therefore forces the complete, fresh eligibility and
bootstrap path whenever any review exists. A hosted reconciliation fixture also
activates this guard; no hosted scale improvement is claimed where it is active.
The shortcut does not use a global eligibility cache or assume that a ledger ID
closes those dependencies.

Cold bootstrap, changed snapshots and reconciliation-guarded reads still load the
full clinic. Native clinical rows are still read on every poll. Full bootstrap
pagination, database-paginated assistant results, native invalidation and broader
load/soak acceptance remain unfinished. This change reduces repeated unchanged
PMS reads; it does not complete feature-status items 9 or 24 or certify hosted
clinic capacity.

## Acceptance

`test_bootstrap_refresh.py` seeds 5,000 synthetic patients, verifies a full response
over 2 MB, then proves repeated responses stay under 150 bytes and never call the
full PMS record loader. SQLite and PostgreSQL tests cover committed concurrent
writes during reads, rollback, insert/update/delete/move, both move scopes, read
revocation/restoration, inherited policy changes outside the records table,
session/membership/logout boundaries, changed jobs, process restart and the
deployment-wide reconciliation fallback.

`test_bootstrap_native_refresh.py` uses real PostgreSQL ingest and changes native
approval, source content, observation value and concept label without advancing
the PMS revision; each invalidates the token. Native deletion does too.

Frontend regressions execute the actual workspace refresh path with deferred
requests. They verify mutation follow-up, clinic switches, pending-note sync on
unchanged responses, failed-cache retry, offline fallback/reconnection, rejected
authorization and scoped token recovery. The existing device suite separately
verifies authenticated encryption, exact audio bytes, lease expiry and rejection
of older snapshots after a permission change and quota failure.

The PostgreSQL connection boundary lets psycopg start transactions once, setting
repeatable-read isolation before the first snapshot query. Actual server tests
check isolation, timeouts, rollback, blocked serial writers and the absence of
duplicate-BEGIN notices. No writer-lock or read-isolation guarantee was removed.


### Root browser acceptance — 25 September 2026

A disposable local PostgreSQL clinic at integrated revision `2f9b242` contained
1,084 records, including 1,000 additional synthetic patients. The veterinary
account's cold response was 888,371 bytes; an unchanged response was 105 bytes.
The root operator edited a synthetic patient in Chrome; the revised name appeared
immediately and independent API readback showed revision 2 and a changed token.
A separate synthetic administrator session then restricted only that vet's
billing access. Returning the existing Billing tab to the foreground triggered
a fresh authorized read and replaced it with “Access restricted”; independent
readback contained zero billing records, compared with two before restriction.
The fixture contained no reconciliation review. This local acceptance does not
claim the shortcut runs in a hosted deployment after reconciliation is exercised.

## Whole-workspace pagination assessment

The source specification already has cursor/limit patient and timeline APIs.
It gives no whole-workspace pagination or clinic capacity threshold. Full-bootstrap
pagination remains scaling work, not a missing named read endpoint.

A disposable two-store probe showed why a local revision cursor is insufficient:
changing only original attachment bytes opens the correct clinical hold while
all PMS revisions and reconciliation ledger rows remain identical. A 5,059-record
PMS-only snapshot materialized 10,118 rows; repeating existing eligibility for 21
hypothetical 250-row pages materialized 106,239 rows, before native/page/HTTP work.
Native dependencies were stubbed empty: this is a lower bound, not a hosted
benchmark or implemented paging endpoint.

Genuine bounded paging needs an authoritative dependency/integrity read model
covering PMS, native and cross-clinic changes plus media integrity, bounded native
reads, and consistent snapshot assembly. Complete-clinic versus explicit downloaded
working-set offline availability must also be defined before changing 24 consumers
that currently expect complete snapshots. Superficial JSON chunking does not solve
backend or offline-memory scaling. Preserve the global reconciliation fallback
until those contracts are proven; hosted capacity remains unaccepted.
