"""PMS transaction and concurrency contracts against real PostgreSQL."""
import os,uuid
import threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from sqlalchemy import create_engine
import db,actions,main
from pms_postgres import parameters,pool,url,schema,Row,Connection


@pytest.fixture
def postgres_target(tmp_path,monkeypatch):
    connection_url=os.getenv('BROBY_TEST_SPINE_URL') or os.getenv('BROBY_SPINE_URL')
    assert connection_url,'Local PostgreSQL test URL is required'
    name='pms_test_'+uuid.uuid4().hex
    monkeypatch.setenv('BROBY_PMS_URL',connection_url)
    monkeypatch.setenv('BROBY_PMS_SCHEMA',name)
    monkeypatch.setenv('BROBY_PMS_STORE','postgres')
    monkeypatch.setattr(db,'DB',tmp_path/'broby.sqlite3')
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr('spine.reader.native_records',lambda *a,**k:[])
    try:yield
    finally:
        pool(url(),schema()).dispose()
        with create_engine(connection_url).begin() as c:c.exec_driver_sql('DROP SCHEMA IF EXISTS '+name+' CASCADE')


@pytest.fixture
def postgres_store(postgres_target):
    db.init()
    from spine.projection import setup_queue
    setup_queue()


def test_parameter_values_and_literals_are_never_sql_rewritten():
    assert parameters("SELECT '?', ?, 'what''s?', 5 % 2, \"?\"")=="SELECT '?', %s, 'what''s?', 5 %% 2, \"?\""
    assert dict(Row({'a':1,'b':2}))=={'a':1,'b':2}
    assert dict([Row({'kind':'patient','count':2})])=={'patient':2}


def test_postgres_seed_schema_history_and_rollback(postgres_store):
    assert not db.DB.exists()
    with db.connection(True) as c:
        luna=db.get(c,'luna');original=luna
        changed=db.update(c,luna,{**luna['data'],'weight':5.2})
        assert changed['version']==luna['version']+1
        old=c.execute('SELECT * FROM record_versions WHERE record_id=? AND version=?',('luna',original['version'])).fetchone()
        assert old[0]==old['record_id']=='luna' and old['data']==__import__('json').dumps(original['data'])
        assert c.execute('SELECT COUNT(*) FROM spine_changes').fetchone()[0]>0
    with pytest.raises(RuntimeError):
        with db.connection(True) as c:
            db.update(c,db.get(c,'luna'),{**original['data'],'name':'Should roll back'})
            db.transaction_file(c,db.DATA/'rollback.txt',b'SYNTHETIC')
            raise RuntimeError('Synthetic interruption')
    assert not (db.DATA/'rollback.txt').exists()
    with db.connection() as c:assert db.get(c,'luna')['data']['weight']==5.2
    db.init()
    with db.connection() as c:assert db.get(c,'luna')['data']['weight']==5.2


def test_unrelated_postgres_writes_do_not_rebuild_clinical_projection(postgres_store):
    with db.connection(True) as c:
        before=c.execute("SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id='clinic-east'").fetchone()[0]
        dashboard=db.record(c,'dashboard','clinic-east',{'name':'Synthetic display only'})
        assert c.execute("SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id='clinic-east'").fetchone()[0]==before
        db.update(c,dashboard,{'name':'Synthetic display revised'})
        assert c.execute("SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id='clinic-east'").fetchone()[0]==before
        owner=db.get(c,'owner-milo')
        db.update(c,owner,{**owner['data'],'name':'SYNTHETIC changed owner'})
        assert c.execute("SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id='clinic-east'").fetchone()[0]>before
        changed=c.execute("SELECT record_id,kind FROM spine_changes WHERE clinic_id='clinic-east' ORDER BY sequence DESC LIMIT 1").fetchone()
        assert changed['record_id']=='owner-milo' and changed['kind']=='owner'


def test_postgres_shared_action_concurrent_retry_charges_once(postgres_store):
    with db.connection() as c:invoice=db.all_records(c,'clinic-east','invoice')[0]
    def run(_):
        return actions.execute('payment.record',{'id':invoice['id'],'version':invoice['version'],'amount_cents':100,'method':'cash'},'clinic-east','clinic-east-vet','concurrent-once')
    with ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(run,range(4)))
    assert len({r['id'] for r in results})==1
    with db.connection() as c:
        assert len(db.all_records(c,'clinic-east','payment'))==1
        assert db.get(c,invoice['id'])['data']['paid_cents']==100


def test_postgres_json_and_double_precision_claims(postgres_store):
    with db.connection(True) as c:
        db.record(c,'organization_adoption','clinic-east',{'consent':{'organization_id':'org-1'}},'nested-record')
        row=c.execute('SELECT id FROM records WHERE '+db.json_text(c,'data','consent','organization_id')+'=?',('org-1',)).fetchone()
        assert row['id']=='nested-record'
        c.execute('INSERT INTO twilio_attempts(id,lease_until) VALUES(?,?)',('precision',1789999999.123456))
        assert c.execute('SELECT lease_until FROM twilio_attempts WHERE id=?',('precision',)).fetchone()[0]==1789999999.123456
        assert 'scope' in db.columns(c,'transfer_requests')
        assert c.execute("SELECT ? AS safely_bound",("'; DROP TABLE records; -- ? %",)).fetchone()[0]=="'; DROP TABLE records; -- ? %"


@pytest.mark.parametrize('write,snapshot,expected', [(False,False,'read committed'), (False,True,'repeatable read'), (True,False,'read committed'), (True,True,'read committed')])
def test_postgres_transaction_isolation_without_duplicate_begin_notice(postgres_store,write,snapshot,expected):
    connection=Connection();notices=[]
    connection.raw.add_notice_handler(lambda diagnostic:notices.append(diagnostic.message_primary))
    try:
        connection.begin(write,snapshot=snapshot)
        assert connection.execute('SHOW transaction_isolation').fetchone()[0]==expected
        assert connection.execute('SHOW lock_timeout').fetchone()[0]=='20s'
        assert connection.execute('SHOW statement_timeout').fetchone()[0]=='1min'
        assert connection.in_transaction
        assert not notices
        connection.rollback()
        assert not connection.in_transaction
        connection.begin(False)
        assert connection.execute('SHOW transaction_isolation').fetchone()[0]=='read committed'
        assert not notices
    finally:connection.close()


def test_postgres_serial_writer_waits_and_reads_the_first_committed_edit(postgres_store):
    waiting=Connection();started=threading.Event();finished=threading.Event()
    pid=waiting.raw.info.backend_pid
    def next_writer():
        started.set()
        try:
            waiting.begin(True)
            current=db.get(waiting,'luna')
            assert current['data']['name']=='SYNTHETIC first writer'
            changed=db.update(waiting,current,{**current['data'],'name':'SYNTHETIC second writer'})
            waiting.commit();return changed
        finally:waiting.close();finished.set()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with db.connection(True) as first:
            old=db.get(first,'luna');db.update(first,old,{**old['data'],'name':'SYNTHETIC first writer'})
            future=executor.submit(next_writer);assert started.wait(5)
            deadline=time.monotonic()+5;blocked=False
            while time.monotonic()<deadline:
                blocked=bool(first.execute("SELECT 1 FROM pg_locks WHERE pid=? AND locktype='advisory' AND NOT granted",(pid,)).fetchone())
                if blocked:break
                time.sleep(.01)
            assert blocked and not finished.is_set()
        result=future.result(timeout=5)
    assert result['version']==old['version']+2
    with db.connection() as c:assert db.get(c,'luna')['data']['name']=='SYNTHETIC second writer'
