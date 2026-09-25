# Synthetic administrative assistant acceptance

This run covers exact member-read restriction proposals and organization-request
withdrawal. Local regression tests use authenticated application APIs and a
stubbed intent model; they are not hosted or browser evidence.

## Provision only after verifying the isolated V2 service

The root operator must verify **Broby New**, Railway project
`ca389ebd-0186-4b7e-baec-8ddacdfc406b`, the backend service/environment and its
revision before running the service-side fixture script. It has no public route.
In the verified backend container, run:

```sh
python /app/scripts/provision-assistant-administration.py "$V2_ACCEPTANCE_ORIGIN" \
  --account "$V2_ACCEPTANCE_USERNAME" \
  --state /tmp/broby-assistant-admin-acceptance.json \
  --confirm-v2-project ca389ebd-0186-4b7e-baec-8ddacdfc406b
```

The script requires the same project ID in `RAILWAY_PROJECT_ID`, hosted password
mode and an HTTPS origin present in this service's configured allowed origins.
It requires an existing account with an active administrator membership, refuses
an existing state file, and generates fresh `synthetic-assistant-admin-…` IDs.
One transaction creates two marked, empty synthetic clinics with clinic settings,
a SOAP template and new administrator memberships for that existing account. It
creates no credentials and edits no existing clinic, member, organization or
membership. The state file has permissions `0600` and contains fixture IDs,
account name and prior membership identifiers; it contains no passwords.

Copy that state file to a private local path using the verified V2 service
connection. Preserve `0600`. The following phases use the existing acceptance
account's private credentials file through the normal same-origin APIs:

```sh
python scripts/smoke-assistant-administration.py "$V2_ACCEPTANCE_ORIGIN" \
  --credentials "$V2_ACCEPTANCE_CREDENTIALS" --state "$V2_ACCEPTANCE_STATE" --phase setup
python scripts/smoke-assistant-administration.py "$V2_ACCEPTANCE_ORIGIN" \
  --credentials "$V2_ACCEPTANCE_CREDENTIALS" --state "$V2_ACCEPTANCE_STATE" --phase review
```

Setup creates a **new** synthetic organization attached only to the new access
clinic, a new synthetic nurse without a login, and a pending request from the
new independent withdrawal clinic. Before each phase's writes, the script checks
the exact marked clinic, fixture tag, current administrator and account membership.
It never changes an existing clinic's adoption or an existing organization's policy.

Review first saves a proposal to restrict the new nurse's billing reads. It then
adds an inventory-read restriction to this new organization's empty policy and
proves the old saved proposal returns `409` from the effective-access digest guard,
with the nurse unchanged. It prepares a fresh billing-restriction proposal that
retains that inherited inventory restriction and displays all effective views.
It also prepares withdrawal of the new synthetic adoption request, preserving
its exact original consent. Setup and interrupted review use deterministic keys;
a lost organization-create or policy-change response can resume without duplicates.
No proposal is confirmed successfully by the review phase.

## Browser confirmation and a new-login readback

Sign into V2 with the same acceptance account and select the two new clinics by
their `SYNTHETIC Assistant Administration [tag] access/withdrawal` names. Refresh
or sign in again if newly provisioned clinic memberships are not yet listed.

1. In the access clinic, open Ask Broby's saved conversation for `tighten-access`.
   Review the exact synthetic staff ID, `read.billing` restriction, retained
   `read.inventory` inherited restriction and resulting view availability.
   Confirm the saved action. Leave `stale-access` unconfirmed.
2. In the withdrawal clinic, open the saved `withdraw-request` conversation.
   Review the exact new organization/request and original access consent.
   Confirm withdrawal.
3. Reload both conversations and inspect their completed saved reviews.

The private state file stores the exact conversation/turn IDs under
`turns.tighten-access` and `turns.withdraw-request`. Their command titles in the
browser begin `Set member…` and `Withdraw organization request…`; the older stale
proposal begins `Please Set member…`. Use the recorded conversation IDs and check
that the fresh review includes inherited inventory restrictions before confirming.

```sh
python scripts/smoke-assistant-administration.py "$V2_ACCEPTANCE_ORIGIN" \
  --credentials "$V2_ACCEPTANCE_CREDENTIALS" --state "$V2_ACCEPTANCE_STATE" --phase readback
```

Readback uses a new login, requires both successful executions to exist already,
compares the exact saved reviews, and replays only completed confirmations. It
checks the displayed restriction is stored, role/activity are unchanged, the
synthetic policy remains restrictive, the stale proposal has no execution, and
the withdrawn request preserves its consent while its clinic stays independent.
The fixtures remain for inspection with no customer data and no staff login for
the restricted nurse. Readback does not clear restrictions or widen access.

Only a root-run hosted script and observed browser workflow constitute hosted
acceptance. None of these synthetic checks establish clinic administrative policy,
real-clinic readiness, external provider delivery or access to real customer data.

## API-only fallback when verified service execution is unavailable

There is no public independent-clinic enrollment route. Invitation acceptance
attaches an account to an existing staff member; `organization.clinic_create`
always creates a child of the current organization. Do not change shared Railway
authentication or alter an existing clinic's adoption to bypass this boundary.

The existing organization master can instead prepare a **fresh synthetic child**
using ordinary authenticated APIs. Verify the hosted V2 identity and revision,
then set the existing parent clinic/actor/organization IDs and a new private state
path. Run each phase separately:

```sh
python scripts/smoke-assistant-access-only.py "$V2_ACCEPTANCE_ORIGIN" \
  --credentials "$V2_ACCEPTANCE_CREDENTIALS" --state "$V2_ACCESS_ONLY_STATE" \
  --parent-clinic "$V2_PARENT_CLINIC" --parent-actor "$V2_PARENT_ACTOR" \
  --organization "$V2_PARENT_ORGANIZATION" \
  --confirm-v2-project ca389ebd-0186-4b7e-baec-8ddacdfc406b --phase setup
```

Repeat with `--phase review`. Setup adds only one new child clinic and a new nurse
without a login. Review prepares a stale proposal, adds `read.inventory` only to
the fresh child's empty clinic locks, verifies stale confirmation rejection,
then prepares a fresh `read.billing` restriction. The organization policy,
parent clinic and existing staff/memberships remain unchanged. The script pins
its parent identity and policy, validates the exact fresh child name/IDs and
rejects existing-clinic retargeting. Interrupted child creation or lock changes
replay the same mutation key; successful browser confirmation is never automated.

In the browser select `SYNTHETIC Assistant Access [tag]`, open the saved fresh
conversation under `turns.tighten-access` (title begins `Set member…`), review all
effective access and confirm. Leave the `Please Set member…` stale proposal
unconfirmed. Repeat the command with `--phase readback` to require that saved
execution, compare its exact review and replay only the completed receipt.

This fallback establishes **member-access and stale clinic-version** acceptance.
It does **not** establish hosted organization-policy drift or independent adoption
withdrawal. Those remain separate local browser/API evidence until verified
service execution makes the full disposable fixture available. No restrictions
are cleared after acceptance.
