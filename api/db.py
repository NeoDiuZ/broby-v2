"""Transactional clinic store with explicit SQLite and PostgreSQL backends."""
import json, os, sqlite3, uuid, re
from contextvars import ContextVar
mutation_actor=ContextVar('mutation_actor',default=None)
store_override=ContextVar('store_override',default=None)
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

DATA = Path(os.environ.get('BROBY_DATA_DIR', Path(__file__).parent / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'broby.sqlite3'
def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid.uuid4())
def unpack(row):
    if not row: return None
    result = dict(row)
    for key in ('data','payload','result'):
        if key in result and result[key] is not None: result[key] = json.loads(result[key])
    return result
class TransactionConnection(sqlite3.Connection):
    """Track newly created binary files until their owning transaction commits."""
    rollback_files: list
    dialect='sqlite'

def store():
    value=store_override.get() or os.getenv('BROBY_PMS_STORE','sqlite')
    if value not in ('sqlite','postgres'):raise ValueError('Unknown BROBY_PMS_STORE')
    return value

def identifier(value):
    if not re.fullmatch(r'[a-z][a-z0-9_]*',value):raise ValueError('Invalid database identifier')
    return value

def upsert(con,table,data,keys,ignore=False):
    table=identifier(table);columns=[identifier(k) for k in data];keys=[identifier(k) for k in keys]
    sql='INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')'
    if ignore:sql+=' ON CONFLICT DO NOTHING'
    else:sql+=' ON CONFLICT('+','.join(keys)+') DO UPDATE SET '+','.join(k+'=excluded.'+k for k in columns if k not in keys)
    return con.execute(sql,tuple(data.values()))

def columns(con,table):
    table=identifier(table)
    if con.dialect=='postgres':
        return [r[0] for r in con.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position',(table,))]
    return [r[1] for r in con.execute('PRAGMA table_info('+table+')')]

def json_text(con,column,*path):
    column=identifier(column);path=[identifier(p) for p in path]
    if con.dialect=='postgres':return column+"::jsonb #>> '{"+','.join(path)+"}'"
    return "json_extract("+column+",'$."+'.'.join(path)+"')"

def transaction_file(con, path, content):
    if not con.in_transaction:
        raise RuntimeError('Binary copies require a write transaction')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation ensures rollback can never remove an existing copy.
    with path.open('xb') as output:
        con.rollback_files.append(path)
        output.write(content)
        output.flush()
        os.fsync(output.fileno())

@contextmanager
def connection(write=False,*,snapshot=False):
    postgres=store()=='postgres'
    if postgres:
        from pms_postgres import Connection
        con=Connection()
    else:
        if DB.with_suffix('.cutover.json').exists():
            raise RuntimeError('This PMS database has entered PostgreSQL cutover; SQLite fallback is disabled')
        con = sqlite3.connect(DB, timeout=20, factory=TransactionConnection)
        con.rollback_files = []
        DB.chmod(0o600)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
    try:
        if postgres:con.begin(write,snapshot=snapshot)
        elif write: con.execute('BEGIN IMMEDIATE')
        elif snapshot:con.execute('BEGIN')
        yield con
        if write: con.commit()
    except Exception:
        if write: con.rollback()
        for path in reversed(con.rollback_files):
            path.unlink(missing_ok=True)
        raise
    finally: con.close()
def record(con, kind, clinic, data, id=None):
    id=id or uid()
    con.execute('INSERT INTO records(id,kind,clinic_id,data,version,created_at,updated_at) VALUES(?,?,?,?,1,?,?)',(id,kind,clinic,json.dumps(data),now(),now()))
    return get(con,id,clinic)
def get(con,id,clinic=None):
    row=con.execute('SELECT * FROM records WHERE id=?'+(' AND clinic_id=?' if clinic else ''),(id,clinic) if clinic else (id,)).fetchone()
    return unpack(row)
def all_records(con,clinic,kind=None):
    rows=con.execute('SELECT * FROM records WHERE clinic_id=?'+(' AND kind=?' if kind else '')+' ORDER BY created_at DESC',(clinic,kind) if kind else (clinic,)).fetchall()
    return [unpack(r) for r in rows]
def update(con,r,data):
    changed=con.execute('UPDATE records SET data=?,version=version+1,updated_at=? WHERE id=? AND version=?',(json.dumps(data),now(),r['id'],r['version']))
    if changed.rowcount!=1:
        from fastapi import HTTPException
        raise HTTPException(409,'Record changed before this write; reload and retry')
    return get(con,r['id'],r['clinic_id'])
def event(con,clinic,patient_id,category,title,body,source_ids=None,approved=False):
    actor=mutation_actor.get()
    if not source_ids and actor:
        member=get(con,actor,clinic)
        receipt=record(con,'source',clinic,{'patient_id':patient_id,'title':title+' · recorded action','text':body,'category':category,'section':'Objective','author':member['data']['name'] if member else 'Recorded clinic action','actor_id':actor})
        source_ids=[receipt['id']]
    return record(con,'event',clinic,{'patient_id':patient_id,'category':category,'title':title,'body':body,'source_ids':source_ids or [],'approved':approved,'occurred_at':now()})
def init(seed=True):
    if store()=='postgres':
        from pms_postgres import create_schema
        create_schema()
    else:
        with connection() as c:c.execute('PRAGMA journal_mode=WAL')
    with connection(True) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,clinic_id TEXT NOT NULL,data TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS records_scope ON records(clinic_id,kind);
        CREATE TABLE IF NOT EXISTS mutations(clinic_id TEXT,actor_id TEXT,key TEXT,payload_hash TEXT,result TEXT,PRIMARY KEY(clinic_id,actor_id,key));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,clinic_id TEXT,consultation_id TEXT,status TEXT,payload TEXT,result TEXT,error TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,clinic_id TEXT,actor_id TEXT,action TEXT,resource_id TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS grants(token TEXT PRIMARY KEY,clinic_id TEXT,patient_id TEXT,expires_at TEXT,revoked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS chunks(recording_id TEXT,chunk_index INTEGER,path TEXT,sha256 TEXT,PRIMARY KEY(recording_id,chunk_index));
        ''')
    from schema import migrate
    with connection(True) as c:migrate(c)
    if store()=='postgres':
        from pms_postgres import projection_queue
        from pms_migrate import promote_if_needed
        with connection(True) as c:projection_queue(c)
        promote_if_needed()
    if not seed:return
    with connection(True) as c:
        if c.execute('SELECT COUNT(*) FROM records').fetchone()[0]: return
        for clinic,name in [('clinic-east','Broby • East Coast'),('clinic-river','Broby • River Valley')]:
            record(c,'clinic',clinic,{'name':name,'timezone':'Asia/Singapore','currency':'SGD','retention':'medical','locked_features':[]},clinic)
            record(c,'settings',clinic,{'retention':'medical','language':'en','emergency_phone':'+65 6000 0000','reminder_days':7},'settings-'+clinic)
            for id,name,role in [('vet','Dr. Amelia Tan','vet'),('nurse','Nur Aisyah','nurse'),('admin','Daniel Lim','admin')]:
                record(c,'member',clinic,{'name':name,'role':role,'active':True},clinic+'-'+id)
            record(c,'template',clinic,{'name':'SOAP consultation','description':'The familiar four-section clinical note.','sections':['Subjective','Objective','Assessment','Plan']},'soap-'+clinic)
            record(c,'template',clinic,{'name':'Discharge instructions','description':'Approved findings and instructions for the owner.','sections':['Visit summary','Medication','Home care','Follow-up']})
            for name,unit,stock,price in [('Consultation','service',0,4800),('Amoxicillin 250 mg','tablet',120,180),('Meloxicam 1.5 mg/ml','bottle',8,2850),('Canine vaccination','dose',24,6500),('Blood count','test',20,8200)]:
                record(c,'inventory',clinic,{'name':name,'unit':unit,'stock':stock,'reorder':10 if unit!='service' else 0,'price_cents':price})
        patients=[('milo','Milo','Dog','Golden Retriever','Male',28.4,'4 years','Rachel Tan','Annual wellness',9),('luna','Luna','Cat','British Shorthair','Female',4.2,'3 years','Marcus Lee','Appetite follow-up',9.5),('bella-dog','Bella','Dog','Cavapoo','Female',7.8,'2 years','Priya Nair','Skin review',10),('mochi','Mochi','Rabbit','Holland Lop','Male',1.9,'1 year','Sofia Chua','Dental check',11),('teddy','Teddy','Dog','Shiba Inu','Male',10.6,'6 years','Ethan Wong','Vaccination',12),('olive','Olive','Cat','Domestic Shorthair','Female',3.6,'8 years','Hannah Goh','Senior wellness',14),('oscar','Oscar','Dog','Dachshund','Male',8.1,'5 years','Adrian Koh','Post-operative review',15),('bella-cat','Bella','Cat','Ragdoll','Female',4.8,'4 years','Mei Lin','Routine check',16)]
        today=datetime.now().astimezone().date().isoformat()
        for i,(id,name,species,breed,sex,weight,age,owner,reason,hour) in enumerate(patients):
            owner_id='owner-'+id
            record(c,'owner','clinic-east',{'name':owner,'email':owner.lower().replace(' ','.')+'@example.test','phone':'+65 8000 '+str(1000+i)},owner_id)
            record(c,'patient','clinic-east',{'name':name,'species':species,'breed':breed,'sex':sex,'weight':weight,'age':age,'owner_id':owner_id,'external_id':'DEMO-'+str(100+i)},id)
            record(c,'appointment','clinic-east',{'patient_id':id,'date':today,'time':f'{int(hour):02d}:{"30" if hour%1 else "00"}','duration':30,'reason':reason,'clinician':'clinic-east-vet','status':'completed' if i==0 else 'arrived' if i==1 else 'scheduled'})
            source=record(c,'source','clinic-east',{'patient_id':id,'title':'Previous visit · veterinarian note','text':f'{name} attended for a routine check. Weight {weight} kg. Owner reports normal appetite.','category':'clinical','section':'Subjective','author':'Dr. Amelia Tan'})
            e=event(c,'clinic-east',id,'consultation','Wellness consultation',source['data']['text'],[source['id']],True)
            d=e['data']; d['occurred_at']=(datetime.now(timezone.utc)-timedelta(days=30+i*4)).isoformat(); update(c,e,d)
            record(c,'observation','clinic-east',{'patient_id':id,'name':'Weight','value':weight,'unit':'kg','low':None,'high':None,'source_id':source['id'],'category':'Vitals'})
        record(c,'consultation','clinic-east',{'patient_id':'luna','title':'Appetite follow-up','status':'in_progress','template_id':'soap-clinic-east','summary':[],'source_ids':[],'input_revision':0,'generated_revision':0,'date':today},'consult-luna')
        record(c,'reminder','clinic-east',{'patient_id':'teddy','title':'Annual vaccination','due':today,'status':'due'})
        source=record(c,'source','clinic-east',{'patient_id':'olive','title':'Sample laboratory report','text':'Creatinine 2.1 mg/dL. Laboratory reference interval 0.8–1.8 mg/dL.','category':'bloods','section':'Objective','author':'Imported sample'})
        record(c,'observation','clinic-east',{'patient_id':'olive','name':'Creatinine','value':2.1,'unit':'mg/dL','low':0.8,'high':1.8,'source_id':source['id'],'category':'Bloods'})
        event(c,'clinic-east','olive','bloods','Blood chemistry',source['data']['text'],[source['id']],True)
        record(c,'invoice','clinic-east',{'patient_id':'milo','number':'INV-1001','items':[{'name':'Consultation','quantity':1,'price_cents':4800},{'name':'Blood count','quantity':1,'price_cents':8200}],'total_cents':13000,'paid_cents':0,'status':'issued'})
