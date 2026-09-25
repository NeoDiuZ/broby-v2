"""Optional, explicitly configured staff escalation. Never clinical triage or advice.

The owner/clinic supplies urgency and deadlines. HTTP acceptance is not a human
acknowledgement. Payloads contain opaque references and fixed routing metadata;
questions, patient identity, clinical text and media never leave this transport.
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import re
import signal
import threading
import time
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import db
import runtime

POLL_SECONDS = 5
STALE_SECONDS = 30
LEASE_SECONDS = 30
MAX_ATTEMPTS = 6
RETRY_SECONDS = 5


@dataclass(frozen=True)
class Destination:
    url: str = field(repr=False)
    token: str = field(default='', repr=False)

    def fingerprint(self):
        return hashlib.sha256((self.url+'\0'+self.token).encode()).hexdigest()


def configuration():
    mode = os.getenv('BROBY_CLINICAL_ESCALATION_MODE', 'disabled')
    if mode == 'disabled':
        return mode, {}
    if mode not in ('webhook', 'test-loopback'):
        raise ValueError('Unsupported clinical escalation mode')
    values = json.loads(os.getenv('BROBY_CLINICAL_ESCALATION_ROUTES', '{}'))
    if not isinstance(values, dict) or not 1 <= len(values) <= 30:
        raise ValueError('Configure named clinical escalation routes')
    routes = {}
    for alias, value in values.items():
        if not re.fullmatch('[a-z][a-z0-9_-]{0,63}', alias) or not isinstance(value, dict) or set(value)-{'url', 'token'}:
            raise ValueError('Invalid clinical escalation route')
        address, token = value.get('url', ''), value.get('token', '')
        if not isinstance(address, str) or not isinstance(token, str) or any(x in address or x in token for x in ('\r', '\n')):
            raise ValueError('Invalid clinical escalation destination')
        parts = urlsplit(address)
        _ = parts.port
        if not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError('Invalid clinical escalation destination')
        if mode == 'test-loopback':
            if runtime.hosted() or parts.scheme not in ('http', 'https') or not ipaddress.ip_address(parts.hostname).is_loopback:
                raise ValueError('Synthetic escalation requires local loopback')
        elif parts.scheme != 'https':
            raise ValueError('Clinical escalation requires HTTPS')
        routes[alias] = Destination(address, token)
    return mode, routes


def setup(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS clinical_escalations(
      id TEXT PRIMARY KEY,clinic_id TEXT NOT NULL,thread_id TEXT NOT NULL,owner_turn_id TEXT NOT NULL,
      state TEXT NOT NULL,stage INTEGER NOT NULL,version INTEGER NOT NULL,policy TEXT NOT NULL,
      opened_at TEXT NOT NULL,primary_due_at TEXT NOT NULL,backup_due_at TEXT NOT NULL,
      blocked_reason TEXT,acknowledged_at TEXT,acknowledged_by TEXT,acknowledgement_reason TEXT,
      UNIQUE(clinic_id,thread_id,owner_turn_id));
    CREATE INDEX IF NOT EXISTS clinical_escalations_clinic ON clinical_escalations(clinic_id,state,opened_at);
    CREATE TABLE IF NOT EXISTS clinical_escalation_events(
      id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,clinic_id TEXT NOT NULL,stage TEXT NOT NULL,
      recipient TEXT NOT NULL,route_alias TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
      lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,token TEXT,accepted_at TEXT,last_error_code TEXT,
      created_at TEXT NOT NULL,UNIQUE(incident_id,stage,recipient));
    CREATE INDEX IF NOT EXISTS clinical_escalation_events_due ON clinical_escalation_events(status,next_attempt,lease_until);
    CREATE TABLE IF NOT EXISTS clinical_escalation_attempts(
      event_id TEXT NOT NULL,attempt INTEGER NOT NULL,token TEXT NOT NULL,started_at TEXT NOT NULL,
      finished_at TEXT,outcome TEXT NOT NULL,http_status INTEGER,PRIMARY KEY(event_id,attempt));
    CREATE TABLE IF NOT EXISTS clinical_escalation_reviews(
      id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,clinic_id TEXT NOT NULL,actor_id TEXT NOT NULL,
      action TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS clinical_escalation_monitor(name TEXT PRIMARY KEY,heartbeat_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS clinical_escalation_routes(alias TEXT PRIMARY KEY,digest TEXT NOT NULL,revision TEXT NOT NULL);
    ''')


class Policy(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', str_strip_whitespace=True)
    enabled: bool
    primary_member_id: str = Field(default='', max_length=100)
    backup_member_id: str = Field(default='', max_length=100)
    primary_route: str = Field(default='', max_length=64)
    backup_route: str = Field(default='', max_length=64)
    primary_timeout_seconds: int | None = Field(default=None, ge=1, le=604800)
    backup_timeout_seconds: int | None = Field(default=None, ge=1, le=604800)
    fallback_instructions: str = Field(default='', max_length=1000)
    recipient_authority_confirmed: bool = False


def validate_policy(c, clinic, value):
    from actions import fail
    try:
        policy = Policy.model_validate(value).model_dump()
    except ValidationError:
        fail('Review the named recipients, routes, explicit timeouts and fallback instructions')
    if not policy['enabled']:
        return {'enabled': False}
    try:
        mode, routes = configuration()
    except Exception:
        fail('Clinical notification configuration is unavailable; ask the operator to check it')
    if mode == 'disabled':
        fail('Clinical notification transport is disabled')
    if not policy['recipient_authority_confirmed'] or not policy['fallback_instructions'] or not policy['primary_timeout_seconds'] or not policy['backup_timeout_seconds']:
        fail('Explicit recipient notification authority, both timeouts and fallback instructions are required')
    if policy['primary_member_id'] == policy['backup_member_id'] or policy['primary_route'] == policy['backup_route']:
        fail('Select a distinct named primary and backup with separate configured routes')
    for stage in ('primary', 'backup'):
        member = db.get(c, policy[stage+'_member_id'], clinic)
        if not member or member['kind'] != 'member' or not member['data'].get('active') or member['data'].get('role') not in ('vet', 'nurse', 'admin'):
            fail('Select active clinic staff for both notification recipients')
        route = routes.get(policy[stage+'_route'])
        if not route:
            fail('Select an available configured destination alias')
        policy[stage+'_name'] = member['data']['name']
        # Only a random opaque revision enters the reviewed policy or records.
        # Destination digests stay in this private server registry, never any
        # staff/bootstrap response, outbox payload, receipt or diagnostic.
        registered = c.execute('SELECT digest,revision FROM clinical_escalation_routes WHERE alias=?', (policy[stage+'_route'],)).fetchone()
        revision = registered['revision'] if registered and registered['digest'] == route.fingerprint() else db.uid()
        db.upsert(c, 'clinical_escalation_routes', {'alias': policy[stage+'_route'], 'digest': route.fingerprint(), 'revision': revision}, ['alias'])
        policy[stage+'_route_revision'] = revision
    policy['enabled_at'] = db.now()
    return policy


def _incident(c, id):
    row = c.execute('SELECT * FROM clinical_escalations WHERE id=?', (id,)).fetchone()
    return dict(row) if row else None


def _event(c, incident, stage, recipient):
    policy = json.loads(incident['policy'])
    id = db.uid()
    sequence = 3 if stage == 'acknowledged' else 1 if stage == 'primary' else 2
    payload = {'version': 1, 'scope': 'clinic_staff_review_notification', 'event_id': id,
               'incident_id': incident['id'], 'stage': stage, 'sequence': sequence,
               'recipient_reference': hashlib.sha256(policy[recipient+'_member_id'].encode()).hexdigest(),
               'opened_at': incident['opened_at'], 'primary_due_at': incident['primary_due_at'],
               'backup_due_at': incident['backup_due_at'], 'clinical_response_verified': False,
               'staff_acknowledgement_recorded': stage == 'acknowledged'}
    c.execute('''INSERT INTO clinical_escalation_events
        (id,incident_id,clinic_id,stage,recipient,route_alias,payload,status,created_at)
        VALUES(?,?,?,?,?,?,?,'queued',?) ON CONFLICT(incident_id,stage,recipient) DO NOTHING''',
        (id, incident['id'], incident['clinic_id'], stage, recipient, policy[recipient+'_route'], json.dumps(payload), db.now()))


def question_policy(c, clinic):
    """Freeze explicit opt-in at owner-message creation, not later timer scans."""
    row = db.get(c, 'owner-policy:'+clinic, clinic)
    policy = row['data'].get('escalation', {}) if row else {}
    return policy if policy.get('enabled') else None


def _supersede_incident(c, id):
    c.execute("UPDATE clinical_escalations SET state='superseded',version=version+1 WHERE id=?", (id,))
    c.execute("UPDATE clinical_escalation_events SET status='superseded',token=NULL,lease_until=0 WHERE incident_id=? AND status IN ('queued','sending')", (id,))


def supersede(c, clinic, thread_id):
    """New input invalidates earlier notification work before retrieval starts."""
    old = [r[0] for r in c.execute("SELECT id FROM clinical_escalations WHERE clinic_id=? AND thread_id=? AND state IN ('awaiting_ack','manual_fallback')", (clinic, thread_id))]
    for id in old:
        _supersede_incident(c, id)


def attention(c, thread):
    """Called inside the original attention transaction, never sweeps old threads."""
    turn = db.get(c, thread['data'].get('last_owner_turn'), thread['clinic_id'])
    policy = turn['data'].get('escalation_policy') if turn else None
    if not policy or not policy.get('enabled'):
        return
    if c.execute('SELECT 1 FROM clinical_escalations WHERE clinic_id=? AND thread_id=? AND owner_turn_id=?',
                 (thread['clinic_id'], thread['id'], turn['id'])).fetchone():
        return
    # A subsequent owner turn needs its own response; it is never covered by an
    # earlier acknowledgement. Older receipts remain as superseded history.
    supersede(c, thread['clinic_id'], thread['id'])
    instant = datetime.now(timezone.utc)
    primary = instant+timedelta(seconds=policy['primary_timeout_seconds'])
    backup = primary+timedelta(seconds=policy['backup_timeout_seconds'])
    id = db.uid()
    c.execute('''INSERT INTO clinical_escalations
        (id,clinic_id,thread_id,owner_turn_id,state,stage,version,policy,opened_at,primary_due_at,backup_due_at)
        VALUES(?,?,?,?,'awaiting_ack',1,1,?,?,?,?)''',
        (id, thread['clinic_id'], thread['id'], turn['id'], json.dumps(policy), instant.isoformat(), primary.isoformat(), backup.isoformat()))
    _event(c, _incident(c, id), 'primary', 'primary')


def acknowledged(c, thread, actor, reason, action):
    for row in c.execute("SELECT * FROM clinical_escalations WHERE clinic_id=? AND thread_id=? AND owner_turn_id=? AND state IN ('awaiting_ack','manual_fallback')",
                         (thread['clinic_id'], thread['id'], thread['data'].get('last_owner_turn'))).fetchall():
        incident = dict(row)
        c.execute("UPDATE clinical_escalations SET state='acknowledged',acknowledged_at=?,acknowledged_by=?,acknowledgement_reason=?,version=version+1 WHERE id=?",
                  (db.now(), actor, reason, incident['id']))
        c.execute("UPDATE clinical_escalation_events SET status='superseded',token=NULL,lease_until=0 WHERE incident_id=? AND status IN ('queued','sending')", (incident['id'],))
        c.execute('INSERT INTO clinical_escalation_reviews VALUES(?,?,?,?,?,?,?)',
                  (db.uid(), incident['id'], thread['clinic_id'], actor, action, reason, db.now()))
        # Notify every attempted recipient so reordered/late HTTP requests can be
        # suppressed by the receiver's per-incident sequence contract.
        recipients = [r[0] for r in c.execute('SELECT DISTINCT recipient FROM clinical_escalation_events WHERE incident_id=? AND attempts>0', (incident['id'],))]
        for recipient in recipients:
            _event(c, incident, 'acknowledged', recipient)


def _blocked(c, incident, recipient, mode, routes):
    if mode == 'disabled':
        return 'transport_disabled'
    policy_row = db.get(c, 'owner-policy:'+incident['clinic_id'], incident['clinic_id'])
    if not policy_row or not policy_row['data'].get('escalation', {}).get('enabled'):
        return 'clinic_policy_disabled'
    policy = json.loads(incident['policy'])
    member = db.get(c, policy[recipient+'_member_id'], incident['clinic_id'])
    if not member or member['kind'] != 'member' or not member['data'].get('active') or member['data'].get('role') not in ('vet', 'nurse', 'admin'):
        return 'recipient_inactive'
    route = routes.get(policy[recipient+'_route'])
    if not route:
        return 'destination_removed'
    registered = c.execute('SELECT digest,revision FROM clinical_escalation_routes WHERE alias=?', (policy[recipient+'_route'],)).fetchone()
    if not registered or registered['revision'] != policy[recipient+'_route_revision'] or registered['digest'] != route.fingerprint():
        return 'destination_changed'
    return None


def scan(instant=None):
    instant = instant or datetime.now(timezone.utc)
    try:
        mode, routes = configuration()
    except Exception:
        mode, routes = 'configuration_error', {}
    with db.connection(True) as c:
        db.upsert(c, 'clinical_escalation_monitor', {'name': 'clinical', 'heartbeat_at': instant.isoformat()}, ['name'])
        for row in c.execute("SELECT * FROM clinical_escalations WHERE state IN ('awaiting_ack','manual_fallback')").fetchall():
            incident = dict(row)
            thread = db.get(c, incident['thread_id'], incident['clinic_id'])
            if not thread or thread['data'].get('last_owner_turn') != incident['owner_turn_id']:
                _supersede_incident(c, incident['id'])
                continue
            if incident['stage'] == 1 and instant >= datetime.fromisoformat(incident['primary_due_at']):
                c.execute("UPDATE clinical_escalation_events SET status='superseded',token=NULL,lease_until=0 WHERE incident_id=? AND stage='primary' AND status IN ('queued','sending')", (incident['id'],))
                _event(c, incident, 'backup', 'backup')
                incident['stage'] = 2
            state = 'manual_fallback' if instant >= datetime.fromisoformat(incident['backup_due_at']) else 'awaiting_ack'
            blocked = 'configuration_error' if mode == 'configuration_error' else _blocked(c, incident, 'backup' if incident['stage'] == 2 else 'primary', mode, routes)
            if (row['stage'], row['state'], row['blocked_reason']) != (incident['stage'], state, blocked):
                c.execute('UPDATE clinical_escalations SET stage=?,state=?,blocked_reason=?,version=version+1 WHERE id=?',
                          (incident['stage'], state, blocked, incident['id']))


def claim():
    mode, routes = configuration()
    if mode == 'disabled':
        return None
    instant, stamp = time.time(), db.now()
    with db.connection(True) as c:
        for row in c.execute("SELECT * FROM clinical_escalation_events WHERE (status='queued' AND next_attempt<=?) OR (status='sending' AND lease_until<=?) ORDER BY created_at,id", (instant, instant)).fetchall():
            event = dict(row)
            incident = _incident(c, event['incident_id'])
            thread = db.get(c, incident['thread_id'], incident['clinic_id'])
            if event['stage'] != 'acknowledged' and (not thread or thread['data'].get('last_owner_turn') != incident['owner_turn_id']):
                _supersede_incident(c, incident['id'])
                continue
            allowed = incident['state'] == 'acknowledged' if event['stage'] == 'acknowledged' else incident['state'] in ('awaiting_ack', 'manual_fallback')
            if not allowed or event['stage'] == 'primary' and instant >= datetime.fromisoformat(incident['primary_due_at']).timestamp():
                c.execute("UPDATE clinical_escalation_events SET status='superseded',token=NULL,lease_until=0 WHERE id=?", (event['id'],))
                continue
            blocked = _blocked(c, incident, event['recipient'], mode, routes)
            if blocked:
                c.execute('UPDATE clinical_escalation_events SET last_error_code=? WHERE id=?', (blocked, event['id']))
                continue
            if event['status'] == 'sending':
                c.execute("UPDATE clinical_escalation_attempts SET outcome='interrupted',finished_at=? WHERE event_id=? AND attempt=? AND finished_at IS NULL", (stamp, event['id'], event['attempts']))
            if event['attempts'] >= MAX_ATTEMPTS:
                c.execute("UPDATE clinical_escalation_events SET status='failed',last_error_code='attempt_budget_exhausted',token=NULL,lease_until=0 WHERE id=?", (event['id'],))
                continue
            token = db.uid(); attempt = event['attempts']+1
            c.execute("UPDATE clinical_escalation_events SET status='sending',attempts=?,token=?,lease_until=? WHERE id=?", (attempt, token, instant+LEASE_SECONDS, event['id']))
            c.execute('INSERT INTO clinical_escalation_attempts VALUES(?,?,?,?,NULL,?,NULL)', (event['id'], attempt, token, stamp, 'started'))
            return {**event, 'attempts': attempt, 'token': token}
    return None


def send_one():
    event = claim()
    if not event:
        return False
    # Recheck selected active membership and fixed configuration just before
    # network dispatch. A request already in flight cannot be recalled.
    mode, routes = configuration()
    with db.connection() as c:
        incident = _incident(c, event['incident_id'])
        blocked = _blocked(c, incident, event['recipient'], mode, routes)
        current = c.execute('SELECT token,status FROM clinical_escalation_events WHERE id=?', (event['id'],)).fetchone()
        if current['token'] != event['token'] or current['status'] != 'sending':
            blocked = 'superseded_before_dispatch'
    status = None; transport = None
    if blocked:
        outcome = blocked
    else:
        destination = routes[event['route_alias']]
        try:
            address = urlsplit(destination.url)
            headers = {'Content-Type': 'application/json', 'Idempotency-Key': event['id']}
            if destination.token:
                headers['Authorization'] = 'Bearer '+destination.token
            factory = http.client.HTTPSConnection if address.scheme == 'https' else http.client.HTTPConnection
            transport = factory(address.hostname, address.port, timeout=10)
            transport.request('POST', (address.path or '/')+('?'+address.query if address.query else ''), body=event['payload'].encode(), headers=headers)
            status = transport.getresponse().status
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
    retry = outcome in ('retryable_http', 'timeout', 'network_error', 'transport_error') and event['attempts'] < MAX_ATTEMPTS
    with db.connection(True) as c:
        stamp = db.now(); instant = time.time()
        c.execute('UPDATE clinical_escalation_attempts SET finished_at=?,outcome=?,http_status=? WHERE event_id=? AND attempt=? AND token=?',
                  (stamp, outcome, status, event['id'], event['attempts'], event['token']))
        c.execute('''UPDATE clinical_escalation_events SET status=?,accepted_at=?,last_error_code=?,next_attempt=?,lease_until=0
          WHERE id=? AND token=? AND lease_until>?''',
          ('accepted' if outcome == 'accepted' else 'queued' if retry else 'failed', stamp if outcome == 'accepted' else None,
           None if outcome == 'accepted' else outcome, instant+RETRY_SECONDS*2**(event['attempts']-1) if retry else 0,
           event['id'], event['token'], instant))
    return True


def status(c, clinic):
    from clinical_reconciliation import eligibility
    clinical = eligibility(c, clinic)
    try:
        mode, routes = configuration()
    except Exception:
        mode, routes = 'configuration_error', {}
    heartbeat = c.execute("SELECT heartbeat_at FROM clinical_escalation_monitor WHERE name='clinical'").fetchone()
    fresh = heartbeat and (datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat[0])).total_seconds() <= STALE_SECONDS
    incidents = []
    counts = {r['state']: r['count'] for r in c.execute('SELECT state,COUNT(*) count FROM clinical_escalations WHERE clinic_id=? GROUP BY state', (clinic,))}
    for row in c.execute("SELECT * FROM clinical_escalations WHERE clinic_id=? ORDER BY CASE WHEN state IN ('awaiting_ack','manual_fallback') THEN 0 ELSE 1 END,opened_at DESC LIMIT 30", (clinic,)):
        incident = dict(row); incident['policy'] = json.loads(incident['policy'])
        incident['policy'] = {k: v for k, v in incident['policy'].items() if not k.endswith('_route_revision')}
        thread = db.get(c, incident['thread_id'], clinic)
        held = not thread or thread['data'].get('patient_id') in clinical['patients'] or thread['id'] in clinical['excluded']
        incident['clinical_reconciliation'] = {'status': 'historical_administrative_only', 'current_clinical_use': False,
            'notice': 'Patient identity or provenance is under review. Notification deadlines and staff follow-up remain active. Preserved policy and review wording is historical administrative evidence, not verified current clinical guidance.'} if held else None
        # A stopped dispatcher must not hide an elapsed acknowledgement deadline.
        incident['persisted_state'] = incident['state']
        if incident['state'] == 'awaiting_ack' and datetime.now(timezone.utc) >= datetime.fromisoformat(incident['backup_due_at']):
            incident['state'] = 'manual_fallback'
        incident['events'] = []
        for event in c.execute('SELECT id,stage,recipient,route_alias,status,attempts,accepted_at,last_error_code FROM clinical_escalation_events WHERE incident_id=? ORDER BY created_at,id', (incident['id'],)):
            value = dict(event)
            value['receipts'] = [dict(r) for r in c.execute('SELECT attempt,started_at,finished_at,outcome,http_status FROM clinical_escalation_attempts WHERE event_id=? ORDER BY attempt', (event['id'],))]
            incident['events'].append(value)
        incident['reviews'] = [dict(r) for r in c.execute('SELECT actor_id,action,reason,created_at FROM clinical_escalation_reviews WHERE incident_id=? ORDER BY created_at', (incident['id'],))]
        incidents.append(incident)
    return {'mode': mode, 'routes': sorted(routes), 'monitor_state': 'disabled' if mode == 'disabled' else 'fresh' if fresh else 'overdue' if heartbeat else 'not_started',
            'heartbeat_at': heartbeat[0] if heartbeat else None, 'incidents': incidents,
            'counts': counts, 'unresolved_count': counts.get('awaiting_ack', 0)+counts.get('manual_fallback', 0),
            'incident_limit': 30, 'truncated': sum(counts.values()) > len(incidents),
            'notice': 'Receiver acceptance is not staff acknowledgement or clinical response. Review the conversation and record follow-up. This service cannot assess symptoms or promise emergency monitoring.'}


def tick():
    scan()
    for _ in range(5):
        if not send_one():
            break


def main():
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent/'.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if configuration()[0] == 'disabled':
        logging.info('Clinical escalation transport is disabled')
        return 0
    stop = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stop.set())
    while not stop.is_set():
        try:
            tick()
        except Exception:
            logging.error('Clinical escalation cycle failed; check configuration, database and supervisor freshness')
            if args.once:
                return 1
        if args.once or stop.wait(POLL_SECONDS):
            break
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        logging.error('Clinical escalation could not start; inspect configuration and prepared database')
        raise SystemExit(1)
