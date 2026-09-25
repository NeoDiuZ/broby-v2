"""Optional operational webhook monitor; never clinical emergency escalation.

The configured destination is fixed outside the application. Only allowlisted
worker states and aggregate queue counts leave this process. Acceptance of a
webhook, a human acknowledgement, and observed recovery are separate facts.
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import http.client
import json
import logging
import os
import signal
import threading
import time
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import db
import runtime

PERMISSIONS = {name: {'admin'} for name in ('operations.alert.acknowledge', 'operations.alert.retry')}
MAX_ATTEMPTS = 6
RETRY_BASE_SECONDS = 30
LEASE_SECONDS = 60
POLL_SECONDS = 15
MONITOR_STALE_SECONDS = 90
QUEUE_STATES = {'documents': ('failed', 'conflict', 'overdue'),
                'payments': ('failed', 'overdue'),
                'messaging': ('failed', 'undelivered', 'uncertain', 'needs_review', 'blocked')}


@dataclass(frozen=True)
class Config:
    mode: str
    url: str = field(default='', repr=False)
    token: str = field(default='', repr=False)


def configuration():
    mode = os.getenv('BROBY_OPS_ALERT_MODE', 'disabled')
    if mode == 'disabled':
        return Config(mode)
    if mode not in ('webhook', 'test-loopback'):
        raise ValueError('Unsupported operational alert mode')
    address = os.getenv('BROBY_OPS_ALERT_WEBHOOK_URL', '')
    token = os.getenv('BROBY_OPS_ALERT_WEBHOOK_TOKEN', '')
    parts = urlsplit(address)
    _ = parts.port  # Reject an invalid port before claiming any event.
    if not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Operational alerts require a configured webhook destination')
    if parts.scheme != 'https':
        if mode != 'test-loopback' or runtime.hosted() or parts.scheme != 'http':
            raise ValueError('Operational alerts require HTTPS')
        if not ipaddress.ip_address(parts.hostname).is_loopback:
            raise ValueError('Synthetic webhook tests require a loopback destination')
    elif mode == 'test-loopback':
        if runtime.hosted() or not ipaddress.ip_address(parts.hostname).is_loopback:
            raise ValueError('Synthetic webhook tests require a local loopback destination')
    if any(char in address or char in token for char in ('\r', '\n')):
        raise ValueError('Invalid operational alert configuration')
    return Config(mode, address, token)


def setup(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS ops_incidents(
        id TEXT PRIMARY KEY,clinic_id TEXT NOT NULL,condition_key TEXT NOT NULL,
        state TEXT NOT NULL,version INTEGER NOT NULL,details TEXT NOT NULL,
        opened_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,recovered_at TEXT,
        acknowledged_at TEXT,acknowledged_by TEXT,acknowledgement_reason TEXT);
    CREATE UNIQUE INDEX IF NOT EXISTS ops_incidents_open
        ON ops_incidents(clinic_id,condition_key) WHERE state='open';
    CREATE INDEX IF NOT EXISTS ops_incidents_clinic ON ops_incidents(clinic_id,opened_at);
    CREATE TABLE IF NOT EXISTS ops_alert_events(
        id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,clinic_id TEXT NOT NULL,
        kind TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,retry_limit INTEGER NOT NULL,
        next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
        lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,token TEXT,
        accepted_at TEXT,last_error_code TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
        UNIQUE(incident_id,kind));
    CREATE INDEX IF NOT EXISTS ops_alert_events_due ON ops_alert_events(status,next_attempt,lease_until);
    CREATE TABLE IF NOT EXISTS ops_alert_attempts(
        event_id TEXT NOT NULL,attempt INTEGER NOT NULL,token TEXT NOT NULL,
        started_at TEXT NOT NULL,finished_at TEXT,outcome TEXT NOT NULL,http_status INTEGER,
        PRIMARY KEY(event_id,attempt));
    CREATE TABLE IF NOT EXISTS ops_incident_actions(
        id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,clinic_id TEXT NOT NULL,event_id TEXT,
        action TEXT NOT NULL,actor_id TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS ops_alert_monitor(
        name TEXT PRIMARY KEY,heartbeat_at TEXT NOT NULL,last_scan_at TEXT NOT NULL);
    ''')


def _count(value):
    return min(10**9, max(0, int(value or 0)))


def conditions(c, instant):
    """Generate diagnostics from existing health data, never source/job payloads."""
    from operations_health import LABELS, queue_summary
    from worker_runtime import STALE_SECONDS
    row = c.execute("SELECT * FROM worker_runtime WHERE name='background'").fetchone()
    common = {}
    if not row:
        common['worker:runtime'] = {'category': 'worker', 'worker': 'runtime', 'state': 'missing'}
    elif row['stopped_at'] or (instant-datetime.fromisoformat(row['heartbeat_at'])).total_seconds() > STALE_SECONDS:
        common['worker:runtime'] = {'category': 'worker', 'worker': 'runtime',
                                    'state': 'stopped' if row['stopped_at'] else 'overdue'}
    else:
        snapshot = {v['name']: v for v in json.loads(row['snapshot']) if v.get('name') in LABELS}
        startup_age = (instant-datetime.fromisoformat(row['started_at'])).total_seconds()
        for name in LABELS:
            worker = snapshot.get(name, {'state': 'starting'})
            state = worker.get('state')
            failure_count = _count(worker.get('consecutive_failures'))
            if worker.get('history_saved') is False:
                state = 'history_unavailable'
            if state in ('stopped', 'overdue', 'history_unavailable') or state == 'retry_wait' and failure_count >= 3 or state in ('starting', 'not_started') and startup_age > 30:
                common['worker:'+name] = {'category': 'worker', 'worker': name,
                                          'state': state, 'consecutive_failures': failure_count}
    result = {}
    clinics = [r[0] for r in c.execute("SELECT id FROM records WHERE kind='clinic' ORDER BY id")]
    for clinic in clinics:
        for key, details in common.items():
            result[(clinic, key)] = details
        for queue in queue_summary(c, clinic, instant):
            counts = {state: _count(queue['counts'].get(state)) for state in QUEUE_STATES[queue['name']]
                      if queue['counts'].get(state)}
            if counts:
                result[(clinic, 'queue:'+queue['name'])] = {'category': 'queue', 'queue': queue['name'], 'counts': counts}
    return result


def _event(c, incident, kind, stamp):
    event_id = db.uid()
    # No clinic, patient, job, actor, free-text reason, destination or token.
    details = json.loads(incident['details'])
    if kind == 'recovered':
        details = ({'category': 'worker', 'worker': details['worker'], 'state': 'clear'}
                   if details['category'] == 'worker' else {'category': 'queue', 'queue': details['queue'], 'counts': {}})
    payload = {'version': 1, 'scope': 'infrastructure_operations_only', 'event_id': event_id,
               'incident_id': incident['id'], 'kind': kind, 'sequence': 1 if kind == 'opened' else 2, 'occurred_at': stamp,
               'condition': details,
               'human_response_verified': False}
    c.execute('''INSERT INTO ops_alert_events
        (id,incident_id,clinic_id,kind,payload,status,retry_limit,created_at,updated_at)
        VALUES(?,?,?,?,?,'queued',?,?,?)''',
        (event_id, incident['id'], incident['clinic_id'], kind, json.dumps(payload), MAX_ATTEMPTS, stamp, stamp))


def scan(instant=None):
    """Reconcile condition transitions and outbox events atomically."""
    if configuration().mode == 'disabled':
        return
    instant = instant or datetime.now(timezone.utc)
    stamp = instant.isoformat()
    with db.connection(True) as c:
        observed = conditions(c, instant)
        opened = {(r['clinic_id'], r['condition_key']): dict(r)
                  for r in c.execute("SELECT * FROM ops_incidents WHERE state='open'")}
        for key, details in observed.items():
            serialized = json.dumps(details, sort_keys=True)
            previous = opened.get(key)
            if previous:
                changed = previous['details'] != serialized
                c.execute('UPDATE ops_incidents SET details=?,last_seen_at=?,version=version+? WHERE id=?',
                          (serialized, stamp, int(changed), previous['id']))
            else:
                incident = {'id': db.uid(), 'clinic_id': key[0], 'condition_key': key[1],
                            'state': 'open', 'version': 1, 'details': serialized,
                            'opened_at': stamp, 'last_seen_at': stamp}
                db.upsert(c, 'ops_incidents', incident, ['id'])
                _event(c, incident, 'opened', stamp)
        for key, previous in opened.items():
            if key not in observed:
                c.execute("UPDATE ops_incidents SET state='recovered',recovered_at=?,version=version+1 WHERE id=?", (stamp, previous['id']))
                # Do not keep retrying an old opening after recovery. An already
                # in-flight request may still reach its destination; receivers
                # must also order the immutable sequence numbers per incident.
                c.execute("""UPDATE ops_alert_attempts SET outcome='superseded_unconfirmed',finished_at=?
                    WHERE outcome='in_flight' AND event_id IN
                    (SELECT id FROM ops_alert_events WHERE incident_id=? AND kind='opened' AND status='sending')""", (stamp, previous['id']))
                c.execute("""UPDATE ops_alert_events SET status='superseded',lease_until=0,token=NULL,updated_at=?
                    WHERE incident_id=? AND kind='opened' AND status IN ('queued','sending','failed')""", (stamp, previous['id']))
                _event(c, previous, 'recovered', stamp)
        db.upsert(c, 'ops_alert_monitor', {'name': 'webhook', 'heartbeat_at': stamp, 'last_scan_at': stamp}, ['name'])


def claim(instant=None):
    instant = time.time() if instant is None else instant
    with db.connection(True) as c:
        # A killed last attempt must become visibly failed, not remain sending
        # forever because its retry budget was already consumed.
        expired = list(c.execute("SELECT * FROM ops_alert_events WHERE status='sending' AND lease_until<=?", (instant,)))
        for event in expired:
            c.execute("UPDATE ops_alert_attempts SET outcome='interrupted',finished_at=? WHERE event_id=? AND attempt=? AND outcome='in_flight'",
                      (db.now(), event['id'], event['attempts']))
            if event['attempts'] >= event['retry_limit']:
                c.execute("UPDATE ops_alert_events SET status='failed',last_error_code='interrupted',updated_at=? WHERE id=?", (db.now(), event['id']))
        event = c.execute("""SELECT * FROM ops_alert_events WHERE status IN ('queued','sending')
            AND lease_until<=? AND next_attempt<=? AND attempts<retry_limit
            ORDER BY created_at,id LIMIT 1""", (instant, instant)).fetchone()
        if not event:
            return None
        token = db.uid(); attempt = event['attempts']+1
        c.execute("UPDATE ops_alert_events SET status='sending',attempts=?,token=?,lease_until=?,updated_at=? WHERE id=?",
                  (attempt, token, instant+LEASE_SECONDS, db.now(), event['id']))
        c.execute('''INSERT INTO ops_alert_attempts(event_id,attempt,token,started_at,outcome)
            VALUES(?,?,?,?,'in_flight')''', (event['id'], attempt, token, db.now()))
        return {**dict(event), 'attempts': attempt, 'token': token}


def send_one(config=None):
    config = config or configuration()
    if config.mode == 'disabled':
        return False
    event = claim()
    if not event:
        return False
    status = None
    transport = None
    try:
        headers = {'Idempotency-Key': event['id'], 'Content-Type': 'application/json'}
        if config.token:
            headers['Authorization'] = 'Bearer ' + config.token
        # The standard HTTP client has no request-URL logging, proxy discovery,
        # redirect following or implicit retries. TLS uses system verification.
        address = urlsplit(config.url)
        factory = http.client.HTTPSConnection if address.scheme == 'https' else http.client.HTTPConnection
        transport = factory(address.hostname, address.port, timeout=10)
        transport.request('POST', (address.path or '/') + ('?'+address.query if address.query else ''),
                          body=event['payload'].encode(), headers=headers)
        response = transport.getresponse()
        status = response.status
        outcome = 'accepted' if 200 <= status < 300 else 'retryable_http' if status in (408, 425, 429) or status >= 500 else 'rejected_http'
    except TimeoutError:
        outcome = 'timeout'
    except (OSError, http.client.HTTPException):
        outcome = 'network_error'
    except Exception:
        outcome = 'transport_error'
    finally:
        if transport:
            transport.close()
    accepted = outcome == 'accepted'
    retry = outcome in ('retryable_http', 'timeout', 'network_error', 'transport_error') and event['attempts'] < event['retry_limit']
    instant = time.time(); stamp = db.now()
    with db.connection(True) as c:
        c.execute('''UPDATE ops_alert_attempts SET finished_at=?,outcome=?,http_status=?
            WHERE event_id=? AND attempt=? AND token=?''',
            (stamp, outcome, status, event['id'], event['attempts'], event['token']))
        # A late old response can leave its receipt but cannot replace a newer
        # claimant's authoritative event state.
        c.execute('''UPDATE ops_alert_events SET status=?,accepted_at=?,last_error_code=?,
            next_attempt=?,lease_until=0,updated_at=? WHERE id=? AND token=? AND lease_until>?''',
            ('accepted' if accepted else 'queued' if retry else 'failed', stamp if accepted else None,
             None if accepted else outcome, instant+min(900, RETRY_BASE_SECONDS*2**min(event['attempts']-1, 5)) if retry else 0,
             stamp, event['id'], event['token'], instant))
    return True


class Review(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class RetryReview(Review):
    event_id: str = Field(min_length=1, max_length=100)


def dispatch(c, action, payload, clinic, actor):
    from actions import fail
    try:
        p = (RetryReview if action == 'operations.alert.retry' else Review).model_validate(payload)
    except ValidationError:
        fail('Review the incident, its current version and an explicit reason')
    incident = c.execute('SELECT * FROM ops_incidents WHERE id=? AND clinic_id=?', (p.id, clinic)).fetchone()
    if not incident:
        fail('Operational incident not found', 404)
    if incident['version'] != p.version:
        fail('This incident changed. Refresh and review the current details.', 409)
    stamp = db.now()
    if action == 'operations.alert.acknowledge':
        if incident['acknowledged_at']:
            fail('This incident already has an acknowledgement', 409)
        c.execute('''UPDATE ops_incidents SET acknowledged_at=?,acknowledged_by=?,acknowledgement_reason=?,version=version+1 WHERE id=?''',
                  (stamp, actor, p.reason, p.id))
    else:
        event = c.execute('SELECT * FROM ops_alert_events WHERE id=? AND incident_id=? AND clinic_id=?', (p.event_id, p.id, clinic)).fetchone()
        if not event:
            fail('Operational alert event not found', 404)
        if event['status'] != 'failed':
            fail('Only a failed webhook event can be manually retried', 409)
        c.execute("UPDATE ops_alert_events SET status='queued',next_attempt=0,lease_until=0,retry_limit=attempts+?,updated_at=? WHERE id=?",
                  (MAX_ATTEMPTS, stamp, event['id']))
        c.execute('UPDATE ops_incidents SET version=version+1 WHERE id=?', (p.id,))
    c.execute('INSERT INTO ops_incident_actions VALUES(?,?,?,?,?,?,?,?)',
              (db.uid(), p.id, clinic, getattr(p, 'event_id', None), action, actor, p.reason, stamp))
    return present_incident(c, c.execute('SELECT * FROM ops_incidents WHERE id=?', (p.id,)).fetchone())


def present_incident(c, incident):
    value = {key: incident[key] for key in ('id', 'version', 'state', 'opened_at', 'last_seen_at', 'recovered_at',
                                           'acknowledged_at', 'acknowledged_by', 'acknowledgement_reason')}
    value['details'] = json.loads(incident['details'])
    value['events'] = []
    for event in c.execute('''SELECT id,kind,status,attempts,retry_limit,next_attempt,accepted_at,last_error_code,created_at
        FROM ops_alert_events WHERE incident_id=? ORDER BY created_at,id''', (incident['id'],)):
        entry = dict(event)
        entry['attempt_receipts'] = [dict(row) for row in c.execute('''SELECT attempt,started_at,finished_at,outcome,http_status
            FROM ops_alert_attempts WHERE event_id=? ORDER BY attempt DESC LIMIT 10''', (event['id'],))]
        value['events'].append(entry)
    value['review_history'] = [dict(row) for row in c.execute('''SELECT action,actor_id,reason,created_at,event_id
        FROM ops_incident_actions WHERE incident_id=? ORDER BY created_at DESC LIMIT 10''', (incident['id'],))]
    return value


def status(c, clinic):
    try:
        mode = configuration().mode
    except Exception:
        mode = 'configuration_error'
    monitor = c.execute("SELECT * FROM ops_alert_monitor WHERE name='webhook'").fetchone()
    fresh = bool(monitor and (datetime.now(timezone.utc)-datetime.fromisoformat(monitor['heartbeat_at'])).total_seconds() <= MONITOR_STALE_SECONDS)
    incidents = [present_incident(c, row) for row in c.execute('''SELECT * FROM ops_incidents WHERE clinic_id=?
        ORDER BY CASE WHEN state='open' THEN 0 ELSE 1 END,opened_at DESC LIMIT 20''', (clinic,))]
    counts = {row['state']: row['count'] for row in c.execute('SELECT state,COUNT(*) count FROM ops_incidents WHERE clinic_id=? GROUP BY state', (clinic,))}
    delivery_counts = {row['status']: row['count'] for row in c.execute('SELECT status,COUNT(*) count FROM ops_alert_events WHERE clinic_id=? GROUP BY status', (clinic,))}
    return {'mode': mode, 'monitor_state': 'disabled' if mode == 'disabled' else 'checked' if fresh else 'overdue' if monitor else 'not_started',
            'last_scan_at': monitor['last_scan_at'] if monitor else None,
            'counts': counts, 'delivery_counts': delivery_counts, 'incidents': incidents, 'incident_limit': 20,
            'needs_attention': mode != 'disabled' and (mode == 'configuration_error' or not fresh or bool(delivery_counts.get('failed')) or bool(counts.get('open'))),
            'scope': 'Operational infrastructure alerts only. Webhook acceptance, administrator acknowledgement and observed recovery are separate. This does not provide clinical emergency response or prove an on-call response.'}


def tick():
    config = configuration()
    if config.mode == 'disabled':
        return
    scan()
    for _ in range(5):
        if not send_one(config):
            break


def main():
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent/'.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Run one configured monitoring/delivery cycle')
    args = parser.parse_args()
    if configuration().mode == 'disabled':
        logging.info('Operational webhook monitoring is disabled')
        return 0
    stop = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stop.set())
    while not stop.is_set():
        try:
            tick()
        except Exception:
            logging.error('Operational alert cycle failed; inspect monitor freshness and database availability')
            if args.once:
                return 1
        if args.once or stop.wait(POLL_SECONDS):
            break
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        logging.error('Operational alert monitor could not start; inspect configuration and prepared database')
        raise SystemExit(1)
