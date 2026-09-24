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
Cancellation fees, no-show rules, leave approvals, payroll, a rolling weekly rota
with effective date ranges, deposits and clinic policy decisions are not inferred
or implemented by this release.
