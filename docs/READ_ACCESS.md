# Read permissions

Clinic feature locks now include eight named read capabilities: patient/owner
identity, clinical records, billing, inventory, scheduling, communications, staff,
and reports. Administrators can restrict one member with an optimistic version
check and a recorded reason. Clinic-wide locks apply to vets/nurses; inherited
organization locks apply to clinic administrators too. The organization master
retains recovery access. Nobody changes their own individual restrictions.

The server filters bootstrap records and jobs, checks every staff API route, and
removes dependent write actions. A retried mutation must still pass current access
before receiving its saved result. Unknown record kinds are withheld from
restricted members; an unclassified new API route fails closed. Owner capabilities
and signed provider callbacks keep their separate existing authorization.

Mixed event histories, source receipts, files/audio, transfers, saved assistant
conversations, archives and full reports may contain copied facts from several
areas. They require all eight capabilities. This is deliberately conservative:
there is no claim to redact individual sentences inside old notes or files.
Patients, typed measurements, invoices, inventory and appointments have separate
read boundaries. Existing downloaded files cannot be recalled.

The browser remounts views when current permissions change, so a selected invoice,
old modal or saved AI result cannot remain visible after the next successful
six-second workspace refresh. Restricted views explain the required access instead
of reporting misleading zero balances. Own password/authenticator controls remain
available. An observed policy change prevents fallback to an older encrypted cache,
even when storing the replacement fails. Disconnected devices retain their last
verified access until the existing session lease expires, at most twelve hours;
instant offline revocation is not claimed. Unsynced work is retained encrypted.

## Acceptance

50 dedicated regression cases cover all capability filters, direct endpoint
bypasses, inherited locks, administrator exports, mutation replay, assistant
history, stale changes, cross-clinic access, unknown record kinds and preservation
of unrelated member fields. The frontend quota-failure regression proves the old
cache is not reopened after a newly observed policy change.

Isolated password-authenticated browser acceptance uses real PostgreSQL and a
production frontend: administrator saves a vet restriction, vet signs in, billing
is denied and patient search remains usable; restoring access updates the open
session; revoking access while the invoice is visible removes it without a reload.
After a backend/frontend restart, restrictions and all 65 unrelated original
records remain exact. Browser error log was empty.

`scripts/smoke-read-access.py` runs a repeatable credentialed acceptance flow using
a new synthetic member, then deactivates that member. It verifies twelve direct
bypass paths, disabled writes, fresh-session persistence and unchanged original
records. Use `--verify-only` on an existing state file. It never sends a message
or makes a payment. Hosted execution and exact release/deployment receipts are
recorded after deployment, separately from the local evidence.
