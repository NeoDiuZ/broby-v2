"""Acceptance for leave decisions and effective-dated rota, through the shared executor."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
import threading
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import db, main, scheduling
from test_integrity import isolated, act, get, rows, err
from test_scheduling import ADMIN, MONDAY, TUESDAY, staff, shift, save, booking, preview


def period(start=MONDAY, end=TUESDAY, **kw):
    return {'start': start, 'end': end, 'week': {'0': [shift('14:00', '17:00')], '1': [shift('14:00', '17:00')]}, 'reason': 'Synthetic seasonal hours', **kw}


def request(member=None, **kw):
    return act('leave.request', {'member_id': member or staff(), 'start': MONDAY, 'end': TUESDAY, 'reason': 'Synthetic annual leave', **kw}, actor=ADMIN)


def review(r, **kw):
    config = get('schedule-clinic-east')
    return act('leave.review', {'id': r['id'], 'version': r['version'], 'decision': 'approved', 'schedule_version': config['version'] if config else None, 'reason': 'Synthetic coverage reviewed', **kw}, actor=ADMIN)


def leave_preview(r, actor=ADMIN, clinic='clinic-east'):
    return TestClient(main.app).post('/api/schedule/leave/preview', json={'id': r['id'], 'version': r['version']}, headers={'x-actor-id': actor, 'x-clinic-id': clinic})


def test_period_boundaries_precedence_and_base_restoration():
    m = staff()
    config = save({'availability': {m: {str(d): [shift()] for d in range(7)}}, 'periods': {m: [period()]}, 'date_overrides': {m: {TUESDAY: {'windows': [shift('16:00', '18:00')], 'reason': 'Special hours'}}}})
    d = config['data']
    assert scheduling.effective(d, m, date(2099, 1, 4))['source'] == 'weekly'
    assert scheduling.effective(d, m, date(2099, 1, 5)) == {'source': 'period', 'windows': [shift('14:00','17:00')], 'reason': 'Synthetic seasonal hours'}
    assert scheduling.effective(d, m, date(2099, 1, 6))['source'] == 'exception'
    assert scheduling.effective(d, m, date(2099, 1, 7))['source'] == 'weekly'
    err(409, lambda: act('appointment.create', booking(m)))
    act('appointment.create', booking(m, time='14:00'))
    act('appointment.create', booking(m, date=TUESDAY, time='16:00'))
    err(409, lambda: act('appointment.create', booking(m, date=TUESDAY, time='14:00')))
    assert save({'version': 1, 'rooms': []})['data']['periods'] == config['data']['periods']


def test_periods_conflict_preview_and_transaction_rollback():
    m = staff(); appt = act('appointment.create', booking(m))
    payload = {'periods': {m: [period()]}}
    assert preview(payload).json()['conflicts'][0]['id'] == appt['id']
    err(409, lambda: save(payload))
    assert get('schedule-clinic-east') is None and get(appt['id']) == appt


@pytest.mark.parametrize('p', [None, {}, [None], [period(start=TUESDAY, end=MONDAY)], [period(start='2099-1-5')], [period(reason='')], [period(week={'7':[]})], [period(week={'0':[shift('17:00','09:00')]})], [period(), period(start=TUESDAY, end='2099-01-07')], [period()]*105, [dict(period(), unexpected=True)]])
def test_invalid_periods_fail_without_writes(p):
    err(422, lambda: save({'periods': {staff(): p}}))
    assert get('schedule-clinic-east') is None


def test_adjacent_periods_are_sorted_and_day_off_is_not_unrestricted():
    m = staff()
    c = save({'periods': {m: [period(start='2099-01-07', end='2099-01-10', week={}), period()]}})
    assert c['data']['periods'][m][0]['start'] == MONDAY
    assert scheduling.effective(c['data'], m, date(2099, 1, 7))['windows'] == []
    assert scheduling.effective(c['data'], m, date(2099, 1, 11))['windows'] is None
    err(404, lambda: save({'version': 1, 'periods': {'clinic-river-vet': [period()]}}))


def test_pending_does_not_block_but_approval_requires_resolving_booking():
    m = staff(); r = request(m); before = deepcopy(r)
    appt = act('appointment.create', booking(m))
    checked = leave_preview(r)
    assert checked.status_code == 200 and checked.json()['conflicts'][0]['id'] == appt['id']
    assert get(r['id']) == before and get('schedule-clinic-east') is None
    err(409, lambda: review(r))
    assert get(r['id']) == before
    act('appointment.update', {'id': appt['id'], 'version': 1, 'status': 'cancelled'})
    approved = review(r)
    assert approved['data']['status'] == 'approved'
    assert [h['status'] for h in approved['data']['history']] == ['pending','approved']
    assert get('schedule-clinic-east')['version'] == 1
    err(409, lambda: act('appointment.create', booking(m)))
    err(409, lambda: act('appointment.update', {'id': appt['id'], 'version': 2, 'status': 'scheduled'}))
    rota = TestClient(main.app).get('/api/schedule/rota?start='+MONDAY).json()
    days = next(x['days'] for x in rota['members'] if x['id'] == m)
    assert days[0]['source'] == days[1]['source'] == 'approved_leave'
    assert days[0]['leave_id'] == r['id'] and days[2]['windows'] is None


def test_approved_leave_wins_even_over_later_dated_and_period_changes():
    m = staff(); r = request(m); review(r)
    save({'version': 1, 'periods': {m: [period()]}, 'date_overrides': {m: {MONDAY: {'windows': [shift()], 'reason': 'Override test'}}}})
    err(409, lambda: act('appointment.create', booking(m)))
    err(409, lambda: act('appointment.create', booking(m, date=TUESDAY, time='14:00')))
    # Forged derived state is ignored by schedule.configure.
    config = save({'version': 2, '_approved_leave': {}})
    assert '_approved_leave' not in config['data']
    err(409, lambda: act('appointment.create', booking(m)))


def test_withdrawal_restores_underlying_rules_not_unrestricted_hours():
    m = staff(); save({'periods': {m: [period()]}})
    r = review(request(m))
    cancelled = act('leave.cancel', {'id': r['id'], 'version': 2, 'reason': 'Synthetic plans changed'}, actor=m)
    assert cancelled['data']['status'] == 'cancelled'
    assert get('schedule-clinic-east')['version'] == 3
    err(409, lambda: act('appointment.create', booking(m)))
    act('appointment.create', booking(m, time='14:00'))
    assert [h['status'] for h in cancelled['data']['history']] == ['pending', 'approved', 'cancelled']
    err(409, lambda: act('leave.cancel', {'id': r['id'], 'version': 3, 'reason': 'Repeat cancellation'}, actor=m))
    err(409, lambda: review(cancelled))


def test_reject_and_pending_withdraw_do_not_change_rota():
    m = staff(); r = request(m)
    rejected = review(r, decision='rejected')
    assert rejected['data']['status'] == 'rejected' and get('schedule-clinic-east') is None
    other = request(m)
    act('leave.cancel', {'id': other['id'], 'version': 1, 'reason': 'Withdraw pending request'}, actor=m)
    assert get('schedule-clinic-east') is None
    act('appointment.create', booking(m))


def test_stale_versions_replay_and_history_are_exactly_once():
    m = staff(); r = request(m)
    payload = {'id': r['id'], 'version': 1, 'decision': 'approved', 'reason': 'Synthetic review accepted', 'schedule_version': None}
    checked = leave_preview(r).json(); assert checked['schedule_version'] is None
    save({'rooms': []})
    err(409, lambda: act('leave.review', payload, actor=ADMIN))
    assert get(r['id']) == r
    payload['schedule_version'] = 1
    approved = act('leave.review', payload, actor=ADMIN, key='approve-leave-once')
    assert act('leave.review', payload, actor=ADMIN, key='approve-leave-once') == approved
    assert get('schedule-clinic-east')['version'] == 2
    err(409, lambda: act('leave.review', {**payload, 'reason': 'Different'}, actor=ADMIN, key='approve-leave-once'))
    err(409, lambda: act('leave.cancel', {'id': r['id'], 'version': 1, 'reason': 'Old version'}, actor=m))
    with db.connection() as c:
        assert c.execute("SELECT count(*) FROM audit WHERE action='leave.review'").fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM record_versions WHERE record_id=?',(r['id'],)).fetchone()[0] == 1
    # Approval also invalidates previously opened rota editors.
    err(409, lambda: save({'version': 1, 'rooms': []}))


def test_request_idempotency_and_overlap_duplicate_protection():
    m = staff(); p = {'start': MONDAY, 'end': TUESDAY, 'reason': 'Synthetic leave'}
    r = act('leave.request', p, actor=m, key='request-leave-once')
    assert act('leave.request', p, actor=m, key='request-leave-once') == r
    err(409, lambda: act('leave.request', p, actor=m))
    err(409, lambda: request(m, start=TUESDAY, end='2099-01-07'))
    review(r)
    err(409, lambda: request(m))
    request(m, start='2099-01-07', end='2099-01-07')
    assert len(rows('staff_leave')) == 2


def test_roles_self_review_isolation_and_master_lock():
    m = staff(); r = request(m)
    err(403, lambda: act('leave.request', {'member_id': m}, actor='clinic-east-nurse'))
    err(403, lambda: act('leave.review', {'id': r['id']}, actor=m))
    err(403, lambda: act('leave.cancel', {'id': r['id'], 'version': 1, 'reason': 'Not my leave'}, actor='clinic-east-nurse'))
    assert leave_preview(r, actor='clinic-east-nurse').status_code == 403
    assert leave_preview(r, actor='clinic-river-admin', clinic='clinic-river').status_code == 404
    err(404, lambda: request('clinic-river-vet'))
    own = request(ADMIN)
    assert leave_preview(own).status_code == 403
    err(403, lambda: review(own))
    second = act('member.save', {'name': 'Second administrator', 'role': 'admin'}, actor=ADMIN)['id']
    assert leave_preview(own, actor=second).status_code == 200
    act('organization.create', {'name': 'Synthetic leave organization'}, actor=ADMIN)
    act('organization.policy', {'actions': ['schedule.configure']}, actor=ADMIN)
    assert leave_preview(r, actor=second).status_code == 403
    err(403, lambda: act('leave.review', {'id': r['id']}, actor=second))


@pytest.mark.parametrize('kw', [{'start':'2000-01-01'}, {'start':TUESDAY,'end':MONDAY}, {'end':'2100-01-06'}, {'start':'bad'}, {'reason':''}, {'reason':'a'*501}])
def test_invalid_requests_leave_no_record(kw):
    err(422, lambda: request(**kw))
    assert rows('staff_leave') == []


def test_inactive_member_cannot_request_or_be_approved():
    m = staff(); r = request(m)
    act('member.save', {'id': m, 'version': 1, 'name': 'Inactive member', 'role': 'vet', 'active': False}, actor=ADMIN)
    err(422, lambda: request(m, start='2099-01-07', end='2099-01-07'))
    err(409, lambda: review(r))
    # Administrative rejection remains possible for an obsolete request.
    assert review(r, decision='rejected')['data']['status'] == 'rejected'


def test_past_leave_policy_and_clinic_local_boundary(monkeypatch):
    from datetime import datetime, timezone
    from clinic_workflows import clinic_today as actual_today
    instant = datetime(2099,1,4,17,tzinfo=timezone.utc)
    monkeypatch.setattr('clinic_workflows.clinic_today', lambda c, clinic: actual_today(c,clinic,instant))
    m = staff()
    err(422, lambda: request(m,start='2099-01-04'))
    r = request(m)
    review(r)
    other = request(staff())
    instant = datetime(2099,1,7,0,tzinfo=timezone.utc)
    err(409, lambda: review(other))
    err(409, lambda: act('leave.cancel', {'id': r['id'], 'version': 2, 'reason': 'Past approved leave'}, actor=m))
    assert review(other, decision='rejected')['data']['status'] == 'rejected'


def test_recurring_and_reschedule_enforce_leave_atomically():
    m = staff(); review(request(m))
    before = len(rows('appointment'))
    err(409, lambda: act('appointment.series', {**booking(m, date='2098-12-29'), 'count': 3, 'interval_days': 7}))
    assert len(rows('appointment')) == before
    a = act('appointment.create', booking(m, date='2099-01-07'))
    err(409, lambda: act('appointment.reschedule', {**booking(m), 'id': a['id'], 'version': 1}))
    assert get(a['id']) == a


def test_booking_after_preview_and_concurrent_approval_never_strands_booking():
    m = staff(); r = request(m); assert leave_preview(r).json()['conflicts'] == []
    barrier = threading.Barrier(2)
    def attempt(which):
        barrier.wait()
        try:
            return ('ok', review(r) if which == 0 else act('appointment.create', booking(m)))
        except HTTPException as e:
            return ('error', e.status_code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [0,1]))
    assert sorted(r[0] for r in results) == ['error','ok']
    assert next(r[1] for r in results if r[0] == 'error') == 409
