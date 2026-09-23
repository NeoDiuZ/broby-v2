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
    pg_dump=ROOT/'.local/postgres/bin/pg_dump'
    binary=str(pg_dump) if pg_dump.exists() else shutil.which('pg_dump')
    if not binary:raise SystemExit('pg_dump is required')
    target.mkdir(parents=True,mode=0o700)
    env={**os.environ,'PGPASSWORD':url.password or ''}
    try:
        subprocess.run([binary,'-h',url.host or '127.0.0.1','-p',str(url.port or 5432),'-U',url.username or '', '-d',url.database or '', '-Fc','-f',str(target/'spine.dump')],env=env,check=True)
        shutil.copytree(Path(os.getenv('BROBY_DATA_DIR',ROOT/'api/data')),target/'legacy-data')
        (target/'manifest.json').write_text(json.dumps({'format':1,'spine':'spine.dump','legacy':'legacy-data','warning':'Sensitive backup: includes legacy credentials and sharing grants. Store securely. Environment secrets are excluded.'},indent=2))
    except Exception:
        (target/'INCOMPLETE').write_text('Backup did not complete. Do not restore this directory.');raise
    print('Coordinated backup created at',target)
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: .venv/bin/python scripts/backup-local.py /new/backup/directory')
    backup(sys.argv[1])
