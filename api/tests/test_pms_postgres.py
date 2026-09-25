"""PMS transaction and concurrency contracts against real PostgreSQL."""
import os,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from sqlalchemy import create_engine
import db,actions,main
from pms_postgres import parameters,pool,url,schema,Row


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
