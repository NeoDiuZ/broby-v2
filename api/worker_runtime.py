"""One worker owner, with durable progress visible to a separate API process.

This is a single-host runtime: every process must share the same POSIX file
volume and PMS database. It is not a distributed filesystem or replica design.
"""
import fcntl
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import db
from operations_health import LABELS, Supervisor, start_workers

HEARTBEAT_SECONDS = 5
STALE_SECONDS = 30


def storage_identity(create=True):
    """Persist an opaque identity in the volume, never a local path or secret."""
    path = db.DATA / '.worker-storage-id'
    if not create:
        value = path.read_text().strip()
        uuid.UUID(value)
        return value
    # Serialize first boot so another process never reads a partially written ID.
    with (db.DATA / '.worker-storage-init.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists():
            temporary = path.with_suffix('.tmp')
            with temporary.open('w') as output:
                output.write(str(uuid.uuid4()))
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, path)
        value = path.read_text().strip()
        uuid.UUID(value)
        return value


class Ownership:
    """Locks release on process death; expired heartbeats do not fork live work.

    A local filesystem lock prevents overlap during a lost DB connection or a
    hung provider call. PostgreSQL also holds a dedicated session advisory lock
    across processes, including accidental use of a different file volume.
    """
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or db.DATA
        self.file = None
        self.database = None

    def acquire(self):
        try:
            self.file = (self.data_dir / '.worker-owner.lock').open('a+b')
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another background worker owns this file volume') from None
            if db.store() == 'postgres':
                import psycopg
                import pms_postgres
                self.database = psycopg.connect(
                    pms_postgres.url().replace('postgresql+psycopg://', 'postgresql://', 1),
                    autocommit=True, connect_timeout=10)
                self.database.execute("SET statement_timeout='10s'")
                acquired = self.database.execute('SELECT pg_try_advisory_lock(hashtext(%s))',
                    ('broby-background-owner:' + pms_postgres.schema(),)).fetchone()[0]
                if not acquired:
                    raise RuntimeError('Another background worker owns this PMS database')
        except Exception:
            self.close()
            raise

    def check(self):
        if self.database:
            self.database.execute('SELECT 1').fetchone()

    def close(self):
        if self.database is not None:
            self.database.close()
            self.database = None
        if self.file is not None:
            self.file.close()
            self.file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.close()


class WorkerRuntime:
    def __init__(self, stop, mode):
        self.stop = stop
        self.mode = mode
        self.owner_id = str(uuid.uuid4())
        self.storage_id = storage_identity()
        self.started_at = db.now()
        self.ownership = Ownership()
        self.monitor = None
        self.failure = False
        self.keeper = None

    @property
    def threads(self):
        return self.monitor.threads if self.monitor else {}

    def start(self):
        self.ownership.acquire()
        try:
            # The API prepares schema; a standalone worker does not migrate,
            # seed clinics or provision accounts while another process serves.
            with db.connection(True) as c:
                previous = c.execute("SELECT storage_id FROM worker_runtime WHERE name='background'").fetchone()
                if self.mode == 'external' and not previous:
                    raise RuntimeError('Start the external-mode API to register file storage before its worker')
                if previous and previous['storage_id'] != self.storage_id:
                    raise RuntimeError('Worker storage differs from the registered file volume')
                db.upsert(c, 'worker_runtime', {
                    'name': 'background', 'owner_id': self.owner_id,
                    'storage_id': self.storage_id, 'mode': self.mode,
                    'started_at': self.started_at, 'heartbeat_at': db.now(),
                    'stopped_at': None, 'snapshot': '[]'}, ['name'])
            self.monitor = Supervisor(self.stop)
            start_workers(self.stop, self.monitor)
            self.publish()
            self.keeper = threading.Thread(target=self.keep, daemon=True, name='broby-worker-heartbeat')
            self.keeper.start()
            return self
        except Exception:
            self.stop.set()
            # If startup failed after a thread began, retain the lock until that
            # thread finishes; never unlock while its provider call may be live.
            if any(t.is_alive() for t in self.threads.values()):
                self.keeper = threading.Thread(target=self.keep, daemon=True, name='broby-worker-heartbeat')
                self.keeper.start()
            else:
                self.ownership.close()
            raise

    def publish(self, stopped=False):
        self.ownership.check()
        with db.connection(True) as c:
            changed = c.execute('''UPDATE worker_runtime SET heartbeat_at=?,stopped_at=?,snapshot=?
                WHERE name='background' AND owner_id=?''',
                (db.now(), db.now() if stopped else None, json.dumps(self.snapshot()), self.owner_id))
            if changed.rowcount != 1:
                raise RuntimeError('Worker ownership changed')

    def keep(self):
        try:
            while True:
                if self.stop.wait(HEARTBEAT_SECONDS):
                    # A stopped polling loop may still be inside a provider call.
                    # Keep ownership, but do not present it as ready for more work.
                    for thread in self.threads.values():
                        thread.join(timeout=.1)
                    if not any(t.is_alive() for t in self.threads.values()):
                        break
                    time.sleep(HEARTBEAT_SECONDS)
                try:
                    self.publish()
                except Exception:
                    self.failure = True
                    self.stop.set()
                    logging.warning('Background worker heartbeat failed; processing is stopping')
            try:
                self.publish(stopped=True)
            except Exception:
                self.failure = True
                logging.warning('Background worker stopped without a final persisted heartbeat')
        finally:
            self.ownership.close()

    def snapshot(self):
        values = self.monitor.snapshot()
        if self.failure or self.stop.is_set():
            for value in values:
                value['attention'] = True
        return values

    def close(self, timeout=12):
        self.stop.set()
        deadline = time.monotonic() + timeout
        for thread in self.threads.values():
            thread.join(timeout=max(0, deadline-time.monotonic()))
        if self.keeper:
            self.keeper.join(timeout=max(0, deadline-time.monotonic()))


class ExternalWorkers:
    """Read persisted worker progress without starting work in the API process."""
    def __init__(self, register=True):
        self.storage_id = storage_identity(create=register)
        self.threads = {}
        if not register:
            return
        # Bind the database to the API's actual volume before any separate
        # worker is allowed to claim tasks. A different empty worker volume
        # must not discover missing audio only after consuming a job.
        with db.connection(True) as c:
            db.upsert(c, 'worker_runtime', {
                'name': 'background', 'owner_id': '', 'storage_id': self.storage_id,
                'mode': 'external', 'started_at': db.now(), 'heartbeat_at': db.now(),
                'stopped_at': db.now(), 'snapshot': '[]'}, ['name'], ignore=True)
            row = c.execute("SELECT storage_id FROM worker_runtime WHERE name='background'").fetchone()
            if row['storage_id'] != self.storage_id:
                raise RuntimeError('API storage differs from the registered worker file volume')

    def snapshot(self):
        with db.connection() as c:
            row = c.execute("SELECT * FROM worker_runtime WHERE name='background'").fetchone()
        if not row:
            return Supervisor(threading.Event()).snapshot()
        age = max(0, (datetime.now(timezone.utc)-datetime.fromisoformat(row['heartbeat_at'])).total_seconds())
        storage_matches = row['storage_id'] == self.storage_id
        mode_matches = row['mode'] == 'external'
        mismatch = not storage_matches or not mode_matches
        values = json.loads(row['snapshot'])
        by_name = {value['name']: value for value in values}
        result = []
        for name, label in LABELS.items():
            value = by_name.get(name, {'name': name, 'label': label, 'state': 'starting', 'attention': True})
            value['process_started_at'] = row['started_at']
            value['heartbeat_at'] = row['heartbeat_at']
            value['heartbeat_age_seconds'] = round(age)
            value['storage_matches'] = storage_matches
            value['mode_matches'] = mode_matches
            if mismatch or row['stopped_at']:
                value.update(state='stopped', attention=True)
            elif age > STALE_SECONDS:
                value.update(state='overdue', attention=True)
            result.append(value)
        return result


def for_api(stop):
    import runtime
    if runtime.worker_mode() == 'external':
        return ExternalWorkers()
    return WorkerRuntime(stop, 'embedded').start()
