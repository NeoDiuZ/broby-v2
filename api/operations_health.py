"""Sanitized worker supervision and clinic-scoped operational diagnostics.

A successful cycle proves only that the worker loop ran. Provider acceptance,
delivery and settlement still require their own durable receipts.
"""
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request
import db

router = APIRouter(prefix='/api/operations')
LABELS = {'documents': 'Documents and speech', 'schedule': 'Scheduled preparation',
          'payments': 'Stripe test reconciliation', 'messaging': 'WhatsApp trial processing'}


def setup(c):
    c.execute('''CREATE TABLE IF NOT EXISTS worker_history(
        name TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
        last_failure_at TEXT, last_recovery_at TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS jobs_clinic_status ON jobs(clinic_id,status,created_at)')
    c.execute('CREATE INDEX IF NOT EXISTS stripe_tasks_clinic_status ON stripe_tasks(clinic_id,status,created_at)')


class Supervisor:
    """One bounded-backoff loop per worker. Never creates a second concurrent tick.

    Current-thread state is process-local, so a previous process's recent check
    cannot falsely certify this process. Only sanitized failure/recovery history
    is persisted. A hanging call is reported overdue and is never blindly forked.
    """
    def __init__(self, stop):
        self.stop = stop
        self.lock = threading.Lock()
        self.states = {}
        self.threads = {}

    def mark(self, name, **values):
        with self.lock:
            self.states[name].update(values)

    def history(self, name, failed):
        try:
            with db.connection(True) as c:
                c.execute('INSERT INTO worker_history(name) VALUES(?) ON CONFLICT DO NOTHING', (name,))
                if failed:
                    c.execute('UPDATE worker_history SET failures=failures+1,last_failure_at=? WHERE name=?', (db.now(), name))
                else:
                    c.execute('UPDATE worker_history SET last_recovery_at=? WHERE name=? AND last_failure_at IS NOT NULL AND (last_recovery_at IS NULL OR last_failure_at>last_recovery_at)', (db.now(), name))
            self.mark(name, history_saved=True)
        except Exception:
            self.mark(name, history_saved=False)
            logging.warning('Background worker history could not be saved: %s', name)

    def start(self, name, tick, interval, enabled=lambda: True):
        if name not in LABELS or interval <= 0:
            raise ValueError('Unknown worker or invalid interval')
        with self.lock:
            if name in self.threads:
                raise ValueError('Worker already registered')
            self.states[name] = {'name': name, 'label': LABELS[name], 'state': 'starting',
                'started_at': db.now(), 'last_started_at': None, 'last_success_at': None,
                'last_failure_at': None, 'next_check_at': None, 'failures': 0,
                'consecutive_failures': 0, 'history_saved': True, 'interval_seconds': interval,
                '_activity_at': time.monotonic()}
            thread = threading.Thread(target=self.run, args=(name, tick, interval, enabled), daemon=True, name='broby-'+name)
            self.threads[name] = thread
        thread.start()
        return thread

    def cycle(self, name, tick, enabled):
        """Return failure count for backoff; individual task failures stay in queues."""
        try:
            if not enabled():
                self.mark(name, state='disabled', _activity_at=time.monotonic())
                return 0
            self.mark(name, state='working', last_started_at=db.now(), _activity_at=time.monotonic())
            tick()
        except Exception:
            with self.lock:
                failures = self.states[name]['consecutive_failures'] + 1
                self.states[name].update(state='retry_wait', failures=self.states[name]['failures']+1,
                    consecutive_failures=failures, last_failure_at=db.now(), _activity_at=time.monotonic())
            # Do not log exception text, tracebacks, clinic records or provider URLs.
            logging.warning('Background worker cycle failed; bounded retry scheduled: %s', name)
            self.history(name, True)
            return failures
        with self.lock:
            recovering = self.states[name]['consecutive_failures'] > 0 or self.states[name]['last_success_at'] is None
        self.mark(name, state='idle', last_success_at=db.now(), consecutive_failures=0, _activity_at=time.monotonic())
        if recovering:
            self.history(name, False)
        return 0

    def run(self, name, tick, interval, enabled):
        try:
            while not self.stop.is_set():
                failures = self.cycle(name, tick, enabled)
                delay = min(60, max(1, interval)*2**min(failures-1, 6)) if failures else interval
                self.mark(name, next_check_at=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat())
                if self.stop.wait(delay):
                    break
        finally:
            self.mark(name, state='stopped', next_check_at=None)

    def snapshot(self):
        with self.lock:
            result = []
            for name, label in LABELS.items():
                value = self.states.get(name)
                if value is None:
                    result.append({'name': name, 'label': label, 'state': 'not_started', 'attention': True})
                    continue
                value = dict(value)
                elapsed = max(0, time.monotonic()-value.pop('_activity_at'))
                value['seconds_since_progress'] = round(elapsed)
                thread = self.threads.get(name)
                if not thread or not thread.is_alive():
                    value['state'] = 'stopped'
                # Long work may be legitimate; report it as needing inspection,
                # never terminate or start duplicate provider work automatically.
                elif elapsed > max(300, value['interval_seconds']*3):
                    value['state'] = 'overdue'
                value['attention'] = value['state'] in ('starting', 'retry_wait', 'overdue', 'stopped') or not value['history_saved']
                result.append(value)
            return result


def start_workers(stop):
    import jobs, clinic_workflows, stripe_payments, twilio_trial
    monitor = Supervisor(stop)
    monitor.start('documents', jobs.tick, .4)
    monitor.start('schedule', clinic_workflows.tick, 30)
    last_poll = [0.0]
    def payments():
        if time.monotonic()-last_poll[0] > 60:
            stripe_payments.poll()
            last_poll[0] = time.monotonic()
        stripe_payments.tick()
    monitor.start('payments', payments, 1, stripe_payments.configured)
    def messaging_enabled():
        from fastapi import HTTPException
        try:
            twilio_trial.config()
            return True
        except HTTPException:
            return False
    # Sending disabled can still permit receipt reconciliation when configured.
    monitor.start('messaging', twilio_trial.tick, 1, messaging_enabled)
    return monitor


def queue_summary(c, clinic, instant=None):
    instant = instant or datetime.now(timezone.utc)
    iso, cutoff = instant.isoformat(), (instant-timedelta(minutes=5)).isoformat()
    # Leases and retry waits are mutually exclusive with ready work. The clock
    # at next_attempt controls retry readiness; created_at controls queue age.
    states = '''CASE WHEN j.status NOT IN ('queued','running') THEN j.status
        WHEN q.lease_until>? THEN 'leased' WHEN q.next_attempt>? THEN 'retry_wait'
        WHEN j.created_at<=? THEN 'overdue' ELSE 'ready' END'''
    query = f'SELECT j.id,j.consultation_id,j.created_at,j.updated_at,COALESCE(q.attempts,0) attempts,q.next_attempt,{states} state FROM jobs j LEFT JOIN job_claims q ON q.job_id=j.id WHERE j.clinic_id=?'
    params = (iso, iso, cutoff, clinic)
    counts = {r['state']: r['count'] for r in c.execute('SELECT state,COUNT(*) count FROM ('+query+') GROUP BY state', params)}
    recent = [dict(r) for r in c.execute('SELECT * FROM ('+query+") WHERE state IN ('failed','conflict','overdue') ORDER BY created_at DESC,id LIMIT 20", params)]
    for row in recent:
        row['kind'] = 'document'
        row['next_attempt'] = row['next_attempt'] or None
    payment_query = '''SELECT id,kind,created_at,updated_at,attempts,CASE
        WHEN status NOT IN ('queued','running') THEN status
        WHEN lease_until>? THEN 'leased' WHEN next_attempt>? THEN 'retry_wait'
        WHEN created_at<=? THEN 'overdue' ELSE 'ready' END state
        FROM stripe_tasks WHERE clinic_id=?'''
    pp = (instant.timestamp(), instant.timestamp(), cutoff, clinic)
    payment_counts = {r['state']:r['count'] for r in c.execute('SELECT state,COUNT(*) count FROM ('+payment_query+') GROUP BY state', pp)}
    payment_issues = [dict(r) for r in c.execute('SELECT * FROM ('+payment_query+") WHERE state IN ('failed','overdue') ORDER BY created_at DESC,id LIMIT 20", pp)]
    status=db.json_text(c,'data','status')
    message_counts = {r['state']: r['count'] for r in c.execute(f"SELECT {status} state,COUNT(*) count FROM records WHERE clinic_id=? AND kind='whatsapp_trial' GROUP BY state", (clinic,))}
    message_issues = [dict(r) for r in c.execute(f"SELECT id,created_at,updated_at,{status} state FROM records WHERE clinic_id=? AND kind='whatsapp_trial' AND {status} IN ('failed','undelivered','canceled','uncertain','needs_review','blocked') ORDER BY created_at DESC,id LIMIT 20", (clinic,))]
    return [{'name':'documents','label':'Documents and speech','counts':counts,'issues':recent},
            {'name':'payments','label':'Stripe test tasks','counts':payment_counts,'issues':payment_issues},
            {'name':'messaging','label':'WhatsApp trial attempts','counts':message_counts,'issues':message_issues}]


@router.get('/health')
def health(request: Request):
    from main import identity
    from actions import owned, fail
    clinic, actor = identity(request)
    with db.connection(snapshot=True) as c:
        member = owned(c, actor, clinic, 'member')
        if not member['data'].get('active') or member['data']['role'] != 'admin':
            fail('Administrator access required', 403)
        queues = queue_summary(c, clinic)
        history = {r['name']:dict(r) for r in c.execute('SELECT * FROM worker_history')}
    monitor = getattr(request.app.state, 'workers', None)
    workers = (monitor or Supervisor(threading.Event())).snapshot()
    for worker in workers:
        worker['history'] = history.get(worker['name'], {'failures':0,'last_failure_at':None,'last_recovery_at':None})
    attention = any(w['attention'] for w in workers) or any(q['issues'] for q in queues)
    return {'checked_at': db.now(), 'clinic_id': clinic, 'status': 'needs_attention' if attention else 'checked',
            'workers': workers, 'queues': queues, 'issue_limit_per_queue': 20,
            'scope': 'Worker progress is shared by this deployment. Queue counts belong only to the selected clinic. This does not verify provider delivery, settlement, backups or physical recording devices.'}
