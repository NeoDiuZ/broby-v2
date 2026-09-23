#!/usr/bin/env python3
"""Restore a coordinated local backup into a disposable database and directory.

Never touches the running workspace or overwrites an existing destination.
"""
import argparse,json,os,shutil,sqlite3,subprocess,uuid,hashlib
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('backup',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
source=a.backup.resolve();target=a.destination.resolve()
if target.exists():raise SystemExit('Choose a new, empty destination path')
manifest=json.loads((source/'manifest.json').read_text())
if manifest.get('format')!=1 or (source/'INCOMPLETE').exists():raise SystemExit('Backup is unsupported or incomplete')
load_dotenv(ROOT/'.env');url=make_url(os.environ['BROBY_SPINE_URL']);database='broby_restore_'+uuid.uuid4().hex
admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT');created=False
try:
    with admin.connect() as c:c.execute(text('CREATE DATABASE '+database));created=True
    target.mkdir(parents=True,mode=0o700);shutil.copytree(source/'legacy-data',target/'legacy-data')
    binary=ROOT/'.local/postgres/bin/pg_restore'
    subprocess.run([str(binary),'-h',url.host or '127.0.0.1','-p',str(url.port or 5432),'-U',url.username or '', '-d',database,'--exit-on-error',str(source/'spine.dump')],env={**os.environ,'PGPASSWORD':url.password or ''},check=True,capture_output=True)
    restored=create_engine(url.set(database=database));counts={}
    with restored.connect() as c:
        for table in ('patients','owners','events','observations','sources'):counts[table]=c.execute(text('SELECT count(*) FROM '+table)).scalar_one()
        counts['revision']=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
    restored.dispose()
    dbpath=target/'legacy-data'/'broby.sqlite3';checked=0
    with sqlite3.connect(dbpath) as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        for id,raw in c.execute("SELECT id,data FROM records WHERE kind='attachment'").fetchall():
            data=json.loads(raw);path=target/'legacy-data'/'files'/id
            assert hashlib.sha256(path.read_bytes()).hexdigest()==data['sha256']
            data['path']=str(path);c.execute('UPDATE records SET data=? WHERE id=?',(json.dumps(data),id));checked+=1
        for rid,index,sha in c.execute('SELECT recording_id,chunk_index,sha256 FROM chunks').fetchall():
            path=target/'legacy-data'/'audio'/rid/str(index)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
            c.execute('UPDATE chunks SET path=? WHERE recording_id=? AND chunk_index=?',(str(path),rid,index));checked+=1
        legacy_count=c.execute('SELECT count(*) FROM records').fetchone()[0]
    with sqlite3.connect('file:'+str(source/'legacy-data'/'broby.sqlite3')+'?mode=ro',uri=True) as c:assert c.execute('SELECT count(*) FROM records').fetchone()[0]==legacy_count
    result={'restored':True,'postgres':counts,'legacy_records':legacy_count,'verified_binary_files':checked,'isolated_database_removed':True}
    (target/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
finally:
    if created:
        with admin.connect() as c:c.execute(text('DROP DATABASE '+database+' WITH (FORCE)'))
    admin.dispose()
