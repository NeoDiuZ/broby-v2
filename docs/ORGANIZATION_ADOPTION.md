# Joining an existing independent clinic

An independent clinic administrator can request to join an organization in
Settings → Organization and master policies. Obtain the organization ID from the
master, preview the exact clinic/organization names and inherited restrictions,
and explicitly confirm administrator access for the master. The request exposes
only the administrative request and workspace record counts for review. It grants
no cross-clinic record access. Requests expire after seven days and can be
withdrawn by a current clinic administrator.

The organization master reviews the request and current record counts, then
accepts or declines with a reason. Acceptance creates one administrator membership
for the existing master account, or reuses its existing active administrator
membership. It never silently upgrades a restricted or inactive membership.
Existing clinic staff, patient IDs, records, stock, balances and settings remain
unchanged; this attaches the clinic and applies inherited feature restrictions.
It does not merge patients or migrate data between clinics. The master must have a
password account. Newly added clinic memberships require a fresh sign-in before
encrypted offline work is available there; online access can be used immediately.

## Checks at the shared write boundary

- Active administrator authority, clinic independence and the organization master
  account are verified. No global clinic or patient directory is exposed.
- The clinic confirms a digest of clinic identity/version and exact organization
  identity/master/policies. Changing these requires a fresh clinic request.
- The master confirms a fresh review digest, including current workspace counts.
  Intervening writes that change those counts require another master preview.
- Expired, withdrawn, declined, accepted or stale requests cannot be accepted.
  The original requesting administrator must still be active and authorized.
- One transaction attaches the clinic, adds/reuses the master membership, closes
  the request and writes audit receipts for both sides. Same-key replay is safe;
  concurrent approvals cannot duplicate memberships. Exceptions roll back all of it.

Accepted adoption is a governance change, not a reversible patient-data transfer.
There is no self-service detach or organization ownership transfer in this release.
The reviewing administrators must understand the displayed access grant. Workspace
counts cover the current PMS records, not an exhaustive PostgreSQL clinical audit.

## Verification

27 regression cases cover consent, roles, scope, stale clinic/policy/counts,
expiry, requester revocation/demotion, pending duplication, withdrawal/decline,
replay, concurrent acceptance, rollback and existing restricted memberships.
A password-authenticated local browser test used separate independent-clinic and
master accounts. Before acceptance, target-clinic access returned 403. After
acceptance, master clinic switching worked, all 14 original records were exact,
one membership was added, original staff stayed intact, the inherited message lock
applied, and the independent administrator still could not read the master clinic.
A fresh master sign-in enabled the new clinic's encrypted device copy without
browser errors. Restart readbacks and final checks are in the release receipt.

Hosted acceptance does not attach any existing clinic: the accessible hosted
clinics already belong to an organization. Deploy verification covers authenticated
routes, permission errors and unchanged existing organization membership. The full
mutating adoption acceptance above uses isolated synthetic data and real local
PostgreSQL. A real independent clinic's administrator must request adoption through
this workflow; no clinic is attached merely to produce a test result.
