"""Repeatable HTTP reads with real durable revision triggers in SQLite and PG."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
import auth
import bootstrap_refresh
import db
import main
from test_integrity import isolated, act, get


def client(clinic='clinic-east', actor=None):
    return TestClient(main.app, headers={'x-clinic-id': clinic, 'x-actor-id': actor or clinic+'-vet'})


def snapshot(c, token=None):
    r = c.get('/api/bootstrap', params={'since': token} if token else {})
    assert r.status_code == 200, r.text
    return r.json()


def test_5000_record_unchanged_poll_skips_pms_materialization(monkeypatch):
    with db.connection(True) as c:
        for i in range(5000):
            db.record(c, 'patient', 'clinic-east', {'name': 'SYNTHETIC scale '+str(i), 'species': 'Cat', 'description': 'SYNTHETIC '*30})
    c = client(); first = c.get('/api/bootstrap')
    assert len(first.content) > 2_000_000
    data = first.json(); assert len(data['records']) >= 5000
    monkeypatch.setattr(main, 'all_records', lambda *a: pytest.fail('Unchanged poll materialized PMS records'))
    for _ in range(3):
        response = c.get('/api/bootstrap', params={'since': data['snapshot_revision']})
        assert response.status_code == 200 and len(response.content) < 150
        assert response.json() == {'unchanged': True, 'snapshot_revision': data['snapshot_revision']}
    with db.connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM bootstrap_revisions').fetchone()[0] == 2


@pytest.mark.parametrize('mutation', ['insert', 'update', 'delete', 'move'])
def test_every_record_change_including_delete_and_both_move_scopes_invalidates(mutation):
    east, river = client(), client('clinic-river')
    with db.connection(True) as c:
        target = db.record(c, 'inventory', 'clinic-east', {'name': 'SYNTHETIC isolated item', 'stock': 3})
    before = snapshot(east); river_before = snapshot(river)
    with db.connection(True) as c:
        if mutation == 'insert': db.record(c, 'inventory', 'clinic-east', {'name': 'SYNTHETIC new item'})
        if mutation == 'update': c.execute('UPDATE records SET data=? WHERE id=?', (json.dumps({'name': 'SYNTHETIC edited'}), target['id']))
        if mutation == 'delete': c.execute('DELETE FROM records WHERE id=?', (target['id'],))
        if mutation == 'move': c.execute('UPDATE records SET clinic_id=? WHERE id=?', ('clinic-river', target['id']))
    after = snapshot(east, before['snapshot_revision']); assert 'records' in after
    assert after['snapshot_revision'] != before['snapshot_revision']
    if mutation in ('delete', 'move'): assert target['id'] not in {r['id'] for r in after['records']}
    river_after = snapshot(river, river_before['snapshot_revision'])
    if mutation == 'move': assert target['id'] in {r['id'] for r in river_after['records']}
    else: assert river_after['unchanged'] is True


def test_rollback_does_not_invalidate_or_change_data():
    c = client(); before = snapshot(c)
    with pytest.raises(RuntimeError):
        with db.connection(True) as connection:
            db.record(connection, 'inventory', 'clinic-east', {'name': 'SYNTHETIC rolled back'})
            raise RuntimeError('rollback')
    assert snapshot(c, before['snapshot_revision'])['unchanged']


def test_live_permission_revocation_and_restore_invalidate_cached_result():
    c = client(); before = snapshot(c)
    member = get('clinic-east-vet')
    act('access.member', {'id': member['id'], 'version': member['version'], 'restrictions': ['read.billing'], 'reason': 'SYNTHETIC revoke'}, actor='clinic-east-admin')
    after = snapshot(c, before['snapshot_revision'])
    assert 'read.billing' not in after['read_permissions'] and not after['jobs']
    assert not any(r['kind'] == 'invoice' for r in after['records'])
    assert snapshot(c, after['snapshot_revision'])['unchanged']
    member = get(member['id'])
    act('access.member', {'id': member['id'], 'version': member['version'], 'restrictions': [], 'reason': 'SYNTHETIC restore'}, actor='clinic-east-admin')
    restored = snapshot(c, after['snapshot_revision'])
    assert any(r['kind'] == 'invoice' for r in restored['records'])


def test_organization_policy_outside_records_is_rechecked():
    act('organization.create', {'name': 'SYNTHETIC org'}, actor='clinic-east-admin')
    c = client(); before = snapshot(c)
    act('organization.policy', {'actions': ['read.billing']}, actor='clinic-east-admin')
    after = snapshot(c, before['snapshot_revision'])
    assert 'read.billing' not in after['read_permissions']


def test_wrong_scope_malformed_token_and_process_restart_require_full_response(monkeypatch):
    c = client(); before = snapshot(c)
    for other in (client('clinic-river'), client(actor='clinic-east-nurse')):
        after = snapshot(other, before['snapshot_revision'])
        assert 'records' in after
        assert after['snapshot_revision'] != before['snapshot_revision']
    assert 'records' in snapshot(c, 'not-a-token')
    monkeypatch.setattr(bootstrap_refresh, 'BOOT_ID', 'SYNTHETIC next process')
    assert 'records' in snapshot(c, before['snapshot_revision'])


def test_inactive_member_and_expired_session_cannot_reuse_token(monkeypatch):
    c = client(); before = snapshot(c)
    with db.connection(True) as connection:
        m = db.get(connection, 'clinic-east-vet'); db.update(connection, m, {**m['data'], 'active': False})
    assert c.get('/api/bootstrap', params={'since': before['snapshot_revision']}).status_code == 403
    monkeypatch.setenv('BROBY_AUTH_MODE', 'password')
    auth.setup_tables()
    assert c.get('/api/bootstrap', params={'since': before['snapshot_revision']}).status_code == 401


def test_signed_in_session_membership_and_logout_are_checked_on_unchanged_poll(monkeypatch):
    monkeypatch.setenv('BROBY_AUTH_MODE', 'password')
    auth.setup_tables()
    auth.provision('synthetic-refresh', 'clinic-east-vet', 'clinic-east', 'synthetic-refresh-password')
    c = client()
    assert c.post('/api/login', json={'username': 'synthetic-refresh', 'password': 'synthetic-refresh-password'}).status_code == 200
    before = snapshot(c)
    assert snapshot(c, before['snapshot_revision'])['unchanged']
    assert c.get('/api/bootstrap', params={'since': before['snapshot_revision']}, headers={'x-clinic-id': 'clinic-river'}).status_code == 403
    # Password mode ignores a forged actor header; this is still the signed-in vet.
    forged = c.get('/api/bootstrap', params={'since': before['snapshot_revision']}, headers={'x-actor-id': 'clinic-east-admin'})
    assert forged.json()['unchanged']
    assert c.post('/api/logout').status_code == 200
    assert c.get('/api/bootstrap', params={'since': before['snapshot_revision']}).status_code == 401


def test_job_update_and_native_content_update_are_included_without_pms_change(monkeypatch):
    native = [{'id': 'SYNTHETIC-native', 'kind': 'event', 'clinic_id': 'clinic-east', 'version': 1, 'data': {'body': 'SYNTHETIC first'}}]
    monkeypatch.setattr('spine.reader.native_records', lambda *a: json.loads(json.dumps(native)))
    with db.connection(True) as connection:
        connection.execute('INSERT INTO jobs(id,clinic_id,status,created_at) VALUES(?,?,?,?)', ('SYNTHETIC-job', 'clinic-east', 'queued', db.now()))
    c = client(); before = snapshot(c)
    with db.connection(True) as connection:
        connection.execute('UPDATE jobs SET status=? WHERE id=?', ('completed', 'SYNTHETIC-job'))
    after_job = snapshot(c, before['snapshot_revision']); assert after_job['jobs'][0]['status'] == 'completed'
    native[0]['data']['approved'] = True
    after_native = snapshot(c, after_job['snapshot_revision'])
    assert next(r for r in after_native['records'] if r['id'] == native[0]['id'])['data']['approved']
    native.clear()
    assert not any(r['id'] == 'SYNTHETIC-native' for r in snapshot(c, after_native['snapshot_revision'])['records'])


def test_any_foreign_reconciliation_review_disables_unchanged_globally():
    c = client(); before = snapshot(c)
    with db.connection(True) as connection:
        db.record(connection, 'clinical_reconciliation_review', 'clinic-river', {'decisions': [], 'synthetic': True})
    # No East revision changed. Even a matching token must run the normal read.
    after = snapshot(c, before['snapshot_revision'])
    assert 'records' in after and after['snapshot_revision'] == before['snapshot_revision']
    with db.connection(True) as connection:
        db.record(connection, 'source', 'clinic-river', {'text': 'SYNTHETIC retained original changed'})
    assert 'records' in snapshot(c, after['snapshot_revision'])


def test_write_committed_during_read_never_stamps_unseen_content(monkeypatch):
    entered, written = threading.Event(), threading.Event()
    c = client(); old = get('luna')
    def native(*a):
        entered.set(); assert written.wait(10)
        return []
    monkeypatch.setattr('spine.reader.native_records', native)
    with ThreadPoolExecutor(max_workers=1) as pool:
        reading = pool.submit(snapshot, c)
        assert entered.wait(10)
        try:
            with db.connection(True) as connection:
                db.update(connection, old, {**old['data'], 'name': 'SYNTHETIC concurrent rename'})
        finally: written.set()
        during = reading.result(timeout=10)
    assert next(r for r in during['records'] if r['id'] == 'luna')['data']['name'] == old['data']['name']
    latest = snapshot(c, during['snapshot_revision'])
    assert next(r for r in latest['records'] if r['id'] == 'luna')['data']['name'] == 'SYNTHETIC concurrent rename'
