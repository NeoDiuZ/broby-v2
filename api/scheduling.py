"""Clinic-local rota rules shared by previews, bookings and atomic configuration saves."""
import re
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request
from db import connection, get, all_records, record, update

router = APIRouter()


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
    if not isinstance(weekly, dict) or not isinstance(overrides, dict) or len(set(weekly) | set(overrides)) > 500:
        fail('Invalid staff rota; at most 500 staff can have scheduling rules')
    for member in set(weekly) | set(overrides):
        owned(c, member, clinic, 'member')
    availability, date_overrides = {}, {}
    for member, days in weekly.items():
        if not isinstance(days, dict) or any(day not in list('0123456') for day in days):
            fail('Availability must map weekdays 0–6 to shifts')
        availability[member] = {day: windows(value) for day, value in days.items()}
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
    return current, {**old, 'rooms': rooms, 'availability': availability, 'date_overrides': date_overrides}


def effective(data, member, day):
    override = data.get('date_overrides', {}).get(member, {}).get(day.isoformat())
    if override is not None:
        return {'source': 'exception', **override}
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
        if d.get('room') and d['room'] not in data['rooms']:
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
    blocked = conflicts(c, clinic, data)
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
        return {'version': current['version'] if current else None, 'data': data, 'conflicts': conflicts(c, clinic, data)}


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
        data = config['data'] if config else {}
        dates = [beginning + timedelta(days=i) for i in range(days)]
        members = [r for r in all_records(c, clinic, 'member') if r['data'].get('active')]
        return {'timezone': get(c, clinic, clinic)['data'].get('timezone', 'Asia/Singapore'),
                'version': config['version'] if config else None,
                'dates': [d.isoformat() for d in dates],
                'members': [{'id': r['id'], 'name': r['data']['name'], 'days': [dict(date=d.isoformat(), **effective(data, r['id'], d)) for d in dates]} for r in members]}
