"""Restore a clinic ZIP into an EMPTY data directory; never overwrites a database."""
import argparse,os,json,zipfile,hashlib
from pathlib import Path

def restore(archive,destination):
    destination=Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):raise ValueError('Restore requires an empty destination directory')
    with zipfile.ZipFile(archive) as z:
        if sum(x.file_size for x in z.infolist())>500*1024*1024:raise ValueError('Backup exceeds 500 MB')
        m=json.loads(z.read('manifest.json'))
        if m.get('version')!=1:raise ValueError('Unsupported backup version')
        if m.get('native_event_count',0):raise ValueError('This archive contains native PostgreSQL facts. Use a coordinated whole-workspace restore; the legacy-only restore cannot preserve them.')
        files={}
        for f in m['files']:
            path=Path(f['path'])
            if path.is_absolute() or '..' in path.parts or path.parts[0] not in ('files','audio'):raise ValueError('Unsafe backup path')
            data=z.read(f['path'])
            if hashlib.sha256(data).hexdigest()!=f['sha256']:raise ValueError('Backup checksum mismatch')
            files[f['path']]=data
        ids={r['id'] for r in m['records']}
        if len(ids)!=len(m['records']) or any(r['clinic_id']!=m['clinic_id'] for r in m['records']):raise ValueError('Duplicate IDs or mixed clinic archive')
        for r in m['records']:
            if r['kind']=='attachment' and r['data']['path'] not in files:raise ValueError('Missing attachment')
        for ch in m['chunks']:
            if ch['path'] not in files or ch['recording_id'] not in ids:raise ValueError('Missing audio or recording')
    destination.mkdir(parents=True,exist_ok=True)
    import db
    original_db,original_data=db.DB,db.DATA
    store_token=db.store_override.set('sqlite')
    try:
        db.DB=destination/'broby.sqlite3';db.DATA=destination;db.init(seed=False)
        with db.connection(True) as c:
            for name,data in files.items():
                path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            for r in m['records']:
                if r['kind']=='attachment':r['data']['path']=str(destination/r['data']['path'])
                c.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',(r['id'],r['kind'],r['clinic_id'],json.dumps(r['data']),r['version'],r['created_at'],r['updated_at']))
            for h in m['history']:c.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',(h['record_id'],h['version'],h['clinic_id'],h['kind'],h['data'],h['recorded_at']))
            for term in m.get('ontology',[]):db.upsert(c,'ontology',{k:term[k] for k in ('code','name','value_type','unit','category')},['code'])
            for a in m.get('audit',[]):c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(a['id'],a['clinic_id'],a['actor_id'],a['action'],a['resource_id'],a['created_at']))
            for ch in m['chunks']:c.execute('INSERT INTO chunks VALUES(?,?,?,?)',(ch['recording_id'],ch['chunk_index'],str(destination/ch['path']),ch['sha256']))
    finally:
        db.DB,db.DATA=original_db,original_data
        db.store_override.reset(store_token)
    return len(m['records'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('empty_destination');args=p.parse_args();print(f"Restored {restore(args.archive,args.empty_destination)} records. Credentials and access grants are intentionally not restored.")
