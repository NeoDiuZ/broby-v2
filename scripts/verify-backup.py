#!/usr/bin/env python3
"""Restore v1/v2/v3 backups into a disposable local database, verify, then remove it.

No source database, file paths or active application settings are modified.
Restored files are retained for inspection, but are not an activated deployment.
"""
import argparse,json,os,shutil,sqlite3,subprocess,sys,uuid
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from backup_verification import database_inventory,file_inventory,sha256,binary_receipts


def verify(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    if target.exists():raise ValueError('Choose a new destination path; existing files are never overwritten')
    if target==source or source in target.parents:raise ValueError('Restore outside the backup source')
    manifest=json.loads((source/'manifest.json').read_text())
    fmt=manifest.get('format')
    if fmt not in (1,2,3) or (source/'INCOMPLETE').exists():raise ValueError('Backup is unsupported or incomplete')
    data_name='legacy-data' if fmt==1 else 'data'
    if fmt in (2,3) and (manifest.get('postgresql')!='spine.dump' or manifest.get('data')!='data'):
        raise ValueError('Unsupported backup paths')
    if (source/'spine.dump').is_symlink() or (source/data_name).is_symlink():raise ValueError('Backup must not contain symbolic links')
    original_files=file_inventory(source/data_name)
    if fmt==3:
        if not isinstance(manifest.get('tables'),dict) or not manifest['tables']:raise ValueError('Backup table receipts are missing')
        if sha256(source/'spine.dump')!=manifest.get('postgres_sha256') or original_files!=manifest.get('files'):
            raise ValueError('Backup bytes do not match the manifest; nothing was restored')
    load_dotenv(ROOT/'.env');url=make_url(os.environ['BROBY_SPINE_URL'])
    if url.host not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Verification requires a local disposable PostgreSQL target, not a hosted database')
    database='broby_restore_'+uuid.uuid4().hex
    admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT');created=False;restored=None
    try:
        with admin.connect() as c:c.execute(text('CREATE DATABASE '+database));created=True
        target.mkdir(parents=True,mode=0o700);shutil.copytree(source/data_name,target/data_name)
        binary=ROOT/'.local/postgres/bin/pg_restore'
        executable=str(binary) if binary.exists() else shutil.which('pg_restore')
        if not executable:raise ValueError('pg_restore is required')
        subprocess.run([executable,'-h',url.host,'-p',str(url.port or 5432),'-U',url.username or '', '-d',database,'--exit-on-error',str(source/'spine.dump')],env={**os.environ,'PGPASSWORD':url.password or ''},check=True,capture_output=True)
        restored=create_engine(url.set(database=database))
        with restored.connect() as c:
            c.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            inventory=database_inventory(c)
            if fmt==3 and inventory!=manifest['tables']:raise ValueError('Restored table values or counts differ from the original database snapshot')
            if manifest.get('pms_store','sqlite')=='postgres':
                schema=manifest.get('pms_schema','broby_pms')
                if schema+'.records' not in inventory:raise ValueError('PMS records are missing from the restored database')
                qualified=c.dialect.identifier_preparer.quote(schema)
                rows=c.exec_driver_sql("SELECT id,data FROM "+qualified+".records WHERE kind='attachment'").all()
                chunks=c.exec_driver_sql('SELECT recording_id,chunk_index,sha256 FROM '+qualified+'.chunks').all()
                checked=binary_receipts(rows,chunks,target/data_name)
            else:
                with sqlite3.connect('file:'+str(target/data_name/'broby.sqlite3')+'?mode=ro',uri=True) as legacy:
                    if legacy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite backup integrity failed')
                    checked=binary_receipts(legacy.execute("SELECT id,data FROM records WHERE kind='attachment'").fetchall(),legacy.execute('SELECT recording_id,chunk_index,sha256 FROM chunks').fetchall(),target/data_name)
        if file_inventory(target/data_name)!=original_files:raise ValueError('Restored files differ from backup bytes')
        result={'restored':True,'format':fmt,'tables_verified':len(inventory),'rows_verified':sum(v['rows'] for v in inventory.values()),
                'exact_snapshot_values_verified':fmt==3,'files_verified':len(original_files),'verified_binary_receipts':checked,
                'scope':'Isolated local restore; deployment activation and cloud recovery are not implied.'}
    except Exception:
        if target.exists():(target/'INCOMPLETE').write_text('Restore verification failed; do not activate these files.')
        raise
    finally:
        if restored:restored.dispose()
        if created:
            with admin.connect() as c:c.execute(text('DROP DATABASE '+database+' WITH (FORCE)'))
        admin.dispose()
    result['isolated_database_removed']=True
    output=target/'verification.json';output.write_text(json.dumps(result,indent=2));output.chmod(0o600)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('backup',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
    print(json.dumps(verify(a.backup,a.destination)))
