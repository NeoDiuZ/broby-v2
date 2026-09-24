"""Rota acceptance: shared booking rules, review races and transaction rollback."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import db, main, scheduling
from test_integrity import isolated, act, get, rows, err

ADMIN = 'clinic-east-admin'
MONDAY = '2099-01-05'
TUESDAY = '2099-01-06'


def staff():
    return act('member.save', {'name': 'Synthetic rota clinician', 'role': 'vet'}, actor=ADMIN)['id']


def shift(start='09:00', end='12:00'):
    return {'start': start, 'end': end}


def save(p, key=None):
    return act('schedule.configure', p, actor=ADMIN, key=key)


def booking(member, **extra):
    return {'patient_id': 'luna', 'clinician': member, 'date': MONDAY, 'time': '09:00', 'duration': 30, 'reason': 'Synthetic rota check', **extra}


def preview(payload, actor=ADMIN, clinic='clinic-east'):
    return TestClient(main.app).post('/api/schedule/preview', json=payload, headers={'x-actor-id': actor, 'x-clinic-id': clinic})


def test_full_week_split_shifts_and_other_staff_preserved():
    m, other = staff(), staff()
    config = save({'availability': {m: {'0': [shift('9:00', '12:00'), shift('13:00', '17:00')], '1': [shift()]}, other: {'2': [shift()]}}})
    assert config['data']['availability'][m]['0'][0]['start'] == '09:00'
    act('appointment.create', booking(m, time='11:30'))
    act('appointment.create', booking(m, time='13:00'))
    act('appointment.create', booking(m, date=TUESDAY))
    for changes in ({'time': '11:45'}, {'time': '12:00'}, {'date': '2099-01-07'}):
        err(409, lambda: act('appointment.create', booking(m, **changes)))
    next_data = deepcopy(config['data']); next_data['availability'][m]['2'] = [shift()]
    changed = save({**next_data, 'version': 1})
    assert changed['data']['availability'][other] == config['data']['availability'][other]
    assert changed['data']['availability'][m]['1'] == [shift()]


def test_dated_leave_and_replacement_hours_take_precedence():
    m = staff()
    config = save({'availability': {m: {'0': [shift()]}}, 'date_overrides': {m: {MONDAY: {'windows': [], 'reason': 'Leave'}, TUESDAY: {'windows': [shift('14:00', '16:00')], 'reason': 'Replacement hours'}}}})
    err(409, lambda: act('appointment.create', booking(m)))
    act('appointment.create', booking(m, date=TUESDAY, time='14:00'))
    err(409, lambda: act('appointment.create', booking(m, date=TUESDAY, time='09:00')))
    # Old callers omitting the new field cannot erase leave.
    updated = save({'version': 1, 'availability': config['data']['availability']})
    assert updated['data']['date_overrides'] == config['data']['date_overrides']
    overrides = deepcopy(updated['data']['date_overrides']); del overrides[m][MONDAY]
    save({'version': 2, 'date_overrides': overrides})
    act('appointment.create', booking(m))


def test_unrestricted_and_all_days_off_are_distinct():
    m = staff()
    act('appointment.create', booking(m))
    err(409, lambda: save({'availability': {m: {}}}))
    assert get('schedule-clinic-east') is None
    for a in rows('appointment'):
        if a['data']['clinician'] == m:
            act('appointment.update', {'id': a['id'], 'version': a['version'], 'status': 'cancelled'})
    save({'availability': {m: {}}})
    err(409, lambda: act('appointment.create', booking(m)))
    save({'version': 1, 'availability': {}})
    act('appointment.create', booking(m))


@pytest.mark.parametrize('bad', [None, {}, [None], [{'start':'10:00'}], [shift('12:00','09:00')], [shift('09:00','09:00')], [shift('09:00:01')], [shift('24:00')], [shift('09:00+08:00')], [shift(),shift('11:00','13:00')], [shift()]*9])
def test_invalid_windows_leave_no_configuration(bad):
    m = staff()
    err(422, lambda: save({'availability': {m: {'0': bad}}}))
    assert get('schedule-clinic-east') is None


@pytest.mark.parametrize('bad', [{'2026-02-30': {'windows': [], 'reason': 'Leave'}}, {'2099-1-5': {'windows': [], 'reason': 'Leave'}}, {MONDAY: {'windows': [], 'reason': ''}}, {MONDAY: {'windows': [], 'reason': 'x'*501}}, {MONDAY: []}])
def test_invalid_dated_changes(bad):
    m = staff()
    err(422, lambda: save({'date_overrides': {m: bad}}))


def test_rooms_trim_duplicates_and_block_assigned_room_removal():
    m = staff()
    config = save({'rooms': ['  Room A  ', 'Room B']})
    assert config['data']['rooms'] == ['Room A', 'Room B']
    a = act('appointment.create', booking(m, room='Room A'))
    response = preview({'version': 1, 'rooms': ['Room B']})
    assert response.status_code == 200
    assert response.json()['conflicts'][0]['id'] == a['id']
    err(409, lambda: save({'version': 1, 'rooms': ['Room B']}))
    assert get('schedule-clinic-east') == config
    err(422, lambda: save({'version': 1, 'rooms': ['Room A', ' Room A ']}))


def test_preview_is_read_only_and_save_rechecks_new_booking():
    m = staff(); payload = {'availability': {m: {'0': [shift('14:00', '17:00')]}}}
    assert preview(payload).json()['conflicts'] == []
    assert get('schedule-clinic-east') is None
    a = act('appointment.create', booking(m))
    err(409, lambda: save(payload))
    assert get('schedule-clinic-east') is None
    result = preview(payload).json()['conflicts']
    assert len(result) == 1 and result[0]['patient'] == 'Luna' and result[0]['id'] == a['id']
    assert get(a['id']) == a


def test_stale_versions_replay_and_audit_history():
    m = staff(); initial = save({'availability': {m: {'0': [shift()]}}})
    payload = {'version': 1, 'date_overrides': {m: {TUESDAY: {'windows': [], 'reason': 'Leave'}}}}
    result = save(payload, key='rota-review-once')
    assert save(payload, key='rota-review-once') == result
    err(409, lambda: save(payload))
    assert preview(payload).status_code == 409
    err(409, lambda: save({**payload, 'rooms': ['Changed']}, key='rota-review-once'))
    assert get(initial['id'])['version'] == 2
    with db.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM audit WHERE action='schedule.configure'").fetchone()[0] == 2
        assert c.execute('SELECT COUNT(*) FROM record_versions WHERE record_id=?', (initial['id'],)).fetchone()[0] == 1


def test_roles_clinic_isolation_and_organization_locks():
    for role in ('vet', 'nurse'):
        assert preview({}, actor='clinic-east-'+role).status_code == 403
        err(403, lambda: act('schedule.configure', {}, actor='clinic-east-'+role))
    err(404, lambda: save({'availability': {'clinic-river-vet': {}}}))
    err(404, lambda: save({'date_overrides': {'clinic-river-vet': {}}}))
    save({'date_overrides': {'clinic-east-nurse': {MONDAY: {'windows': [], 'reason': 'Private clinic leave'}}}})
    client = TestClient(main.app)
    response = client.get('/api/schedule/rota?start='+MONDAY, headers={'x-clinic-id': 'clinic-river', 'x-actor-id': 'clinic-river-vet'})
    assert response.status_code == 200 and 'Private clinic leave' not in response.text and 'clinic-east' not in response.text
    act('organization.create', {'name': 'Synthetic rota org'}, actor=ADMIN)
    act('organization.policy', {'actions': ['schedule.configure']}, actor=ADMIN)
    other_admin = act('member.save', {'name': 'Delegated administrator', 'role': 'admin'}, actor=ADMIN)['id']
    assert preview({'version': 1}, actor=other_admin).status_code == 403
    err(403, lambda: act('schedule.configure', {'version': 1}, actor=other_admin))
    assert preview({'version': 1}).status_code == 200


def test_series_reschedule_and_reopen_share_leave_rules_atomically():
    m = staff(); a = act('appointment.create', booking(m))
    cancelled = act('appointment.update', {'id': a['id'], 'version': a['version'], 'status': 'cancelled'})
    save({'date_overrides': {m: {MONDAY: {'windows': [], 'reason': 'Leave'}, '2099-01-19': {'windows': [], 'reason': 'Leave'}}}})
    err(409, lambda: act('appointment.update', {'id': a['id'], 'version': cancelled['version'], 'status': 'scheduled'}))
    assert get(a['id']) == cancelled
    live = act('appointment.create', booking(m, date=TUESDAY))
    err(409, lambda: act('appointment.reschedule', {**booking(m), 'id': live['id'], 'version': live['version']}))
    assert get(live['id']) == live
    before = len(rows('appointment'))
    err(409, lambda: act('appointment.series', {**booking(m, date='2099-01-12'), 'count': 3, 'interval_days': 7}))
    assert len(rows('appointment')) == before


def test_past_and_terminal_appointments_do_not_block_future_rota():
    m = staff()
    act('appointment.create', booking(m, date='2000-01-03'))
    a = act('appointment.create', booking(m))
    act('appointment.update', {'id': a['id'], 'version': a['version'], 'status': 'completed'})
    assert save({'availability': {m: {}}})


def test_rota_default_date_and_conflict_cutoff_use_clinic_timezone(monkeypatch):
    from clinic_workflows import clinic_today as actual_today
    instant = datetime(2099, 1, 4, 17, tzinfo=timezone.utc)  # Monday morning Singapore, still Sunday UTC.
    monkeypatch.setattr('clinic_workflows.clinic_today', lambda c, clinic: actual_today(c, clinic, instant))
    m = staff()
    act('appointment.create', booking(m, date='2099-01-04'))
    a = act('appointment.create', booking(m))
    result = preview({'availability': {m: {}}}).json()
    assert [x['id'] for x in result['conflicts']] == [a['id']]
    client = TestClient(main.app)
    rota = client.get('/api/schedule/rota').json()
    assert rota['dates'][0] == MONDAY and rota['timezone'] == 'Asia/Singapore'
    for query in ('days=43', 'days=0', 'start=bad', 'start=9999-12-31&days=2'):
        assert client.get('/api/schedule/rota?'+query).status_code == 422


def test_concurrent_booking_and_rota_cannot_strand_an_appointment():
    m = staff(); barrier = threading.Barrier(2)
    def attempt(which):
        barrier.wait()
        try:
            return ('ok', save({'availability': {m: {}}}) if which == 0 else act('appointment.create', booking(m)))
        except HTTPException as e:
            return ('error', e.status_code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [0, 1]))
    assert sorted(r[0] for r in results) == ['error', 'ok']
    assert next(r[1] for r in results if r[0] == 'error') == 409


@pytest.mark.parametrize('changes', [{'time': '09:00:01'}, {'time': '09:00+08:00'}, {'date': '20990105'}, {'time': '23:50', 'duration': 30}])
def test_booking_requires_clinic_local_minute_precision(changes):
    err(422, lambda: act('appointment.create', booking(staff(), **changes)))


def test_rota_reader_matches_exception_and_weekly_rules_for_staff():
    m = staff()
    save({'availability': {m: {'0': [shift('09:00', '12:00'), shift('12:00', '17:00')]}}, 'date_overrides': {m: {TUESDAY: {'windows': [], 'reason': 'Annual leave'}}}})
    response = TestClient(main.app).get('/api/schedule/rota?start='+MONDAY, headers={'x-actor-id': 'clinic-east-nurse'})
    assert response.status_code == 200
    days = next(r['days'] for r in response.json()['members'] if r['id'] == m)
    assert days[0]['source'] == 'weekly' and len(days[0]['windows']) == 2
    assert days[1] == {'date': TUESDAY, 'source': 'exception', 'windows': [], 'reason': 'Annual leave'}
    assert days[2]['source'] == 'weekly' and days[2]['windows'] == []
    unrestricted = next(r for r in response.json()['members'] if r['id'] == 'clinic-east-vet')
    assert unrestricted['days'][0]['windows'] is None
