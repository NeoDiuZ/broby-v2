"""Real process ownership and interruption recovery, using synthetic jobs only."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import db
import jobs
import main
import runtime
import worker_runtime as workers
from test_integrity import note, generate

ROOT = Path(__file__).resolve().parents[2]
ADMIN = {'x-clinic-id': 'clinic-east', 'x-actor-id': 'clinic-east-admin'}


@pytest.fixture(autouse=True)
def isolated_worker(tmp_path, monkeypatch):
    monkeypatch.setattr('spine.reader.native_records', lambda *a, **k: [])
    monkeypatch.setattr(db, 'DATA', tmp_path)
    monkeypatch.setattr(db, 'DB', tmp_path / 'broby.sqlite3')
    monkeypatch.setattr(main, 'DATA', tmp_path)
    for key, value in {'BROBY_DATA_DIR': str(tmp_path), 'BROBY_WORKER_MODE': 'external',
                      'BROBY_ENVIRONMENT': 'local', 'BROBY_AUTH_MODE': 'demo',
                      'BROBY_ENABLE_AI': '0', 'BROBY_STRIPE_MODE': 'disabled',
                      'BROBY_TWILIO_MODE': 'disabled', 'BROBY_TWILIO_SEND_ENABLED': '0'}.items():
        monkeypatch.setenv(key, value)
    for key in list(os.environ):
        if key in ('ANTHROPIC_API_KEY', 'DEEPGRAM_API_KEY', 'STRIPE_SECRET_KEY',
                   'BROBY_STRIPE_SECRET_KEY', 'TWILIO_ACCOUNT_SID', 'BROBY_ADMIN_USERNAME',
                   'BROBY_ADMIN_PASSWORD'):
            monkeypatch.delenv(key)
    db.init()
    workers.ExternalWorkers()


def wait_for(check, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Timed out waiting for synthetic worker process state')


def process(code=None):
    command = [sys.executable, '-c', code] if code else [sys.executable, 'worker.py']
    env = {**os.environ, 'PYTHONPATH': str(ROOT/'api'), 'BROBY_PROCESS_ROLE': 'worker'}
    return subprocess.Popen(command, cwd=ROOT/'api', env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_process(child):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)


def test_api_external_mode_does_not_execute_queued_work():
    note('SYNTHETIC external queue'); job = generate()
    with TestClient(main.app) as client:
        assert main.app.state.workers.threads == {}
        response = client.get('/api/operations/health', headers=ADMIN)
        assert response.json()['worker_mode'] == 'external'
        assert response.json()['status'] == 'needs_attention'
        with db.connection() as c:
            assert c.execute('SELECT status FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'queued'


def test_default_embedded_mode_and_unknown_modes(monkeypatch):
    monkeypatch.delenv('BROBY_WORKER_MODE')
    assert runtime.worker_mode() == 'embedded'
    with TestClient(main.app):
        assert len(main.app.state.workers.threads) == 4
    monkeypatch.setenv('BROBY_WORKER_MODE', 'typo')
    with pytest.raises(RuntimeError, match='embedded or external'):
        runtime.validate()


def test_external_progress_is_durable_and_stale_or_wrong_storage_is_never_healthy():
    remote = workers.ExternalWorkers()
    stop = threading.Event()
    owner = workers.WorkerRuntime(stop, 'external').start()
    try:
        wait_for(lambda: all(not v['attention'] for v in owner.snapshot()))
        owner.publish()
        assert all(not v['attention'] for v in remote.snapshot())
        with db.connection(True) as c:
            c.execute('UPDATE worker_runtime SET heartbeat_at=?',
                      ((datetime.now(timezone.utc)-timedelta(seconds=31)).isoformat(),))
        assert all(v['state'] == 'overdue' and v['attention'] for v in remote.snapshot())
        owner.publish()
        remote.storage_id = 'different-volume'
        assert all(not v['storage_matches'] and v['attention'] for v in remote.snapshot())
    finally:
        owner.close()
    remote.storage_id = owner.storage_id
    assert all(v['state'] == 'stopped' and v['attention'] for v in remote.snapshot())


def test_external_api_binds_storage_before_worker_can_consume(monkeypatch, tmp_path):
    workers.ExternalWorkers()
    other = tmp_path/'other-volume'; other.mkdir()
    monkeypatch.setattr(db, 'DATA', other)
    with pytest.raises(RuntimeError, match='storage differs'):
        workers.WorkerRuntime(threading.Event(), 'external').start()
    with pytest.raises(RuntimeError, match='storage differs'):
        workers.ExternalWorkers()


def test_external_worker_requires_api_storage_registration():
    with db.connection(True) as c:
        c.execute('DELETE FROM worker_runtime')
    with pytest.raises(RuntimeError, match='register file storage'):
        workers.WorkerRuntime(threading.Event(), 'external').start()


def test_health_probe_does_not_register_or_certify_an_absent_worker():
    with db.connection(True) as c:
        c.execute('DELETE FROM worker_runtime')
    assert all(v['attention'] for v in workers.ExternalWorkers(register=False).snapshot())
    with db.connection() as c:
        assert c.execute('SELECT COUNT(*) FROM worker_runtime').fetchone()[0] == 0


def test_postgres_ownership_rejects_a_second_volume(tmp_path):
    if db.store() != 'postgres':
        pytest.skip('PostgreSQL advisory ownership is covered by the PostgreSQL PMS matrix')
    other = tmp_path/'other-volume'; other.mkdir()
    owner = workers.Ownership(); owner.acquire()
    contender = workers.Ownership(other)
    try:
        with pytest.raises(RuntimeError, match='owns this PMS database'):
            contender.acquire()
        assert contender.file is None and contender.database is None
    finally:
        owner.close()
    contender.acquire(); contender.close()


def test_heartbeat_failure_stops_polling_and_keeps_sanitized_health(monkeypatch, caplog):
    monkeypatch.setattr(workers, 'HEARTBEAT_SECONDS', .02)
    owner = workers.WorkerRuntime(threading.Event(), 'external').start()
    monkeypatch.setattr(owner.ownership, 'check', lambda: (_ for _ in ()).throw(RuntimeError('PRIVATE-DATABASE-PASSWORD')))
    try:
        wait_for(lambda: owner.stop.is_set())
        assert owner.failure and all(v['attention'] for v in owner.snapshot())
        assert 'PRIVATE' not in caplog.text
    finally:
        owner.close()


def test_shutdown_does_not_release_ownership_while_work_is_still_running(monkeypatch):
    entered = threading.Event(); release = threading.Event()
    def blocked():
        entered.set()
        release.wait(5)
    monkeypatch.setattr(jobs, 'tick', blocked)
    monkeypatch.setattr(workers, 'HEARTBEAT_SECONDS', .02)
    owner = workers.WorkerRuntime(threading.Event(), 'external').start()
    try:
        assert entered.wait(2)
        owner.close(timeout=.01)
        contender = workers.Ownership()
        with pytest.raises(RuntimeError, match='owns this file volume'):
            contender.acquire()
    finally:
        release.set()
        owner.close()
    recovered = workers.Ownership(); recovered.acquire(); recovered.close()


def test_real_worker_process_is_unique_and_healthcheck_tracks_exit():
    remote = workers.ExternalWorkers()
    first = process(); second = None
    try:
        wait_for(lambda: all(not v['attention'] for v in remote.snapshot()))
        second = process()
        assert second.wait(timeout=5) == 1
        assert first.poll() is None
        check = subprocess.run([sys.executable, 'worker.py', '--check'], cwd=ROOT/'api',
                               env=os.environ, capture_output=True)
        assert check.returncode == 0
        stop_process(first)
        assert all(v['attention'] for v in remote.snapshot())
        check = subprocess.run([sys.executable, 'worker.py', '--check'], cwd=ROOT/'api',
                               env=os.environ, capture_output=True)
        assert check.returncode == 1
    finally:
        stop_process(first); stop_process(second)


def test_backup_refuses_a_running_external_worker_even_when_api_is_stopped(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('worker_backup_script', ROOT/'scripts/backup-local.py')
    backup = importlib.util.module_from_spec(spec); spec.loader.exec_module(backup)
    monkeypatch.setattr(socket, 'create_connection',
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError()))
    monkeypatch.setenv('BROBY_SPINE_URL', 'postgresql+psycopg://synthetic@127.0.0.1/synthetic')
    monkeypatch.setenv('BROBY_PMS_URL', 'postgresql+psycopg://synthetic@127.0.0.1/synthetic')
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/synthetic/pg_dump')
    owner = workers.Ownership(); owner.file = (db.DATA/'.worker-owner.lock').open('a+b')
    import fcntl
    fcntl.flock(owner.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(SystemExit, match='Stop all background workers'):
            backup.backup(tmp_path.parent/(tmp_path.name+'-backup'))
    finally:
        owner.close()


def test_actual_api_survives_worker_kill_and_replacement_resumes_expired_job(tmp_path):
    """SIGKILL a real claimant; lease expires naturally, with one final commit.

    Only the test lease is shortened from 90 to 3 seconds; no claim row is reset
    and no provider is called. The replacement uses the normal worker entrypoint.
    """
    source = note('SYNTHETIC preserved source after worker interruption')
    job = generate()
    with db.connection() as c:
        before = db.get(c, 'consult-luna')['version']
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    api_env = {**os.environ, 'BROBY_PROCESS_ROLE': 'api'}
    api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1',
                            '--port', str(port), '--log-level', 'error'], cwd=ROOT/'api', env=api_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = 'http://127.0.0.1:' + str(port)
    first = second = None
    def api_up():
        try:
            return httpx.get(base+'/api/health', timeout=1).status_code == 200
        except httpx.HTTPError:
            return False
    try:
        wait_for(api_up)
        with db.connection() as c:
            assert c.execute('SELECT status FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'queued'
        marker = tmp_path/'claimed'
        code = """
import pathlib, threading, jobs, worker
original_lease_time = jobs.lease_time
jobs.lease_time = lambda seconds=3: original_lease_time(seconds)
def hold(job_id, token):
    pathlib.Path(%r).write_text('claimed')
    threading.Event().wait(60)
jobs.run_claimed = hold
raise SystemExit(worker.main())
""" % str(marker)
        first = process(code)
        wait_for(marker.exists)
        with db.connection() as c:
            claim = dict(c.execute('SELECT * FROM job_claims WHERE job_id=?', (job['id'],)).fetchone())
            first_owner = c.execute('SELECT owner_id FROM worker_runtime').fetchone()[0]
        assert claim['attempts'] == 1
        first.kill(); first.wait(timeout=3)
        assert httpx.get(base+'/api/health').status_code == 200
        assert jobs.claim_job(job['id']) is None  # the live task lease still fences recovery
        second = process()
        def completed():
            with db.connection() as c:
                return c.execute('SELECT status FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'completed'
        wait_for(completed)
        with db.connection() as c:
            final = db.get(c, 'consult-luna')
            assert final['version'] == before+1
            assert final['data']['summary'][0]['source_ids'] == [source['id']]
            assert final['data']['summary'][0]['text'] == 'SYNTHETIC preserved source after worker interruption'
            recovered = dict(c.execute('SELECT * FROM job_claims WHERE job_id=?', (job['id'],)).fetchone())
            assert recovered['attempts'] == 2 and recovered['token'] != claim['token']
            assert not jobs.owns_claim(c, job['id'], claim['token'])
            assert c.execute('SELECT owner_id FROM worker_runtime').fetchone()[0] != first_owner
            assert c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 1
        assert httpx.get(base+'/api/operations/health', headers=ADMIN).json()['worker_mode'] == 'external'
        assert api.poll() is None
    finally:
        stop_process(first); stop_process(second); stop_process(api)
