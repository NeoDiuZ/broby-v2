"""Offline whole-workspace backup. Stops on a live API; never overwrites a folder."""
from pathlib import Path
import os,sys,subprocess,shutil,urllib.request,json
from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine, text
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from backup_verification import database_inventory, file_inventory, sha256
def backup(destination):
    load_dotenv(ROOT/'.env')
    # A separate local acceptance API must not stop an unrelated developer API.
    api_url=os.getenv('BROBY_BACKUP_API_URL','http://127.0.0.1:8100/api/health')
    from urllib.parse import urlsplit
    address=urlsplit(api_url)
    if address.hostname not in ('localhost','127.0.0.1','::1') or address.scheme not in ('http','https'):
        raise SystemExit('This stopped-workspace backup supports a local API only.')
    import socket
    try:
        with socket.create_connection((address.hostname,address.port or (443 if address.scheme=='https' else 80)),timeout=1):pass
    except ConnectionRefusedError:pass
    except OSError:raise SystemExit('Cannot verify that the local API is stopped; inspect it before backing up.')
    else:raise SystemExit('Stop the API before making a coordinated backup, then run this command again.')
    target=Path(destination).resolve()
    if target.exists():raise SystemExit('Choose a new destination directory; existing data is never overwritten.')
    source=Path(os.getenv('BROBY_DATA_DIR',ROOT/'api/data')).resolve()
    if target==source or source in target.parents:raise SystemExit('Back up outside the source data directory.')
    load_dotenv(ROOT/'.env');url=make_url(os.environ['BROBY_SPINE_URL'])
    pms_url=make_url(os.getenv('BROBY_PMS_URL',os.environ['BROBY_SPINE_URL']))
    if (url.host,url.port,url.database)!=(pms_url.host,pms_url.port,pms_url.database):
        raise SystemExit('This coordinated backup requires PMS and clinical schemas in the same PostgreSQL database.')
    pg_dump=ROOT/'.local/postgres/bin/pg_dump'
    binary=str(pg_dump) if pg_dump.exists() else shutil.which('pg_dump')
    if not binary:raise SystemExit('pg_dump is required')
    target.mkdir(parents=True,mode=0o700)
    env={**os.environ,'PGPASSWORD':url.password or ''}
    engine=create_engine(url,isolation_level='REPEATABLE READ')
    try:
        with engine.connect() as c,c.begin():
            c.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            snapshot=c.execute(text('SELECT pg_export_snapshot()')).scalar_one()
            inventory=database_inventory(c)
            subprocess.run([binary,'-h',url.host or '127.0.0.1','-p',str(url.port or 5432),'-U',url.username or '', '-d',url.database or '', '--snapshot='+snapshot,'-Fc','-f',str(target/'spine.dump')],env=env,check=True)
        (target/'spine.dump').chmod(0o600)
        files=file_inventory(source)
        shutil.copytree(source,target/'data')
        if file_inventory(target/'data')!=files or file_inventory(source)!=files:
            raise RuntimeError('Source files changed during backup. Stop all writers and retry into a new destination.')
        (target/'manifest.json').write_text(json.dumps({'format':3,'postgresql':'spine.dump','data':'data','pms_store':os.getenv('BROBY_PMS_STORE','sqlite'),'pms_schema':os.getenv('BROBY_PMS_SCHEMA','broby_pms'),
            'postgres_sha256':sha256(target/'spine.dump'),'tables':inventory,'files':files,
            'warning':'Sensitive backup: includes credentials and sharing grants. Preserve the PostgreSQL dump and data directory together. Environment secrets and browser drafts are excluded.'},indent=2))
        (target/'manifest.json').chmod(0o600)
    except Exception:
        (target/'INCOMPLETE').write_text('Backup did not complete. Do not restore this directory.');raise
    finally:engine.dispose()
    print('Coordinated backup created at',target)
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: .venv/bin/python scripts/backup-local.py /new/backup/directory')
    backup(sys.argv[1])
