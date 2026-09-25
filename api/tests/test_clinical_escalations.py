import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
import clinical_escalations as escalation
import db, main
from test_integrity import isolated, act, get, rows, err
from test_owner_conversations import no_provider, grant, question, transition


@pytest.fixture
def receiver(monkeypatch):
    receipts = []; responses = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            receipts.append({'path': self.path, 'payload': payload, 'key': self.headers['Idempotency-Key']})
            self.send_response(responses.pop(0) if responses else 204); self.end_headers()
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    routes = {name: {'url': f'http://127.0.0.1:{server.server_port}/{name}', 'token': 'SYNTHETIC-secret'} for name in ('primary', 'backup')}
    monkeypatch.setenv('BROBY_ENVIRONMENT', 'local')
    monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_MODE', 'test-loopback')
    monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_ROUTES', json.dumps(routes))
    yield receipts, responses, routes
    server.shutdown(); server.server_close(); worker.join(timeout=2)


def policy(**changes):
    value = {'enabled': True, 'primary_member_id': 'clinic-east-vet', 'backup_member_id': 'clinic-east-nurse',
             'primary_route': 'primary', 'backup_route': 'backup', 'primary_timeout_seconds': 60,
             'backup_timeout_seconds': 60, 'fallback_instructions': 'SYNTHETIC: use the agreed alternate clinic contact process and record the result.',
             'recipient_authority_confirmed': True}
    value.update(changes)
    existing = get('owner-policy:clinic-east')
    return act('conversation.policy', {'version': existing['version'] if existing else 0, 'ack_minutes': 1,
               'escalation': value, 'reason': 'SYNTHETIC explicit routing and recipient authority review'}, actor='clinic-east-admin')


def incidents():
    with db.connection() as c: return escalation.status(c, 'clinic-east')['incidents']


def future(incident, stage):
    return datetime.fromisoformat(incident[stage+'_due_at'])+timedelta(seconds=1)


def test_real_primary_acceptance_timeout_backup_acceptance_and_staff_ack(receiver):
    receipts, _, _ = receiver
    policy(); thread = question(grant(), urgent=True, message='PRIVATE patient symptoms that must never leave the app')
    assert len(incidents()) == 1
    incident = incidents()[0]
    assert escalation.send_one()
    primary = incidents()[0]
    assert primary['state'] == 'awaiting_ack' and not primary['acknowledged_at']
    assert primary['events'][0]['status'] == 'accepted'
    escalation.scan(future(incident, 'primary')); escalation.scan(future(incident, 'primary'))
    assert escalation.send_one()
    assert len(receipts) == 2 and [r['payload']['stage'] for r in receipts] == ['primary', 'backup']
    assert not incidents()[0]['acknowledged_at']
    transition(thread)
    acknowledged = incidents()[0]
    assert acknowledged['state'] == 'acknowledged' and acknowledged['reviews'][0]['reason'] == 'SYNTHETIC reviewed'
    assert acknowledged['acknowledged_by'] == 'clinic-east-vet'
    while escalation.send_one(): pass
    assert [r['payload']['sequence'] for r in receipts] == [1, 2, 3, 3]
    for receipt in receipts:
        assert receipt['key'] == receipt['payload']['event_id']
        assert receipt['payload']['clinical_response_verified'] is False
        assert not any(secret in json.dumps(receipt) for secret in ('PRIVATE', 'luna', 'SYNTHETIC-secret', 'fallback_instructions', 'Amelia'))
    assert {e['status'] for e in incidents()[0]['events']} == {'accepted'}


def test_backup_timeout_stays_manual_fallback_after_http_acceptance_until_review(receiver):
    policy(); thread = question(grant(), urgent=True)
    incident = incidents()[0]
    escalation.scan(future(incident, 'backup'))
    assert escalation.send_one()
    assert incidents()[0]['state'] == 'manual_fallback'
    assert incidents()[0]['events'][-1]['status'] == 'accepted'
    escalation.scan(future(incident, 'backup')+timedelta(hours=1))
    assert incidents()[0]['state'] == 'manual_fallback' and not incidents()[0]['acknowledged_at']
    transition(thread, 'conversation.close')
    assert incidents()[0]['state'] == 'acknowledged'


def test_enable_does_not_sweep_old_urgent_or_old_timed_out_questions(receiver):
    import owner_conversations
    act('conversation.policy', {'ack_minutes': 1, 'reason': 'SYNTHETIC old internal target'}, actor='clinic-east-admin')
    old = question(grant(), urgent=True)
    timed = question(grant(), request_staff=True)
    policy()
    with db.connection(True) as c: owner_conversations.tick(c, 'clinic-east', datetime.now(timezone.utc)+timedelta(minutes=2))
    escalation.scan()
    assert incidents() == [] and not escalation.send_one()
    question(grant(), urgent=True)
    assert len(incidents()) == 1


def test_disabled_default_and_missing_explicit_clinic_policy_never_send(monkeypatch):
    monkeypatch.delenv('BROBY_CLINICAL_ESCALATION_MODE', raising=False)
    monkeypatch.delenv('BROBY_CLINICAL_ESCALATION_ROUTES', raising=False)
    question(grant(), urgent=True)
    escalation.tick()
    assert incidents() == [] and escalation.configuration() == ('disabled', {})
    err(422, lambda: policy())


@pytest.mark.parametrize('changes', [
    {'recipient_authority_confirmed': False}, {'primary_timeout_seconds': None},
    {'backup_timeout_seconds': 0}, {'fallback_instructions': ''},
    {'primary_member_id': 'clinic-river-vet'}, {'backup_member_id': 'clinic-east-vet'},
    {'primary_route': 'unconfigured'}, {'backup_route': 'primary'},
    {'primary_timeout_seconds': True}, {'extra_url': 'https://unreviewed.invalid'},
])
def test_policy_requires_explicit_reviewed_valid_contract(receiver, changes):
    err(422, lambda: policy(**changes))
    assert get('owner-policy:clinic-east') is None


def test_version_permission_notification_authority_and_legacy_preservation(receiver):
    saved = policy()
    payload = {'version': saved['version'], 'ack_minutes': 7, 'reason': 'SYNTHETIC legacy internal-target change'}
    err(403, lambda: act('conversation.policy', payload))
    changed = act('conversation.policy', payload, actor='clinic-east-admin')
    assert changed['data']['escalation'] == saved['data']['escalation']
    err(409, lambda: act('conversation.policy', {**payload, 'escalation': {'enabled': False}}, actor='clinic-east-admin'))
    assert get(saved['id'])['data']['escalation']['enabled'] is True
    with db.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM audit WHERE action='conversation.policy'").fetchone()[0] == 2


@pytest.mark.parametrize('revocation', ['inactive', 'role', 'route_removed', 'route_changed', 'token_changed', 'disabled', 'policy_disabled'])
def test_dispatch_revalidates_selected_member_destination_and_enabled_policy(receiver, monkeypatch, revocation):
    receipts, _, routes = receiver
    policy(); question(grant(), urgent=True)
    if revocation in ('inactive', 'role'):
        member = get('clinic-east-vet')
        with db.connection(True) as c: db.update(c, member, {**member['data'], **({'active': False} if revocation == 'inactive' else {'role': 'owner'})})
    elif revocation == 'disabled': monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_MODE', 'disabled')
    elif revocation == 'policy_disabled': policy(enabled=False)
    else:
        if revocation == 'route_removed': routes.pop('primary')
        elif revocation == 'route_changed': routes['primary']['url'] += '-changed'
        else: routes['primary']['token'] = 'changed-secret'
        monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_ROUTES', json.dumps(routes))
    escalation.scan()
    assert not escalation.send_one() and receipts == []
    assert incidents()[0]['blocked_reason']
    assert incidents()[0]['state'] == 'awaiting_ack'


def test_notification_authority_does_not_grant_read_roles(receiver):
    policy()
    member = get('clinic-east-nurse')
    with db.connection(True) as c: db.update(c, member, {**member['data'], 'read_restrictions': ['read.billing']})
    thread = question(grant(), urgent=True)
    escalation.scan(future(incidents()[0], 'primary')); escalation.send_one()
    assert receiver[0][0]['payload']['stage'] == 'backup'
    client = TestClient(main.app)
    assert client.get('/api/clinical-escalations', headers={'x-actor-id': 'clinic-east-nurse'}).status_code == 403
    current = get(thread['id'])
    err(403, lambda: act('conversation.acknowledge', {'id': current['id'], 'version': current['version'], 'last_owner_turn': current['data']['last_owner_turn'], 'reason': 'SYNTHETIC restricted review'}, actor='clinic-east-nurse'))


def test_http_failure_retry_uses_stable_id_and_redirect_is_not_followed(receiver):
    receipts, responses, _ = receiver
    policy(); question(grant(), urgent=True)
    responses.append(503); assert escalation.send_one()
    assert incidents()[0]['events'][0]['status'] == 'queued'
    with db.connection(True) as c: c.execute('UPDATE clinical_escalation_events SET next_attempt=0')
    assert escalation.send_one()
    assert receipts[0]['key'] == receipts[1]['key']
    assert [r['outcome'] for r in incidents()[0]['events'][0]['receipts']] == ['retryable_http', 'accepted']
    escalation.scan(future(incidents()[0], 'primary')); responses.append(302); escalation.send_one()
    assert len(receipts) == 3 and incidents()[0]['events'][-1]['status'] == 'failed'
    assert not incidents()[0]['acknowledged_at']


def test_exhausted_primary_still_reaches_backup_and_retains_receipts(receiver):
    _, responses, _ = receiver
    policy(); question(grant(), urgent=True)
    responses.extend([503]*escalation.MAX_ATTEMPTS)
    for _ in range(escalation.MAX_ATTEMPTS):
        with db.connection(True) as c: c.execute('UPDATE clinical_escalation_events SET next_attempt=0')
        escalation.send_one()
    assert incidents()[0]['events'][0]['status'] == 'failed'
    escalation.scan(future(incidents()[0], 'primary')); escalation.send_one()
    assert incidents()[0]['events'][-1]['status'] == 'accepted'
    assert len(incidents()[0]['events'][0]['receipts']) == escalation.MAX_ATTEMPTS


def test_interrupted_claim_recovers_without_duplicate_incident(receiver):
    policy(); thread = question(grant(), urgent=True)
    event = escalation.claim()
    assert event and not escalation.claim()
    with db.connection(True) as c: c.execute('UPDATE clinical_escalation_events SET lease_until=0 WHERE id=?', (event['id'],))
    assert escalation.send_one()
    current = incidents()[0]['events'][0]
    assert current['id'] == event['id'] and current['attempts'] == 2
    assert [r['outcome'] for r in current['receipts']] == ['interrupted', 'accepted']
    with db.connection(True) as c: escalation.attention(c, db.get(c, thread['id']))
    assert len(incidents()) == 1


def test_concurrent_claim_and_scan_create_one_backup(receiver):
    policy(); question(grant(), urgent=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: escalation.claim(), range(2)))
    assert sum(r is not None for r in results) == 1
    deadline = future(incidents()[0], 'primary')
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(lambda _: escalation.scan(deadline), range(2)))
    assert len([e for e in incidents()[0]['events'] if e['stage'] == 'backup']) == 1


def test_ack_between_claim_and_dispatch_prevents_send(receiver, monkeypatch):
    policy(); thread = question(grant(), urgent=True)
    original = escalation.claim
    def claim_then_ack():
        event = original(); transition(thread); return event
    monkeypatch.setattr(escalation, 'claim', claim_then_ack)
    assert escalation.send_one() and receiver[0] == []
    assert incidents()[0]['events'][0]['status'] == 'superseded'


def test_new_owner_turn_needs_new_incident_and_old_review_is_stale(receiver):
    policy(); token = grant(); first = question(token, urgent=True); old = get(first['id'])
    question(token, thread_id=first['id'], urgent=True, message='SYNTHETIC new urgent input')
    assert len(incidents()) == 2 and {i['state'] for i in incidents()} == {'awaiting_ack', 'superseded'}
    err(409, lambda: act('conversation.acknowledge', {'id': old['id'], 'version': old['version'], 'last_owner_turn': old['data']['last_owner_turn'], 'reason': 'Stale review'}))
    transition(first)
    assert {i['state'] for i in incidents()} == {'acknowledged', 'superseded'}


def test_status_is_tenant_scoped_and_contains_no_destination_secrets(receiver):
    policy(); question(grant(), urgent=True); escalation.scan()
    client = TestClient(main.app)
    response = client.get('/api/clinical-escalations')
    assert response.status_code == 200 and len(response.json()['incidents']) == 1
    assert all(secret not in response.text for secret in ('http://', 'SYNTHETIC-secret', 'destination_revision'))
    other = client.get('/api/clinical-escalations', headers={'x-clinic-id': 'clinic-river', 'x-actor-id': 'clinic-river-vet'})
    assert other.status_code == 200 and other.json()['incidents'] == []


@pytest.mark.parametrize('mode,url,hosted', [
    ('webhook', 'http://127.0.0.1/primary', False),
    ('test-loopback', 'http://example.com/primary', False),
    ('test-loopback', 'http://127.0.0.1/primary', True),
    ('webhook', 'https://user:secret@example.com/', False),
    ('webhook', 'https://example.com/#fragment', False),
])
def test_configuration_refuses_unapproved_network_modes(monkeypatch, mode, url, hosted):
    monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_MODE', mode)
    monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_ROUTES', json.dumps({'primary': {'url': url}}))
    monkeypatch.setattr('runtime.hosted', lambda: hosted)
    with pytest.raises(ValueError): escalation.configuration()


def test_policy_edit_preserves_existing_question_deadlines_and_future_scope(receiver):
    import owner_conversations
    first = policy(); thread = question(grant(), request_staff=True)
    policy(primary_timeout_seconds=300, backup_timeout_seconds=400)
    with db.connection(True) as c: owner_conversations.tick(c, 'clinic-east', datetime.now(timezone.utc)+timedelta(minutes=2))
    incident = incidents()[0]
    assert incident['policy']['primary_timeout_seconds'] == 60
    assert incident['policy']['backup_timeout_seconds'] == 60
    question(grant(), urgent=True)
    assert incidents()[0]['policy']['primary_timeout_seconds'] == 300


def test_stopped_dispatcher_deadlines_remain_visible_without_a_scan(receiver):
    policy(); question(grant(), urgent=True)
    past = (datetime.now(timezone.utc)-timedelta(seconds=45)).isoformat()
    with db.connection(True) as c:
        c.execute('UPDATE clinical_escalations SET backup_due_at=?', (past,))
        db.upsert(c, 'clinical_escalation_monitor', {'name': 'clinical', 'heartbeat_at': past}, ['name'])
    with db.connection() as c: value = escalation.status(c, 'clinic-east')
    assert value['monitor_state'] == 'overdue'
    assert value['incidents'][0]['state'] == 'manual_fallback'
    assert value['incidents'][0]['persisted_state'] == 'awaiting_ack'
    assert not value['incidents'][0]['acknowledged_at']


def test_fresh_route_review_does_not_redirect_old_queued_incident(receiver, monkeypatch):
    _, _, routes = receiver
    policy(); question(grant(), urgent=True); old = incidents()[0]['id']
    routes['primary']['url'] += '-replacement'
    monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_ROUTES', json.dumps(routes))
    policy(); question(grant(), urgent=True)
    assert escalation.send_one()
    assert receiver[0][0]['path'] == '/primary-replacement'
    assert receiver[0][0]['payload']['incident_id'] != old
    assert not escalation.send_one()
    response = TestClient(main.app).get('/api/bootstrap')
    with db.connection() as c:
        registry = c.execute('SELECT digest,revision FROM clinical_escalation_routes').fetchall()
    assert all(r['digest'] not in response.text for r in registry)
    assert all(r['revision'] != r['digest'] for r in registry)


def test_real_sender_kill_after_receiver_application_recovers_same_event(monkeypatch):
    from test_operational_alerts import webhook
    root = Path(__file__).resolve().parents[2]
    release, received_first = threading.Event(), threading.Event()
    with webhook([204], release, received_first) as (url, received):
        monkeypatch.setenv('BROBY_ENVIRONMENT', 'local')
        monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_MODE', 'test-loopback')
        monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_ROUTES', json.dumps({'primary': {'url': url+'/primary'}, 'backup': {'url': url+'/backup'}}))
        policy(); question(grant(), urgent=True)
        event = incidents()[0]['events'][0]
        common = 'import os;from pathlib import Path;import db;db.DB=Path(os.environ["SYNTHETIC_TEST_DB"]);import clinical_escalations as a;'
        env = {**os.environ, 'SYNTHETIC_TEST_DB': str(db.DB), 'BROBY_DATA_DIR': str(db.DATA), 'PYTHONPATH': str(root/'api')}
        sender = subprocess.Popen([sys.executable, '-c', common+'a.LEASE_SECONDS=.3;a.send_one()'], cwd=root/'api', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert received_first.wait(5)
            sender.kill(); sender.wait(timeout=3)
            assert incidents()[0]['events'][0]['status'] == 'sending'
            assert not incidents()[0]['events'][0]['accepted_at']
            release.set(); time.sleep(.35)
            restarted = subprocess.run([sys.executable, '-c', common+'a.send_one()'], cwd=root/'api', env=env, capture_output=True, timeout=10)
            assert restarted.returncode == 0
            assert len(received) == 2 and sum(r['first_application'] for r in received) == 1
            assert all(r['headers']['Idempotency-Key'] == event['id'] for r in received)
            result = incidents()[0]
            assert result['events'][0]['status'] == 'accepted' and result['events'][0]['attempts'] == 2
            assert not result['acknowledged_at']
        finally:
            release.set()
            if sender.poll() is None:
                sender.kill(); sender.wait(timeout=3)


@pytest.mark.parametrize('disable_policy',[False,True])
def test_new_input_immediately_supersedes_before_retrieval_even_without_opt_in(receiver, monkeypatch, disable_policy):
    import owner_conversations
    policy(); token=grant(); first=question(token,urgent=True)
    old=incidents()[0]['id']
    if disable_policy:policy(enabled=False)
    def during_retrieval(message):
        previous=next(i for i in incidents() if i['id']==old)
        assert previous['state']=='superseded'
        assert not escalation.send_one()
        return 'staff','rules'
    monkeypatch.setattr(owner_conversations,'topic',during_retrieval)
    question(token,thread_id=first['id'],message='SYNTHETIC new input while retrieval runs')
    if disable_policy:
        policy()
        assert not escalation.send_one() and receiver[0]==[]


def test_bounded_status_prioritizes_unresolved_and_exposes_truncation(receiver):
    policy()
    unresolved=question(grant(),urgent=True); pending=incidents()[0]['id']
    for index in range(31):
        patient=act('patient.create',{'name':f'SYNTHETIC queue patient {index}','species':'Cat','owner_name':f'SYNTHETIC queue owner {index}'})
        done=question(grant(patient['id']),urgent=True);transition(done)
    with db.connection() as c:value=escalation.status(c,'clinic-east')
    assert value['unresolved_count']==1 and value['counts']['acknowledged']==31
    assert len(value['incidents'])==value['incident_limit']==30 and value['truncated']
    assert value['incidents'][0]['id']==pending


from test_clinical_reconciliation import sqlite_native, fixture, preview, decision
from test_transfers import TARGET, HEADERS
import clinical_reconciliation


def test_held_patient_escalation_review_reason_is_qualified(monkeypatch):
    monkeypatch.setenv('BROBY_ENVIRONMENT', 'local')
    monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_MODE', 'test-loopback')
    monkeypatch.setenv('BROBY_CLINICAL_ESCALATION_ROUTES', json.dumps({stage: {'url': 'http://127.0.0.1:9/'+stage} for stage in ('primary','backup')}))
    client, old, new, correction = fixture()
    escalation = {'enabled': True, 'primary_member_id': 'clinic-river-vet', 'backup_member_id': 'clinic-river-admin',
                  'primary_route': 'primary', 'backup_route': 'backup', 'primary_timeout_seconds': 60,
                  'backup_timeout_seconds': 60, 'fallback_instructions': 'SYNTHETIC clinic contact procedure.',
                  'recipient_authority_confirmed': True}
    act('conversation.policy', {'version': 0, 'ack_minutes': 1, 'escalation': escalation,
                               'reason': 'SYNTHETIC route policy'}, clinic='clinic-river', actor='clinic-river-admin')
    token = act('share.create', {'patient_id': old['id']}, **TARGET)['id']
    first = question(token, urgent=True, message='SYNTHETIC question before identity hold')
    current = get(first['id'])
    reason = 'SYNTHETIC clinical claim: old transferred medication instructions were confirmed for this patient.'
    act('conversation.acknowledge', {'id': current['id'], 'version': current['version'],
                                   'last_owner_turn': current['data']['last_owner_turn'], 'reason': reason}, **TARGET)
    act('clinical.reconcile', decision(preview(client, correction), old['id']), **TARGET)
    with db.connection() as c:
        assert old['id'] in clinical_reconciliation.eligibility(c, 'clinic-river')['patients']
    result = client.get('/api/clinical-escalations', headers=HEADERS)
    assert result.status_code == 200
    incident = result.json()['incidents'][0]
    assert incident['acknowledgement_reason']==reason and incident['reviews'][0]['reason']==reason
    assert incident['state']=='acknowledged'
    assert incident['clinical_reconciliation']['current_clinical_use'] is False
    assert incident.get('clinical_reconciliation'), 'Historical clinical review text appears without identity-hold qualification'
