# Staff rota and booking acceptance

Appointments and Settings → Clinic both expose **Staff rota and rooms**. All
signed-in clinic staff can inspect a seven-day rota. Administrators with the
`schedule.configure` permission can edit it; inherited organization locks apply.

The editor keeps all seven weekdays and all staff in one versioned draft. Add up
to eight shifts per day; gaps represent breaks. A staff member without a weekly
restriction remains bookable subject to existing booking/room checks. Turning on
weekly shifts makes days without a shift unavailable. Dated changes replace the
weekly hours for that date: no shifts means leave; supplied shifts mean replacement
hours. A 3–500 character reason is required. Removing a dated change restores the
weekly rule. Times and the default displayed date use the clinic timezone. Windows
must start before they end on the same date; overnight shifts are not supported.

**Review rota changes** checks the proposed rooms and shifts against scheduled and
arrived appointments from the clinic's current date onward. It lists conflicts
without changing any booking. Move or cancel those appointments in Appointments
before saving. Completed/cancelled and past appointments remain historical and do
not block future rota editing. The save repeats these checks inside the same
write transaction used to create appointments, preventing a concurrent booking
from being stranded. Stale schedule versions fail; close and reopen the editor to
load a new version. Background refresh never replaces an open draft. An uncertain
save can be retried with the same idempotency key.

The shared action `schedule.configure` stores rooms, weekday availability and
`date_overrides`. Omitted fields retain their saved values, including dated leave
when an older caller submits only weekly availability. Configuration history and
actor audit remain available. Create, reschedule, recurring series and reopening
an appointment all enforce the same effective shifts. New appointment date/time
input must be a calendar date and a local HH:MM time, with no UTC offset or seconds.

Read-only APIs:

- `POST /api/schedule/preview`: administrator authorization, normalization, version
  check and conflict list; no persistence.
- `GET /api/schedule/rota?start=YYYY-MM-DD&days=7`: clinic-scoped effective shifts,
  source (`weekly`, `exception`, `unrestricted`) and reason; 1–42 days per request.

Configuration limits: 100 unique room names (up to 100 characters), 500 staff with
rules, 5000 dated changes across the clinic, eight non-overlapping shifts/day.
This remains the current single-backend transactional SQLite PMS architecture.

## Acceptance

`api/tests/test_scheduling.py` covers split shifts/breaks/day-off, dated replacement
precedence, omitted-field preservation, normalized times, malformed dates/windows,
role/clinic/master-lock boundaries, preview without writes, bookings made after
preview, simultaneous booking/configuration, room removal, stale versions,
idempotency/audit/history, clinic-local date cutoff, terminal/past appointments,
and atomic recurring/reschedule/reopen failure. The earlier room-collision test
now uses its own clinician so it does not strand seeded appointments.

Browser and hosted release results are recorded in RELEASE_WORK.md when verified.
Cancellation fees, no-show rules, payroll, deposits and clinic policy decisions
are not inferred or implemented. Reviewed leave and effective periods are
implemented in the extension below.

## Effective periods and reviewed leave

Administrators can add dated weekly rota periods (inclusive start/end dates) for
individual staff. Periods cannot overlap. Empty weekdays within a period mean a
day off; outside a period the base weekly rule applies. Dated changes override a
period, while approved leave takes priority over both. The same precedence is
used by the rota reader, create/reschedule/reopen/recurring booking actions and
configuration conflict previews. Omitted `periods` retain saved periods. Limits
are 104 periods per member and 2000 per clinic, within the existing 500-member
configuration limit. The editor preserves unsaved changes during polling.

Staff can request full-day leave for themselves; administrators can enter requests
for another staff member. Requests cover 1–366 current/future clinic-local days.
Pending or approved overlapping requests are rejected. Pending leave does not
block bookings. An administrator with `leave.review` and `schedule.configure`
permissions can review another member's request, see conflicting bookings and
approve or reject with a reason. Self-approval is prohibited. Existing bookings
must be moved or cancelled before approval; neither preview nor approval moves
appointments. Approval checks the request and schedule versions and repeats all
conflict checks inside the booking write transaction. Rota changes and approvals
therefore cannot race a new booking or overwrite a concurrent review.

The requester or an administrator can withdraw pending or current/future approved
leave with a reason. Withdrawal restores the **underlying** rota, not unrestricted
availability. Past approved leave remains history. Expired pending requests can
be withdrawn/rejected but cannot be approved retroactively. Every transition
retains its actor, time and reason, record revisions and shared-action audit.
Same-key retries return the same receipt without duplicate transitions. Approval
and withdrawal of approved leave advance the rota version, invalidating stale
rota drafts and refreshing the displayed availability.

These are operational scheduling records visible to the clinic team, **not a
confidential HR system**. The form explicitly asks users not to enter private
medical details. There are no inferred leave entitlements, payroll calculations,
cancellation/no-show fees or deposit rules. Clinic-approved policies are still
needed for those features. Partial-day leave uses the existing administrator
replacement-hour workflow; request/approval currently covers full days only.

Actions: `leave.request`, `leave.review`, `leave.cancel`. Read-only review:
`POST /api/schedule/leave/preview` with `id` and `version`, returning the current
request/schedule versions, overlapping approved request IDs and booking conflicts.
Approval requires that reviewed `schedule_version`. Organization locks apply to
review through its schedule permission dependency.

The calendar now handles incomplete keyboard date entry without constructing
invalid duplicate day cells. Navigation clamps end-of-month dates and bounds
rendered dates to years 0001–9999. Frontend regression tests cover the reproduced
incomplete-input failure, month/leap-year navigation and supported-date boundaries.

Repeatable acceptance (private state files must stay out of Git):

```sh
.venv/bin/python scripts/smoke-scheduling.py <app-url> \
  --credentials <private-credentials.json> --state <new-private-state.json>
# After deployment/restart, inspect the existing fixture without recreating it:
.venv/bin/python scripts/smoke-scheduling.py <app-url> \
  --credentials <private-credentials.json> --state <same-private-state.json> --verify-only
```

The script creates a synthetic member/patient, exercises period hours, conflicts,
a booking arriving after review, approval replay and withdrawal, then cancels its
appointments, deactivates its test member and restores the previous clinic rota.
It checks that every other existing record is unchanged. If a run fails, inspect
its saved phase/IDs before acting; it refuses to recreate an existing state file.
The leave and cancelled appointment history remain as acceptance evidence.
