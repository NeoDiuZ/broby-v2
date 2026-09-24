"""Operational states must not certify delivery, leak payloads or duplicate work."""
import json, threading, time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
import db, main, jobs, operations_health as health
from test_integrity import isolated, act, note, generate

ADMIN={'x-clinic-id':'clinic-east','x-actor-id':'clinic-east-admin'}

@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv('BROBY_AUTH_MODE','demo')
    monkeypatch.setenv('BROBY_ENABLE_AI','0')
    monkeypatch.setenv('BROBY_STRIPE_MODE','disabled')
    monkeypatch.setenv('BROBY_TWILIO_MODE','disabled')
    monkeypatch.setattr(main.app.state,'workers',None,raising=False)


def monitor(name='documents'):
    stop=threading.Event();stop.set();m=health.Supervisor(stop)
    m.start(name,lambda:None,.01).join(timeout=1)
    m.threads[name]=SimpleNamespace(is_alive=lambda:True)
    return m


def row(m,name='documents'):
    return next(w for w in m.snapshot() if w['name']==name)


def job(id,clinic='clinic-east',status='queued',created=None,lease='',retry='',attempts=0):
    created=created or db.now()
    with db.connection(True) as c:
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(id,clinic,'consult-luna',status,json.dumps({'secret':'PRIVATE-PAYLOAD'}),json.dumps({'private':'PRIVATE-RESULT'}),'PRIVATE-ERROR',created,created))
        c.execute('INSERT INTO job_claims VALUES(?,?,?,?,?,?)',(id,'PRIVATE-TOKEN',lease,attempts,retry,'PRIVATE-CLAIM-ERROR'))


def test_supervisor_recovers_one_failed_cycle_without_exposing_exception(caplog):
    m=monitor();calls=[]
    def broken():calls.append(1);raise RuntimeError('sk_live_PRIVATE-PATIENT')
    assert m.cycle('documents',broken,lambda:True)==1
    assert row(m)['state']=='retry_wait' and row(m)['attention']
    assert 'sk_live' not in caplog.text and 'PRIVATE-PATIENT' not in json.dumps(m.snapshot())
    with db.connection() as c:assert c.execute('SELECT failures FROM worker_history').fetchone()[0]==1
    assert m.cycle('documents',lambda:calls.append(2),lambda:True)==0
    value=row(m);assert value['state']=='idle' and not value['attention'] and value['consecutive_failures']==0
    with db.connection() as c:
        saved=c.execute('SELECT * FROM worker_history').fetchone();assert saved['last_recovery_at']>=saved['last_failure_at']
    assert calls==[1,2]


def test_failure_history_survives_new_process_state_but_does_not_certify_it():
    first=monitor();first.cycle('documents',lambda:(_ for _ in ()).throw(ValueError()),lambda:True)
    fresh=health.Supervisor(threading.Event())
    assert all(w['state']=='not_started' and w['attention'] for w in fresh.snapshot())
    second=monitor();second.cycle('documents',lambda:None,lambda:True)
    with db.connection() as c:
        r=c.execute('SELECT * FROM worker_history').fetchone();assert r['failures']==1 and r['last_recovery_at']


def test_disabled_provider_is_not_called_or_counted_as_failure():
    m=monitor('messaging');calls=[]
    assert m.cycle('messaging',lambda:calls.append(1),lambda:False)==0
    assert not calls and row(m,'messaging')['state']=='disabled' and not row(m,'messaging')['attention']
    assert row(m,'messaging')['last_success_at'] is None
    with db.connection() as c:assert c.execute('SELECT COUNT(*) FROM worker_history').fetchone()[0]==0


def test_overdue_worker_is_visible_and_never_forked(monkeypatch):
    m=monitor();m.mark('documents',state='working',_activity_at=time.monotonic()-301)
    value=row(m);assert value['state']=='overdue' and value['attention']
    assert len(m.threads)==1
    with pytest.raises(ValueError):m.start('documents',lambda:None,1)
    m.threads['documents']=SimpleNamespace(is_alive=lambda:False)
    assert row(m)['state']=='stopped'


def test_history_storage_failure_is_visible_and_exception_is_sanitized(monkeypatch,caplog):
    m=monitor()
    monkeypatch.setattr(db,'connection',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('postgresql://PRIVATE-password')))
    m.cycle('documents',lambda:(_ for _ in ()).throw(ValueError('PRIVATE-data')),lambda:True)
    assert row(m)['history_saved'] is False and row(m)['attention']
    assert 'PRIVATE' not in caplog.text


def test_bounded_backoff_interruptible_shutdown_and_no_duplicate_cycle():
    stop=threading.Event();m=health.Supervisor(stop);calls=[];done=threading.Event()
    def tick():
        calls.append(time.monotonic())
        if len(calls)==1:raise ValueError('controlled failure')
        done.set();stop.set()
    thread=m.start('documents',tick,.01)
    assert done.wait(3);thread.join(timeout=1)
    assert len(calls)==2 and calls[1]-calls[0]>=.9 and not thread.is_alive()
    assert row(m)['state']=='stopped'


def test_repeated_failures_back_off_to_a_cap_without_an_unbounded_exponent():
    delays=[]
    class Stop:
        def is_set(self):return len(delays)>=10
        def wait(self,seconds):delays.append(seconds);return len(delays)>=10
    m=health.Supervisor(Stop())
    thread=m.start('documents',lambda:(_ for _ in ()).throw(ValueError()),.4);thread.join(timeout=2)
    assert delays==[1,2,4,8,16,32,60,60,60,60]


def test_unexpected_enabled_check_failure_is_supervised():
    m=monitor('messaging')
    m.cycle('messaging',lambda:None,lambda:(_ for _ in ()).throw(RuntimeError()))
    assert row(m,'messaging')['state']=='retry_wait'


def test_queue_counts_classify_claims_retries_and_overdue_exclusively():
    instant=datetime.now(timezone.utc);old=(instant-timedelta(minutes=10)).isoformat();future=(instant+timedelta(minutes=2)).isoformat()
    job('ready',created=instant.isoformat());job('overdue',created=old)
    job('active',status='running',created=old,lease=future,retry=future)
    job('retry',created=old,retry=future);job('lost',status='running',created=old,lease=old)
    job('failed',status='failed');job('conflict',status='conflict');job('done',status='completed')
    job('foreign-failure',clinic='clinic-river',status='failed')
    with db.connection() as c:q=health.queue_summary(c,'clinic-east',instant)[0]
    assert q['counts']=={'ready':1,'overdue':2,'leased':1,'retry_wait':1,'failed':1,'conflict':1,'completed':1}
    assert {r['id'] for r in q['issues']}=={'overdue','lost','failed','conflict'}
    assert 'PRIVATE' not in json.dumps(q) and 'foreign' not in json.dumps(q)


def test_issue_list_is_bounded_but_counts_include_every_issue():
    for i in range(23):job(str(i),status='failed')
    with db.connection() as c:q=health.queue_summary(c,'clinic-east')[0]
    assert q['counts']['failed']==23 and len(q['issues'])==20


def test_payment_and_message_queues_are_clinic_scoped_and_payload_free():
    old=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    with db.connection(True) as c:
        for clinic in ('clinic-east','clinic-river'):
            c.execute('INSERT INTO stripe_tasks(id,clinic_id,kind,resource_id,status,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',('task-'+clinic,clinic,'sync','PRIVATE-resource','failed','PRIVATE-error',old,old))
            db.record(c,'whatsapp_trial',clinic,{'status':'uncertain','recipient':'PRIVATE-phone','body':'PRIVATE-body','provider_sid':'PRIVATE-sid'},'message-'+clinic)
        result=health.queue_summary(c,'clinic-east')
    assert result[1]['counts']=={'failed':1} and result[2]['counts']=={'uncertain':1}
    output=json.dumps(result);assert 'PRIVATE' not in output and 'clinic-river' not in output


@pytest.mark.parametrize('actor',['clinic-east-vet','clinic-east-nurse','clinic-river-admin'])
def test_admin_endpoint_rejects_nonadmin_and_cross_clinic_membership(actor):
    r=TestClient(main.app).get('/api/operations/health',headers={**ADMIN,'x-actor-id':actor})
    assert r.status_code in (403,404)


def test_inactive_admin_is_rejected():
    with db.connection(True) as c:
        r=db.get(c,'clinic-east-admin');db.update(c,r,{**r['data'],'active':False})
    assert TestClient(main.app).get('/api/operations/health',headers=ADMIN).status_code==403


def test_api_reports_no_monitor_instead_of_false_success():
    job('own',status='failed');job('foreign',status='failed',clinic='clinic-river')
    r=TestClient(main.app).get('/api/operations/health',headers=ADMIN)
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    value=r.json();assert value['status']=='needs_attention' and value['clinic_id']=='clinic-east'
    assert len(value['workers'])==4 and all(w['state']=='not_started' for w in value['workers'])
    assert 'PRIVATE' not in r.text and 'foreign' not in r.text
    assert 'does not verify provider delivery' in value['scope']


def test_worker_failure_is_distinct_from_failed_document(monkeypatch):
    m=monitor()
    note();j=generate()
    monkeypatch.setattr(jobs,'run_job',lambda id:(_ for _ in ()).throw(RuntimeError('before durable state')))
    m.cycle('documents',jobs.tick,lambda:True)
    assert row(m)['state']=='retry_wait'
    with db.connection() as c:assert c.execute('SELECT status FROM jobs WHERE id=?',(j['id'],)).fetchone()[0]=='queued'


def test_guarded_retry_uses_original_job_and_survives_processing():
    note();j=generate()
    with db.connection(True) as c:c.execute("UPDATE jobs SET status='failed',error='sanitized failure' WHERE id=?",(j['id'],))
    response=act('job.retry',{'id':j['id']},actor='clinic-east-admin',key='ops-retry-one')
    assert response['id']==j['id'];m=monitor();m.cycle('documents',jobs.tick,lambda:True)
    with db.connection() as c:
        counts=health.queue_summary(c,'clinic-east')[0]['counts'];assert counts=={'completed':1}
        assert c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==1
    assert act('job.retry',{'id':j['id']},actor='clinic-east-admin',key='ops-retry-one')==response


def test_saved_task_failure_does_not_kill_the_worker(monkeypatch):
    note();j=generate()
    def failed(id):
        with db.connection(True) as c:c.execute("UPDATE jobs SET status='failed',error='safe' WHERE id=?",(id,))
        raise RuntimeError('private provider details')
    monkeypatch.setattr(jobs,'run_job',failed);m=monitor();m.cycle('documents',jobs.tick,lambda:True)
    assert row(m)['state']=='idle'
    with db.connection() as c:assert health.queue_summary(c,'clinic-east')[0]['counts']=={'failed':1}


def test_lifespan_starts_four_workers_and_stops_them_without_sharing_stop_events():
    with TestClient(main.app) as client:
        first=main.app.state.workers
        response=client.get('/api/operations/health',headers=ADMIN)
        assert response.status_code==200 and len(first.threads)==4
        assert all(t.is_alive() for t in first.threads.values())
    assert first.stop.is_set() and all(not t.is_alive() for t in first.threads.values())
    with TestClient(main.app):
        second=main.app.state.workers
        assert second.stop is not first.stop and first.stop.is_set() and not second.stop.is_set()


def test_read_failure_does_not_return_empty_healthy_queues(monkeypatch):
    monkeypatch.setattr(health,'queue_summary',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('PRIVATE-db')))
    r=TestClient(main.app,raise_server_exceptions=False).get('/api/operations/health',headers=ADMIN)
    assert r.status_code==500 and 'PRIVATE-db' not in r.text
