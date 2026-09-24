"""Clinic-local rota rules shared by previews, bookings and atomic configuration saves."""
import re
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request
from db import connection, get, all_records, record, update, now

router = APIRouter()
PERMISSIONS = {'leave.request': {'vet', 'nurse', 'admin'}, 'leave.review': {'admin'}, 'leave.cancel': {'vet', 'nurse', 'admin'}}


def week_windows(days):
    from actions import fail
    if not isinstance(days, dict) or any(day not in list('0123456') for day in days):
        fail('Availability must map weekdays 0–6 to shifts')
    return {day: windows(value) for day, value in days.items()}


def reason_text(value):
    from actions import fail
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= 500:
        fail('Give an operational reason of 3–500 characters; do not include private medical details')
    return value.strip()


def clock_time(value):
    from actions import fail
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,2}:\d{2}', value):
        fail('Use HH:MM start and end times')
    try:
        return datetime.strptime(value, '%H:%M').strftime('%H:%M')
    except ValueError:
        fail('Use HH:MM start and end times')


def windows(value):
    from actions import fail
    if not isinstance(value, list) or len(value) > 8:
        fail('Use at most eight shifts per day')
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {'start', 'end'}:
            fail('Each shift needs a start and end time')
        start, end = clock_time(item['start']), clock_time(item['end'])
        if start >= end:
            fail('Shift start must precede end; split overnight shifts across dates')
        result.append({'start': start, 'end': end})
    result.sort(key=lambda w: w['start'])
    if any(a['end'] > b['start'] for a, b in zip(result, result[1:])):
        fail('Shifts on the same day must not overlap')
    return result


def candidate(c, clinic, payload):
    from actions import fail, owned, version
    from clinic_workflows import calendar_date
    current = get(c, 'schedule-' + clinic, clinic)
    if current:
        version(current, payload)
    elif payload.get('version') not in (None, 0):
        fail('Schedule changed. Reload before editing.', 409)
    old = current['data'] if current else {}
    rooms = payload.get('rooms', old.get('rooms', []))
    if (not isinstance(rooms, list) or len(rooms) > 100 or
            any(not isinstance(r, str) or not r.strip() or len(r.strip()) > 100 for r in rooms)):
        fail('Use at most 100 nonempty room names, each up to 100 characters')
    rooms = [r.strip() for r in rooms]
    if len(set(rooms)) != len(rooms):
        fail('Provide unique room names')
    weekly = payload.get('availability', old.get('availability', {}))
    overrides = payload.get('date_overrides', old.get('date_overrides', {}))
    periods = payload.get('periods', old.get('periods', {}))
    if (not all(isinstance(x, dict) for x in (weekly, overrides, periods)) or
            len(set(weekly) | set(overrides) | set(periods)) > 500):
        fail('Invalid staff rota; at most 500 staff can have scheduling rules')
    for member in set(weekly) | set(overrides) | set(periods):
        owned(c, member, clinic, 'member')
    availability, date_overrides = {}, {}
    for member, days in weekly.items():
        availability[member] = week_windows(days)
    normalized_periods, count = {}, 0
    for member, entries in periods.items():
        if not isinstance(entries, list) or len(entries) > 104:
            fail('Use at most 104 rota periods per staff member')
        count += len(entries)
        if count > 2000:
            fail('Use at most 2000 rota periods per clinic')
        normalized_periods[member] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'start', 'end', 'week', 'reason'}:
                fail('Each rota period needs start, end, weekly shifts and a reason')
            start, end = calendar_date(entry['start']), calendar_date(entry['end'])
            if start > end:
                fail('Rota period start must not follow its end')
            normalized_periods[member].append({'start': start, 'end': end, 'week': week_windows(entry['week']), 'reason': reason_text(entry['reason'])})
        normalized_periods[member].sort(key=lambda p: p['start'])
        if any(a['end'] >= b['start'] for a, b in zip(normalized_periods[member], normalized_periods[member][1:])):
            fail('Rota periods for the same staff member must not overlap, including their end dates')
    count = 0
    for member, days in overrides.items():
        if not isinstance(days, dict):
            fail('Dated changes must map dates to shifts and a reason')
        date_overrides[member] = {}
        for day, item in days.items():
            count += 1
            if count > 5000:
                fail('Use at most 5000 dated rota changes')
            day = calendar_date(day)
            if not isinstance(item, dict) or set(item) != {'windows', 'reason'}:
                fail('Each dated change needs shifts and a reason')
            reason = item['reason']
            if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
                fail('Give a reason of 3–500 characters for the dated change')
            date_overrides[member][day] = {'windows': windows(item['windows']), 'reason': reason.strip()}
    return current, {**old, 'rooms': rooms, 'availability': availability, 'date_overrides': date_overrides, 'periods': normalized_periods}


def with_leave(c, clinic, data, extra=None):
    """Derived only from authorized records, never from a caller's schedule payload."""
    approved = [r for r in all_records(c, clinic, 'staff_leave') if r['data']['status'] == 'approved']
    if extra:
        approved.append(extra)
    leaves = {}
    for row in approved:
        leaves.setdefault(row['data']['member_id'], []).append({'id': row['id'], **row['data']})
    return {**data, '_approved_leave': leaves}


def effective(data, member, day):
    for leave in data.get('_approved_leave', {}).get(member, []):
        if leave['start'] <= day.isoformat() <= leave['end']:
            return {'source': 'approved_leave', 'windows': [], 'reason': 'Approved leave', 'leave_id': leave['id']}
    override = data.get('date_overrides', {}).get(member, {}).get(day.isoformat())
    if override is not None:
        return {'source': 'exception', **override}
    for period in data.get('periods', {}).get(member, []):
        if period['start'] <= day.isoformat() <= period['end']:
            return {'source': 'period', 'windows': period['week'].get(str(day.weekday()), []), 'reason': period['reason']}
    week = data.get('availability', {}).get(member)
    if week is None:
        return {'source': 'unrestricted', 'windows': None, 'reason': ''}
    return {'source': 'weekly', 'windows': week.get(str(day.weekday()), []), 'reason': ''}


def fits(data, member, start, duration):
    if duration < 5 or duration > 1440 or start.tzinfo is not None:
        return False
    try:
        end = start + timedelta(minutes=duration)
    except OverflowError:
        return False
    if start.date() != end.date():
        return False
    slots = effective(data, member, start.date())['windows']
    return slots is None or any(
        datetime.combine(start.date(), datetime.strptime(w['start'], '%H:%M').time()) <= start and
        end <= datetime.combine(start.date(), datetime.strptime(w['end'], '%H:%M').time())
        for w in slots)


def conflicts(c, clinic, data):
    from clinic_workflows import clinic_today
    today = clinic_today(c, clinic).date().isoformat()
    records = all_records(c, clinic)
    names = {r['id']: r['data'].get('name', r['id']) for r in records if r['kind'] in ('patient', 'member')}
    result = []
    for r in records:
        if r['kind'] != 'appointment':
            continue
        d = r['data']
        if d['status'] not in ('scheduled', 'arrived') or d['date'] < today:
            continue
        reasons = []
        if d.get('room') and d['room'] not in data.get('rooms', []):
            reasons.append('Assigned room would be removed')
        if not fits(data, d['clinician'], datetime.fromisoformat(d['date'] + 'T' + d['time']), d['duration']):
            reasons.append('Outside the proposed staff shifts')
        if reasons:
            result.append({'id': r['id'], 'date': d['date'], 'time': d['time'], 'duration': d['duration'],
                           'patient': names.get(d['patient_id'], 'Patient'), 'clinician': names.get(d['clinician'], 'Staff'),
                           'room': d.get('room', ''), 'reasons': reasons})
    return sorted(result, key=lambda r: (r['date'], r['time'], r['id']))


def configure(c, clinic, payload):
    from actions import fail
    current, data = candidate(c, clinic, payload)
    blocked = conflicts(c, clinic, with_leave(c, clinic, data))
    if blocked:
        first = blocked[0]
        fail(f"Rota conflicts with {len(blocked)} existing appointment(s), starting {first['date']} at {first['time']}. Move or cancel these appointments, then review the rota again.", 409)
    # The shared action already holds BEGIN IMMEDIATE: another booking cannot race this check.
    return update(c, current, data) if current else record(c, 'schedule', clinic, data, 'schedule-' + clinic)


@router.post('/api/schedule/preview')
def preview(payload: dict, request: Request):
    from main import identity
    from actions import authorize
    clinic, actor = identity(request)
    with connection() as c:
        authorize(c, clinic, actor, 'schedule.configure')
        current, data = candidate(c, clinic, payload)
        return {'version': current['version'] if current else None, 'data': data, 'conflicts': conflicts(c, clinic, with_leave(c, clinic, data))}


@router.get('/api/schedule/rota')
def rota(request: Request, start: str = '', days: int = 7):
    from main import identity
    from actions import fail
    from clinic_workflows import clinic_today, calendar_date
    clinic, _ = identity(request)
    if not 1 <= days <= 42:
        fail('Request between 1 and 42 rota days')
    with connection() as c:
        beginning = date.fromisoformat(calendar_date(start)) if start else clinic_today(c, clinic).date()
        if beginning > date.max - timedelta(days=days - 1):
            fail('Rota dates exceed the supported calendar')
        config = get(c, 'schedule-' + clinic, clinic)
        data = with_leave(c, clinic, config['data'] if config else {})
        dates = [beginning + timedelta(days=i) for i in range(days)]
        members = [r for r in all_records(c, clinic, 'member') if r['data'].get('active')]
        return {'timezone': get(c, clinic, clinic)['data'].get('timezone', 'Asia/Singapore'),
                'version': config['version'] if config else None,
                'dates': [d.isoformat() for d in dates],
                'members': [{'id': r['id'], 'name': r['data']['name'], 'days': [dict(date=d.isoformat(), **effective(data, r['id'], d)) for d in dates]} for r in members]}


def leave_review(c, clinic, actor, payload):
    from actions import owned, version, fail
    from clinic_workflows import clinic_today
    row = owned(c, payload.get('id'), clinic, 'staff_leave')
    version(row, payload)
    d = row['data']
    if d['status'] != 'pending':
        fail('Only a pending leave request can be reviewed', 409)
    if d['member_id'] == actor:
        fail('Another administrator must review your own leave', 403)
    member = owned(c, d['member_id'], clinic, 'member')
    if not member['data'].get('active'):
        fail('This staff member is inactive', 409)
    if d['start'] < clinic_today(c, clinic).date().isoformat():
        fail('Leave has already started. Withdraw this request and submit current dates.', 409)
    config = get(c, 'schedule-' + clinic, clinic)
    data = config['data'] if config else {}
    overlap = [r for r in all_records(c, clinic, 'staff_leave') if r['data']['member_id'] == d['member_id'] and r['data']['status'] == 'approved' and r['data']['start'] <= d['end'] and r['data']['end'] >= d['start']]
    return row, config, overlap, conflicts(c, clinic, with_leave(c, clinic, data, row))


@router.post('/api/schedule/leave/preview')
def preview_leave(payload: dict, request: Request):
    from main import identity
    from actions import authorize
    clinic, actor = identity(request)
    with connection() as c:
        authorize(c, clinic, actor, 'leave.review')
        row, config, overlaps, blocked = leave_review(c, clinic, actor, payload)
        return {'request_version': row['version'], 'schedule_version': config['version'] if config else None,
                'overlapping_leave_ids': [r['id'] for r in overlaps], 'conflicts': blocked}


def bump_schedule(c, clinic, config):
    # Rota editors and leave approvals share a version as well as the write lock.
    return update(c, config, config['data']) if config else record(c, 'schedule', clinic, {'rooms': [], 'availability': {}, 'date_overrides': {}, 'periods': {}}, 'schedule-' + clinic)


def dispatch(c, action, p, clinic, actor):
    from actions import owned, version, fail
    from clinic_workflows import calendar_date, clinic_today
    today = clinic_today(c, clinic).date().isoformat()
    member = owned(c, actor, clinic, 'member')
    if action == 'leave.request':
        target = p.get('member_id', actor)
        if target != actor and member['data']['role'] != 'admin':
            fail('You can only request your own leave', 403)
        if not owned(c, target, clinic, 'member')['data'].get('active'):
            fail('Choose an active staff member')
        start, end = calendar_date(p.get('start')), calendar_date(p.get('end'))
        if start < today or start > end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 365:
            fail('Use current or future leave dates covering at most 366 days')
        reason = reason_text(p.get('reason'))
        if any(r['data']['member_id'] == target and r['data']['status'] in ('pending', 'approved') and r['data']['start'] <= end and r['data']['end'] >= start for r in all_records(c, clinic, 'staff_leave')):
            fail('This staff member already has pending or approved leave in that period', 409)
        return record(c, 'staff_leave', clinic, {'member_id': target, 'start': start, 'end': end, 'reason': reason,
                      'status': 'pending', 'requested_by': actor, 'history': [{'status': 'pending', 'actor': actor, 'at': now(), 'reason': reason}]})
    row = owned(c, p.get('id'), clinic, 'staff_leave')
    version(row, p)
    d = row['data']
    reason = reason_text(p.get('reason'))
    if action == 'leave.review':
        decision = p.get('decision')
        if decision not in ('approved', 'rejected'):
            fail('Choose approved or rejected')
        if d['status'] != 'pending':
            fail('Only pending requests can be approved or rejected', 409)
        if d['member_id'] == actor:
            fail('Another administrator must review your own leave', 403)
        if decision == 'approved':
            _, config, overlap, blocked = leave_review(c, clinic, actor, p)
            if 'schedule_version' not in p or p['schedule_version'] != (config['version'] if config else None):
                fail('The rota changed. Review leave again before approving.', 409)
            if overlap:
                fail('Approved leave already covers part of this period', 409)
            if blocked:
                fail(f'Leave conflicts with {len(blocked)} appointment(s). Reschedule or cancel them and review again.', 409)
            bump_schedule(c, clinic, config)
        status = decision
    elif action == 'leave.cancel':
        if d['member_id'] != actor and member['data']['role'] != 'admin':
            fail('You can only withdraw your own leave', 403)
        if d['status'] not in ('pending', 'approved'):
            fail('Only pending or approved leave can be withdrawn', 409)
        if d['status'] == 'approved':
            if d['end'] < today:
                fail('Past approved leave is retained as history', 409)
            bump_schedule(c, clinic, get(c, 'schedule-' + clinic, clinic))
        status = 'cancelled'
    else:
        fail('Unknown leave action', 404)
    return update(c, row, {**d, 'status': status, 'history': [*d['history'], {'status': status, 'actor': actor, 'at': now(), 'reason': reason}]})
