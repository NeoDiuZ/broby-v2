"""Explicit, verified promotion of one stopped SQLite PMS into PostgreSQL.

Startup runs this before seeding, accepting requests or starting workers. The
legacy database is locked and retained. A local durable fence prevents fallback
to it, even when copying fails. No existing PostgreSQL clinic store is replaced.
"""
import hashlib,json,os,sqlite3,uuid
from pathlib import Path
import db
from pms_postgres import schema


def write_private(path,content):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as file:
        file.write(content);file.flush();os.fsync(file.fileno())
    os.replace(temporary,path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


def fingerprint(connection,table,columns,keys):
    query='SELECT '+','.join(columns)+' FROM '+table+' ORDER BY '+','.join(keys)
    digest=hashlib.sha256();count=0
    for row in connection.execute(query):
        digest.update(json.dumps(list(row),ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()+b'\n')
        count+=1
    return {'rows':count,'sha256':digest.hexdigest()}


def target_tables(c):
    return {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'")}


def source_tables(source):
    result={}
    for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        table=db.identifier(row[0]);info=source.execute('PRAGMA table_info('+table+')').fetchall()
        columns=[db.identifier(r['name']) for r in info]
        keys=[db.identifier(r['name']) for r in sorted(info,key=lambda r:r['pk']) if r['pk']]
        if not keys:raise RuntimeError('Migration needs a stable primary key: '+table)
        result[table]={'columns':columns,'keys':keys}
    return result


def preserve_backup(source,path,tables):
    if not path.exists():
        write_private(path,source.serialize())
        return
    # Retry after installing the SQL write fence changes SQLite schema bytes but
    # must never change a table, column, key or value from the original backup.
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as backup:
        backup.row_factory=sqlite3.Row
        if source_tables(backup)!=tables:
            raise RuntimeError('Legacy SQLite changed after its cutover backup; resolve the source before retrying')
        for table,info in tables.items():
            if fingerprint(source,table,info['columns'],info['keys'])!=fingerprint(backup,table,info['columns'],info['keys']):
                raise RuntimeError('Legacy SQLite changed after its cutover backup; resolve the source before retrying')


def freeze_legacy(source,tables):
    # Fence at the database boundary as well as in the new application: a still
    # open connection from an older binary must not resume writing stale data.
    for table in tables:
        for operation in ('INSERT','UPDATE','DELETE'):
            name='pms_frozen_'+table+'_'+operation.lower()
            source.execute(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'PMS moved to PostgreSQL; legacy writes disabled'); END")
    source.commit()
    source.execute('BEGIN EXCLUSIVE')


def promote_if_needed():
    path=db.DB.with_suffix('.cutover.json')
    guard=json.loads(path.read_text()) if path.exists() else None
    with db.connection(True) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pms_migration(
            id INTEGER PRIMARY KEY CHECK(id=1),migration_id TEXT NOT NULL,status TEXT NOT NULL,manifest TEXT NOT NULL)''')
        existing=c.execute('SELECT * FROM pms_migration WHERE id=1').fetchone()
        target={'database':c.execute('SELECT current_database()').fetchone()[0],'schema':schema()}
        if existing:
            if guard and (guard['migration_id']!=existing['migration_id'] or guard['target']!=target):
                raise RuntimeError('Local cutover fence does not match the PostgreSQL PMS store')
            if not guard and db.DB.exists():
                raise RuntimeError('Refusing to attach an unfenced SQLite store to an existing PostgreSQL PMS')
            if not guard or guard['state']!='complete':
                write_private(path,json.dumps({'migration_id':existing['migration_id'],'target':target,'state':'complete'}).encode())
            return json.loads(existing['manifest'])
        if guard and (guard['target']!=target or guard['state']=='complete'):
            raise RuntimeError('The PostgreSQL destination does not match the completed cutover fence')

    source=None
    try:
        if db.DB.exists():
            if os.getenv('BROBY_PMS_MIGRATE')!='1':
                raise RuntimeError('An existing SQLite PMS requires explicit BROBY_PMS_MIGRATE=1 at stopped-service cutover')
            source=sqlite3.connect(db.DB.as_uri()+'?mode=rw',uri=True,timeout=20)
            source.row_factory=sqlite3.Row
            source.execute('BEGIN EXCLUSIVE')
        tables=source_tables(source) if source else {}
        with db.connection(True) as c:
            # Serialize concurrent startup and recheck after acquiring the writer lock.
            if c.execute('SELECT 1 FROM pms_migration WHERE id=1').fetchone():
                raise RuntimeError('Another process completed PMS initialization; restart this process')
            known=target_tables(c)
            if set(tables)-known:raise RuntimeError('SQLite contains unmapped tables: '+','.join(sorted(set(tables)-known)))
            for table in known-{'pms_migration','ontology','schema_migrations'}:
                if c.execute('SELECT 1 FROM '+db.identifier(table)+' LIMIT 1').fetchone():
                    raise RuntimeError('PostgreSQL destination is not empty: '+table)
            for table,info in tables.items():
                if set(info['columns'])-set(db.columns(c,table)):
                    raise RuntimeError('SQLite contains unmapped columns in '+table)
            migration_id=guard['migration_id'] if guard else str(uuid.uuid4())
            uuid.UUID(migration_id)
            # Fence first, then commit PostgreSQL; every crash position is either
            # retryable here or refuses the stale SQLite writer.
            write_private(path,json.dumps({'migration_id':migration_id,'target':target,'state':'in_progress'}).encode())
            backup=None
            if source:
                backup=db.DATA/'pms-cutover'/migration_id/'legacy.sqlite3'
                preserve_backup(source,backup,tables)
                freeze_legacy(source,tables)
            for table in ('records','auth_memberships'):c.execute('ALTER TABLE '+table+' DISABLE TRIGGER USER')
            manifest={'version':1,'migration_id':migration_id,'origin':'sqlite' if source else 'fresh',
                      'completed_at':db.now(),'tables':{},'backup':str(backup.relative_to(db.DATA)) if backup else None}
            for table,info in tables.items():
                columns=info['columns'];keys=info['keys']
                expected=fingerprint(source,table,columns,keys)
                c.execute('DELETE FROM '+table)
                rows=source.execute('SELECT '+','.join(columns)+' FROM '+table)
                sql='INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')'
                while True:
                    batch=rows.fetchmany(200)
                    if not batch:break
                    c.executemany(sql,[tuple(row) for row in batch])
                actual=fingerprint(c,table,columns,keys)
                if actual!=expected:raise RuntimeError('Migration content verification failed: '+table)
                manifest['tables'][table]=actual
            c.execute("SELECT setval('spine_changes_sequence_seq',COALESCE((SELECT MAX(sequence) FROM spine_changes),0)+1,false)")
            for table in ('records','auth_memberships'):c.execute('ALTER TABLE '+table+' ENABLE TRIGGER USER')
            c.execute('INSERT INTO pms_migration VALUES(1,?,?,?)',(migration_id,'complete',json.dumps(manifest)))
        write_private(path,json.dumps({'migration_id':migration_id,'target':target,'state':'complete'}).encode())
        print('PMS PostgreSQL promotion verified: '+str(len(manifest['tables']))+' tables, '+
              str(sum(info['rows'] for info in manifest['tables'].values()))+' rows; legacy writes fenced',flush=True)
        return manifest
    finally:
        if source:source.rollback();source.close()
