"""Whole-store cutover, interrupted-copy recovery and explicit fallback guards."""
import json,sqlite3,uuid
import pytest
import db,auth,pms_migrate
from test_pms_postgres import postgres_target


@pytest.fixture
def legacy(postgres_target,monkeypatch):
    monkeypatch.setenv('BROBY_PMS_STORE','sqlite')
    monkeypatch.setenv('BROBY_AUTH_MODE','password')
    db.init()
    from spine.projection import setup_queue
    setup_queue()
    auth.provision('migration-admin','clinic-east-admin','clinic-east','Synthetic-migration-password')
    token=auth.login('migration-admin','Synthetic-migration-password','synthetic-test')
    with db.connection(True) as c:
        row=db.get(c,'luna');db.update(c,row,{**row['data'],'name':'SYNTHETIC preserved patient'})
        c.execute('INSERT INTO job_claims VALUES(?,?,?,?,?,?)',('claim','token','2098-01-01',2,'','held'))
        c.execute('INSERT INTO twilio_attempts(id,lease_until,next_poll) VALUES(?,?,?)',('trial-held',1789999999.123456,1789999999.987654))
        db.record(c,'whatsapp_trial','clinic-east',{'status':'uncertain','patient_id':'luna'},'held-send')
        c.execute('INSERT INTO grants VALUES(?,?,?,?,?)',('SYNTHETIC-private-grant','clinic-east','luna','2098-01-01',0))
        for grant in ('SYNTHETIC-A','SYNTHETIC-a','SYNTHETIC-B','SYNTHETIC-b','SYNTHETIC-_'):
            c.execute('INSERT INTO grants VALUES(?,?,?,?,?)',(grant,'clinic-east','luna','2098-01-01',1))
    original=sqlite3.connect(db.DB);original.row_factory=sqlite3.Row
    tables=pms_migrate.source_tables(original)
    fingerprints={t:pms_migrate.fingerprint(original,t,d['columns'],d['keys']) for t,d in tables.items()}
    original.close()
    monkeypatch.setenv('BROBY_PMS_STORE','postgres')
    monkeypatch.setenv('BROBY_PMS_MIGRATE','1')
    return {'token':token,'tables':tables,'fingerprints':fingerprints}


def test_fingerprint_is_independent_of_database_collation_but_preserves_every_value():
    class Rows:
        def __init__(self,rows):self.rows=rows
        def execute(self,query):return iter(self.rows)
    binary=[('A','clinic',0),('B','clinic',1),('_','clinic',0),('a','clinic',0)]
    locale=[('_','clinic',0),('a','clinic',0),('A','clinic',0),('B','clinic',1)]
    def digest(rows):return pms_migrate.fingerprint(Rows(rows),'grants',['token','clinic_id','revoked'],['token'])
    assert digest(binary)==digest(locale)
    assert digest(binary)!=digest([*binary[:-1],('a','clinic',1)])
    assert digest(binary)!=digest(binary+[binary[0]])
    assert digest(binary)!=digest(binary[:-1])


def test_cutover_preserves_every_table_auth_claims_history_and_original_file(legacy):
    db.init(seed=False)
    with db.connection() as c:
        manifest=json.loads(c.execute('SELECT manifest FROM pms_migration').fetchone()[0])
        for table,info in legacy['tables'].items():
            assert pms_migrate.fingerprint(c,table,info['columns'],info['keys'])==legacy['fingerprints'][table]
        assert c.execute('SELECT username FROM sessions WHERE token_hash=?',(auth.digest(legacy['token']),)).fetchone()[0]=='migration-admin'
        assert c.execute('SELECT lease_until FROM twilio_attempts WHERE id=?',('trial-held',)).fetchone()[0]==1789999999.123456
        assert db.get(c,'held-send')['data']['status']=='uncertain'
        assert manifest['tables']==legacy['fingerprints']
    backup=db.DATA/manifest['backup'];assert backup.exists() and backup.stat().st_mode&0o777==0o600
    with sqlite3.connect(backup) as source:
        for table,info in legacy['tables'].items():assert pms_migrate.fingerprint(source,table,info['columns'],info['keys'])==legacy['fingerprints'][table]
    assert db.DB.exists()
    with db.connection(True) as c:db.record(c,'source','clinic-east',{'text':'After cutover'},'new-pg-write')
    db.init(seed=False)
    with db.connection() as c:assert db.get(c,'new-pg-write')
    with sqlite3.connect(db.DB) as source:assert source.execute("SELECT 1 FROM records WHERE id='new-pg-write'").fetchone() is None


def test_existing_sqlite_requires_explicit_cutover_flag(legacy,monkeypatch):
    monkeypatch.delenv('BROBY_PMS_MIGRATE')
    with pytest.raises(RuntimeError,match='explicit BROBY_PMS_MIGRATE'):db.init(seed=False)
    assert not db.DB.with_suffix('.cutover.json').exists()


def test_copy_failure_rolls_back_and_retry_preserves_one_complete_copy(legacy,monkeypatch):
    original=pms_migrate.fingerprint
    def fail(c,table,*args):
        if getattr(c,'dialect',None)=='postgres' and table=='records':raise RuntimeError('Injected verification failure')
        return original(c,table,*args)
    monkeypatch.setattr(pms_migrate,'fingerprint',fail)
    with pytest.raises(RuntimeError,match='Injected verification failure'):db.init(seed=False)
    with db.connection() as c:
        assert c.execute('SELECT COUNT(*) FROM records').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM pms_migration').fetchone()[0]==0
    assert json.loads(db.DB.with_suffix('.cutover.json').read_text())['state']=='in_progress'
    override=db.store_override.set('sqlite')
    try:
        with pytest.raises(RuntimeError,match='fallback is disabled'):
            with db.connection():pass
    finally:db.store_override.reset(override)
    monkeypatch.setattr(pms_migrate,'fingerprint',original)
    db.init(seed=False)
    with db.connection() as c:
        assert original(c,'records',legacy['tables']['records']['columns'],['id'])==legacy['fingerprints']['records']


def test_completed_cutover_cannot_fall_back_or_attach_to_empty_target(legacy,monkeypatch):
    db.init(seed=False)
    monkeypatch.setenv('BROBY_PMS_STORE','sqlite')
    with pytest.raises(RuntimeError,match='fallback is disabled'):db.init(seed=False)
    monkeypatch.setenv('BROBY_PMS_STORE','postgres')
    with db.connection(True) as c:c.execute('DELETE FROM pms_migration')
    with pytest.raises(RuntimeError,match='completed cutover fence'):db.init(seed=False)


def test_unknown_source_table_is_rejected_before_fencing(legacy):
    with sqlite3.connect(db.DB) as c:c.execute('CREATE TABLE unexpected(id TEXT PRIMARY KEY,secret TEXT)')
    with pytest.raises(RuntimeError,match='unmapped tables'):db.init(seed=False)
    assert not db.DB.with_suffix('.cutover.json').exists()


def test_changed_source_after_failed_copy_cannot_replace_backup(legacy,monkeypatch):
    original=pms_migrate.fingerprint
    def fail(c,table,*args):
        if getattr(c,'dialect',None)=='postgres':raise RuntimeError('Injected copy fault')
        return original(c,table,*args)
    monkeypatch.setattr(pms_migrate,'fingerprint',fail)
    with pytest.raises(RuntimeError,match='Injected copy fault'):db.init(seed=False)
    # Obsolete writers are blocked by SQLite itself, not just the new app flag.
    with sqlite3.connect(db.DB) as c:
        with pytest.raises(sqlite3.DatabaseError,match='legacy writes disabled'):
            c.execute("UPDATE records SET version=version+1 WHERE id='luna'")
        # A deliberate operator schema override must still fail backup validation.
        c.execute('DROP TRIGGER pms_frozen_job_claims_update')
        c.execute("UPDATE job_claims SET attempts=99 WHERE job_id='claim'")
    monkeypatch.setattr(pms_migrate,'fingerprint',original)
    with pytest.raises(RuntimeError,match='changed after its cutover backup'):db.init(seed=False)


def test_obsolete_open_writer_is_fenced_after_successful_cutover(legacy):
    old=sqlite3.connect(db.DB)
    try:
        db.init(seed=False)
        with pytest.raises(sqlite3.DatabaseError,match='legacy writes disabled'):
            old.execute("DELETE FROM sessions")
    finally:old.close()


def test_projection_sequence_continues_after_migrated_high_watermark(legacy):
    db.init(seed=False)
    with db.connection(True) as c:
        previous=c.execute('SELECT MAX(sequence) FROM spine_changes').fetchone()[0]
        db.record(c,'owner','clinic-east',{'name':'SYNTHETIC after promotion'})
        assert c.execute('SELECT MAX(sequence) FROM spine_changes').fetchone()[0]>previous


def test_crash_after_database_commit_recovers_only_the_matching_fence(legacy):
    db.init(seed=False);path=db.DB.with_suffix('.cutover.json');guard=json.loads(path.read_text())
    path.write_text(json.dumps({**guard,'state':'in_progress'}));db.init(seed=False)
    assert json.loads(path.read_text())['state']=='complete'
    path.write_text(json.dumps({**guard,'migration_id':str(uuid.uuid4())}))
    with pytest.raises(RuntimeError,match='does not match'):db.init(seed=False)
