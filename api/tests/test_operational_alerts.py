"""Synthetic operational incidents and real loopback webhook failure/recovery."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import db
import main
import operational_alerts as alerts
from operations_health import LABELS
from test_integrity import isolated, act

ROOT = Path(__file__).resolve().parents[2]
ADMIN = {'x-clinic-id': 'clinic-east', 'x-actor-id': 'clinic-east-admin'}


@pytest.fixture(autouse=True)
def environment(isolated, monkeypatch):
    monkeypatch.setenv('BROBY_ENVIRONMENT', 'local')
    monkeypatch.setenv('BROBY_AUTH_MODE', 'demo')
    monkeypatch.setenv('BROBY_ENABLE_AI', '0')
    monkeypatch.setenv('BROBY_OPS_ALERT_MODE', 'disabled')
    monkeypatch.setenv('BROBY_DATA_DIR', str(db.DATA))
    monkeypatch.delenv('BROBY_OPS_ALERT_WEBHOOK_URL', raising=False)
    monkeypatch.delenv('BROBY_OPS_ALERT_WEBHOOK_TOKEN', raising=False)
    monkeypatch.setattr(main.app.state, 'workers', None, raising=False)
    healthy_worker()


def healthy_worker():
    with db.connection(True) as c:
        db.upsert(c, 'worker_runtime', {'name': 'background', 'owner_id': db.uid(), 'storage_id': db.uid(),
            'mode': 'embedded', 'started_at': db.now(), 'heartbeat_at': db.now(), 'stopped_at': None,
            'snapshot': json.dumps([{'name': name, 'state': 'idle', 'consecutive_failures': 0} for name in LABELS])}, ['name'])


def enable(monkeypatch, url='https://ops.example.test/PRIVATE-destination?key=PRIVATE-url-key'):
    monkeypatch.setenv('BROBY_OPS_ALERT_MODE', 'test-loopback' if url.startswith('http://127.0.0.1:') else 'webhook')
    monkeypatch.setenv('BROBY_OPS_ALERT_WEBHOOK_URL', url)
    monkeypatch.setenv('BROBY_OPS_ALERT_WEBHOOK_TOKEN', 'PRIVATE-webhook-token')


def failed_job(id='synthetic-job', clinic='clinic-east'):
    with db.connection(True) as c:
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)', (id, clinic, 'PRIVATE-consultation', 'failed',
            json.dumps({'text': 'PRIVATE-patient-source'}), json.dumps({'provider': 'PRIVATE-provider-receipt'}),
            'PRIVATE-error with PRIVATE-credentials', db.now(), db.now()))


def incident(clinic='clinic-east', key='queue:documents'):
    with db.connection() as c:
        return dict(c.execute('SELECT * FROM ops_incidents WHERE clinic_id=? AND condition_key=? ORDER BY opened_at DESC LIMIT 1', (clinic, key)).fetchone())


def events():
    with db.connection() as c:
        return [dict(row) for row in c.execute('SELECT * FROM ops_alert_events ORDER BY created_at,id')]


@contextmanager
def webhook(statuses, block_first=None, first_received=None):
    received = []
    applied = set()
    receiver_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length'])).decode()
            with receiver_lock:
                event_id = self.headers['Idempotency-Key']
                received.append({'path': self.path, 'headers': dict(self.headers), 'body': body,
                                 'first_application': event_id not in applied})
                applied.add(event_id)
                index = len(received)-1
            if index == 0 and first_received:
                first_received.set()
            if index == 0 and block_first:
                block_first.wait(5)
            try:
                self.send_response(statuses[min(index, len(statuses)-1)])
                self.send_header('Location', '/PRIVATE-redirect-target')
                self.end_headers()
                self.wfile.write(b'PRIVATE-provider-response-body')
            except OSError:
                pass  # The killed synthetic sender no longer has a socket.
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/synthetic-alert?key=PRIVATE-url-key', received
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_disabled_default_never_scans_claims_or_sends(monkeypatch):
    failed_job()
    monkeypatch.setattr(alerts.http.client, 'HTTPSConnection', lambda *a, **k: pytest.fail('No network in disabled mode'))
    alerts.tick()
    assert not alerts.send_one()
    assert events() == []
    with db.connection() as c:
        value = alerts.status(c, 'clinic-east')
        assert value['mode'] == value['monitor_state'] == 'disabled'


@pytest.mark.parametrize('mode,url,environment', [
    ('webhook', 'http://127.0.0.1:1', 'local'),
    ('test-loopback', 'http://example.test', 'local'),
    ('test-loopback', 'http://127.0.0.1:1', 'staging'),
    ('webhook', 'https://user:PRIVATE@example.test', 'local'),
    ('webhook', 'https://example.test/#PRIVATE', 'local'),
    ('webhook', 'https://example.test:bad', 'local'),
])
def test_destination_validation_fails_closed(monkeypatch, mode, url, environment):
    monkeypatch.setenv('BROBY_OPS_ALERT_MODE', mode)
    monkeypatch.setenv('BROBY_OPS_ALERT_WEBHOOK_URL', url)
    monkeypatch.setenv('BROBY_ENVIRONMENT', environment)
    with pytest.raises(ValueError):
        alerts.configuration()
    assert events() == []


def test_queue_incidents_are_atomic_clinic_scoped_and_payload_free(monkeypatch):
    enable(monkeypatch); failed_job()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: alerts.scan(), range(2)))
    assert len(events()) == 1
    record = incident()
    assert record['state'] == 'open' and record['version'] == 1
    output = events()[0]['payload']
    assert 'PRIVATE' not in output and 'clinic-east' not in output and 'synthetic-job' not in output
    assert json.loads(output)['condition'] == {'category': 'queue', 'queue': 'documents', 'counts': {'failed': 1}}
    with db.connection() as c:
        assert alerts.status(c, 'clinic-river')['incidents'] == []


def test_observed_recovery_and_new_failure_have_distinct_events_and_incidents(monkeypatch):
    enable(monkeypatch); failed_job(); alerts.scan(); original = incident()
    with db.connection(True) as c:
        c.execute("UPDATE jobs SET status='completed'")
    alerts.scan(); alerts.scan()
    recovered = incident()
    assert recovered['id'] == original['id'] and recovered['state'] == 'recovered'
    assert {event['kind'] for event in events()} == {'opened', 'recovered'}
    assert events()[0]['status'] == 'superseded'
    assert json.loads(events()[1]['payload'])['condition']['counts'] == {}
    assert not recovered['acknowledged_at']
    failed_job('synthetic-second'); alerts.scan()
    assert incident()['id'] != original['id'] and len(events()) == 3


def test_recovery_supersedes_old_retry_and_sends_ordered_recovery_event(monkeypatch):
    with webhook([503, 204]) as (url, received):
        enable(monkeypatch, url); failed_job(); alerts.scan(); alerts.send_one()
        with db.connection(True) as c:
            c.execute("UPDATE jobs SET status='completed'")
        alerts.scan()
        assert events()[0]['status'] == 'superseded'
        assert alerts.send_one()
        assert [json.loads(r['body'])['sequence'] for r in received] == [1, 2]
        assert json.loads(received[1]['body'])['kind'] == 'recovered'
        assert events()[1]['status'] == 'accepted'
        assert not alerts.send_one()


def test_transport_exceptions_never_store_or_log_url_credentials_or_raw_message(monkeypatch, caplog):
    enable(monkeypatch); failed_job(); alerts.scan()
    def broken(*a, **k):
        raise OSError('PRIVATE raw network message https://PRIVATE-destination/?PRIVATE-token')
    monkeypatch.setattr(alerts.http.client, 'HTTPSConnection', broken)
    alerts.send_one()
    assert events()[0]['last_error_code'] == 'network_error'
    with db.connection() as c:
        output = json.dumps(alerts.status(c, 'clinic-east'))
    assert 'PRIVATE' not in output+json.dumps(events())+caplog.text


def test_repeated_failures_stale_process_and_disabled_provider_have_distinct_conditions(monkeypatch):
    enable(monkeypatch)
    snapshot = [{'name': n, 'state': 'disabled', 'consecutive_failures': 0} for n in LABELS]
    snapshot[0].update(state='retry_wait', consecutive_failures=2)
    with db.connection(True) as c:
        c.execute('UPDATE worker_runtime SET snapshot=?', (json.dumps(snapshot),))
    alerts.scan(); assert not events()
    snapshot[0]['consecutive_failures'] = 3
    with db.connection(True) as c:
        c.execute('UPDATE worker_runtime SET snapshot=?', (json.dumps(snapshot),))
    alerts.scan()
    assert incident(key='worker:documents')['state'] == 'open'
    assert len(events()) == 2  # shared worker condition is scoped for each clinic
    with db.connection(True) as c:
        c.execute('UPDATE worker_runtime SET heartbeat_at=?', ((datetime.now(timezone.utc)-timedelta(seconds=31)).isoformat(),))
    alerts.scan()
    assert incident(key='worker:runtime')['state'] == 'open'
    assert json.loads(incident(key='worker:runtime')['details'])['state'] == 'overdue'


def test_actual_webhook_503_retries_same_event_then_records_2xx_without_private_data(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(alerts, 'RETRY_BASE_SECONDS', .05)
    with webhook([503, 204]) as (url, received):
        enable(monkeypatch, url); failed_job(); alerts.scan()
        assert alerts.send_one()
        first = events()[0]
        assert first['status'] == 'queued' and first['attempts'] == 1 and first['last_error_code'] == 'retryable_http'
        assert not alerts.send_one()
        time.sleep(.06)
        assert alerts.send_one()
        event = events()[0]
        assert event['status'] == 'accepted' and event['accepted_at'] and event['attempts'] == 2
        assert len(received) == 2 and received[0]['body'] == received[1]['body']
        assert received[0]['headers']['Idempotency-Key'] == received[1]['headers']['Idempotency-Key'] == event['id']
        assert received[0]['path'].endswith('?key=PRIVATE-url-key')
        assert received[0]['headers']['Authorization'] == 'Bearer PRIVATE-webhook-token'
    with db.connection() as c:
        receipts = [dict(r) for r in c.execute('SELECT * FROM ops_alert_attempts ORDER BY attempt')]
        assert [r['http_status'] for r in receipts] == [503, 204]
        assert [r['outcome'] for r in receipts] == ['retryable_http', 'accepted']
        output = json.dumps(alerts.status(c, 'clinic-east'))
    assert 'PRIVATE' not in output+json.dumps(events())+json.dumps(receipts)+caplog.text


def test_redirect_is_never_followed_and_manual_retry_preserves_receipts(monkeypatch):
    with webhook([302, 204]) as (url, received):
        enable(monkeypatch, url); failed_job(); alerts.scan(); alerts.send_one()
        event = events()[0]; old = incident()
        assert len(received) == 1 and event['status'] == 'failed'
        result = act('operations.alert.retry', {'id': old['id'], 'version': old['version'], 'event_id': event['id'],
                     'reason': 'SYNTHETIC fixed destination review'}, actor='clinic-east-admin', key='retry-operational-event')
        assert result['state'] == 'open' and not result['acknowledged_at']
        assert events()[0]['attempts'] == 1 and events()[0]['payload'] == event['payload']
        alerts.send_one()
        assert events()[0]['status'] == 'accepted' and events()[0]['attempts'] == 2
        assert received[0]['headers']['Idempotency-Key'] == received[1]['headers']['Idempotency-Key']
        with db.connection() as c:
            assert c.execute('SELECT COUNT(*) FROM ops_incident_actions').fetchone()[0] == 1
            assert c.execute('SELECT COUNT(*) FROM ops_alert_attempts').fetchone()[0] == 2


def test_retry_exhaustion_and_interrupted_last_attempt_become_visible_failures(monkeypatch):
    monkeypatch.setattr(alerts, 'MAX_ATTEMPTS', 1)
    with webhook([503]) as (url, _):
        enable(monkeypatch, url); failed_job(); alerts.scan(); alerts.send_one()
        assert events()[0]['status'] == 'failed' and not alerts.send_one()
    with db.connection(True) as c:
        c.execute("UPDATE ops_alert_events SET status='queued',attempts=0,lease_until=0,next_attempt=0")
        c.execute('DELETE FROM ops_alert_attempts')
    claimed = alerts.claim()
    assert claimed and alerts.claim(time.time()+61) is None
    assert events()[0]['status'] == 'failed' and events()[0]['last_error_code'] == 'interrupted'


def test_acknowledgement_is_audited_versioned_and_does_not_change_delivery_or_recovery(monkeypatch):
    enable(monkeypatch); failed_job(); alerts.scan(); original = incident(); event = events()[0]
    payload = {'id': original['id'], 'version': original['version'], 'reason': 'PRIVATE reviewed infrastructure logs'}
    result = act('operations.alert.acknowledge', payload, actor='clinic-east-admin', key='ack-operational-incident')
    assert result['state'] == 'open' and not result['recovered_at']
    assert result['acknowledged_by'] == 'clinic-east-admin' and result['acknowledged_at']
    assert events()[0] == event
    assert act('operations.alert.acknowledge', payload, actor='clinic-east-admin', key='ack-operational-incident') == result
    with db.connection() as c:
        assert c.execute('SELECT COUNT(*) FROM ops_incident_actions').fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM audit WHERE action='operations.alert.acknowledge'").fetchone()[0] == 1
    assert 'PRIVATE' not in events()[0]['payload']
    with db.connection(True) as c:
        c.execute("UPDATE jobs SET status='completed'")
    alerts.scan()
    assert incident()['state'] == 'recovered' and incident()['acknowledged_at'] == result['acknowledged_at']


@pytest.mark.parametrize('actor,clinic', [('clinic-east-vet','clinic-east'), ('clinic-east-nurse','clinic-east'), ('clinic-river-admin','clinic-river')])
def test_nonadmin_and_cross_clinic_acknowledgement_are_rejected(monkeypatch, actor, clinic):
    enable(monkeypatch); failed_job(); alerts.scan(); original = incident()
    with pytest.raises(HTTPException) as error:
        act('operations.alert.acknowledge', {'id': original['id'], 'version': original['version'], 'reason': 'review'}, actor=actor, clinic=clinic)
    assert error.value.status_code in (403, 404)
    assert not incident()['acknowledged_at']


def test_stale_review_inactive_admin_and_missing_reason_are_rejected(monkeypatch):
    enable(monkeypatch); failed_job(); alerts.scan(); original = incident()
    failed_job('new-failure'); alerts.scan()
    p = {'id': original['id'], 'version': original['version'], 'reason': 'review'}
    with pytest.raises(HTTPException) as error:
        act('operations.alert.acknowledge', p, actor='clinic-east-admin')
    assert error.value.status_code == 409
    p['version'] = incident()['version']; p['reason'] = '  '
    with pytest.raises(HTTPException) as error:
        act('operations.alert.acknowledge', p, actor='clinic-east-admin')
    assert error.value.status_code == 422
    with db.connection(True) as c:
        member = db.get(c, 'clinic-east-admin'); db.update(c, member, {**member['data'], 'active': False})
    with pytest.raises(HTTPException) as error:
        act('operations.alert.acknowledge', {**p, 'reason': 'review'}, actor='clinic-east-admin')
    assert error.value.status_code == 403


def test_health_readback_keeps_clinic_boundary_and_monitor_freshness(monkeypatch):
    enable(monkeypatch); failed_job(); alerts.scan()
    client = TestClient(main.app)
    result = client.get('/api/operations/health', headers=ADMIN)
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    assert result.json()['operational_alerts']['monitor_state'] == 'checked'
    foreign = client.get('/api/operations/health', headers={'x-clinic-id':'clinic-river','x-actor-id':'clinic-river-admin'})
    assert foreign.json()['operational_alerts']['incidents'] == []
    with db.connection(True) as c:
        c.execute('UPDATE ops_alert_monitor SET heartbeat_at=?', ((datetime.now(timezone.utc)-timedelta(seconds=91)).isoformat(),))
    assert client.get('/api/operations/health', headers=ADMIN).json()['operational_alerts']['monitor_state'] == 'overdue'


def test_real_claimant_kill_is_recovered_by_restarted_monitor_with_same_event(monkeypatch, tmp_path):
    with webhook([204]) as (url, received):
        enable(monkeypatch, url); failed_job(); alerts.scan()
        event = events()[0]; marker = tmp_path/'ops-claimed'
        common = 'import os,sys,time;from pathlib import Path;import db;db.DB=Path(os.environ["SYNTHETIC_TEST_DB"]);import operational_alerts as a;'
        env = {**os.environ, 'SYNTHETIC_TEST_DB': str(db.DB), 'PYTHONPATH': str(ROOT/'api')}
        first = subprocess.Popen([sys.executable, '-c', common+'a.LEASE_SECONDS=.3;e=a.claim();Path('+repr(str(marker))+').write_text(e["id"]);time.sleep(60)'],
                                 cwd=ROOT/'api', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:
                time.sleep(.02)
            assert marker.read_text() == event['id']
            first.kill(); first.wait(timeout=3)
            time.sleep(.35)
            restarted = subprocess.run([sys.executable, '-c', common+'sys.argv=["operational_alerts.py","--once"];raise SystemExit(a.main())'],
                                       cwd=ROOT/'api', env=env, capture_output=True, timeout=10)
            assert restarted.returncode == 0
            assert len(received) == 1 and received[0]['headers']['Idempotency-Key'] == event['id']
            assert events()[0]['status'] == 'accepted' and events()[0]['attempts'] == 2
            with db.connection() as c:
                assert [r[0] for r in c.execute('SELECT outcome FROM ops_alert_attempts ORDER BY attempt')] == ['interrupted', 'accepted']
        finally:
            if first.poll() is None:
                first.kill(); first.wait(timeout=3)


def test_receiver_acceptance_before_sender_loss_retries_with_the_same_dedupe_reference(monkeypatch):
    release = threading.Event(); received_first = threading.Event()
    with webhook([204], release, received_first) as (url, received):
        enable(monkeypatch, url); failed_job(); alerts.scan(); event = events()[0]
        common = 'import os;from pathlib import Path;import db;db.DB=Path(os.environ["SYNTHETIC_TEST_DB"]);import operational_alerts as a;'
        env = {**os.environ, 'SYNTHETIC_TEST_DB': str(db.DB), 'PYTHONPATH': str(ROOT/'api')}
        sender = subprocess.Popen([sys.executable, '-c', common+'a.LEASE_SECONDS=.3;a.send_one()'],
                                  cwd=ROOT/'api', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert received_first.wait(5)
            # The receiver has applied this event, but the sender has no HTTP
            # receipt. This is deliberately not marked accepted in Broby.
            sender.kill(); sender.wait(timeout=3)
            assert events()[0]['status'] == 'sending' and not events()[0]['accepted_at']
            release.set(); time.sleep(.35)
            restarted = subprocess.run([sys.executable, '-c', common+'a.send_one()'], cwd=ROOT/'api',
                                       env=env, capture_output=True, timeout=10)
            assert restarted.returncode == 0
            assert len(received) == 2 and sum(r['first_application'] for r in received) == 1
            assert all(r['headers']['Idempotency-Key'] == event['id'] for r in received)
            assert events()[0]['status'] == 'accepted' and events()[0]['attempts'] == 2
        finally:
            release.set()
            if sender.poll() is None:
                sender.kill(); sender.wait(timeout=3)
