"""Offline whole-workspace backup. Stops on a live API; never overwrites a folder."""
from pathlib import Path
import os,sys,subprocess,shutil,urllib.request,json
from dotenv import load_dotenv
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parents[1]
def backup(destination):
    try:urllib.request.urlopen('http://127.0.0.1:8100/api/health',timeout=1)
    except OSError:pass
    else:raise SystemExit('Stop the API before making a coordinated backup, then run this command again.')
    target=Path(destination).resolve()
    if target.exists():raise SystemExit('Choose a new destination directory; existing data is never overwritten.')
    load_dotenv(ROOT/'.env');url=make_url(os.environ['BROBY_SPINE_URL'])
    pms_url=make_url(os.getenv('BROBY_PMS_URL',os.environ['BROBY_SPINE_URL']))
    if (url.host,url.port,url.database)!=(pms_url.host,pms_url.port,pms_url.database):
        raise SystemExit('This coordinated backup requires PMS and clinical schemas in the same PostgreSQL database.')
    pg_dump=ROOT/'.local/postgres/bin/pg_dump'
    binary=str(pg_dump) if pg_dump.exists() else shutil.which('pg_dump')
    if not binary:raise SystemExit('pg_dump is required')
    target.mkdir(parents=True,mode=0o700)
    env={**os.environ,'PGPASSWORD':url.password or ''}
    try:
        subprocess.run([binary,'-h',url.host or '127.0.0.1','-p',str(url.port or 5432),'-U',url.username or '', '-d',url.database or '', '-Fc','-f',str(target/'spine.dump')],env=env,check=True)
        (target/'spine.dump').chmod(0o600)
        shutil.copytree(Path(os.getenv('BROBY_DATA_DIR',ROOT/'api/data')),target/'data')
        (target/'manifest.json').write_text(json.dumps({'format':2,'postgresql':'spine.dump','data':'data','pms_store':os.getenv('BROBY_PMS_STORE','sqlite'),'warning':'Sensitive backup: includes credentials and sharing grants. Preserve the PostgreSQL dump and data directory together. Environment secrets and browser drafts are excluded.'},indent=2))
    except Exception:
        (target/'INCOMPLETE').write_text('Backup did not complete. Do not restore this directory.');raise
    print('Coordinated backup created at',target)
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: .venv/bin/python scripts/backup-local.py /new/backup/directory')
    backup(sys.argv[1])
