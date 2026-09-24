"""Broby API with isolated local and authenticated hosted deployment modes."""
import csv, hashlib, io, json, os, re, threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Response, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from db import init, connection, all_records, get, record, update, event, uid, now, unpack, DATA
from actions import execute, owned, fail, PERMISSIONS, authorize, allowed_actions
import jobs,auth,providers,runtime

@asynccontextmanager
async def lifespan(app):
    runtime.validate()
    init(seed=os.getenv('BROBY_SEED_DEMO', '1') == '1'); auth.setup_tables();
    runtime.provision_admin()
    from spine.projection import setup_queue
    setup_queue(); worker_stop = threading.Event()
    from operations_health import start_workers
    monitor = start_workers(worker_stop)
    app.state.workers = monitor
    try:
        yield
    finally:
        worker_stop.set()
        for thread in monitor.threads.values(): thread.join(timeout=3)

from read_access import enforce_route
app=FastAPI(title='Broby V2',lifespan=lifespan,dependencies=[Depends(enforce_route)],
            docs_url=None if runtime.hosted() else '/docs',
            redoc_url=None if runtime.hosted() else '/redoc',
            openapi_url=None if runtime.hosted() else '/openapi.json')

def identity(request):
    if auth.enabled(): return auth.resolve(request)
    clinic=request.headers.get('x-clinic-id','clinic-east')
    actor=request.headers.get('x-actor-id',clinic+'-vet')
    with connection() as c:
        member=owned(c,actor,clinic,'member')
        if not member['data'].get('active'): fail('Member is inactive',403)
    return clinic,actor
@app.middleware('http')
async def browser_boundary(request,call_next):
    origin=request.headers.get('origin','')
    if origin and origin not in runtime.allowed_origins():
        return Response('Origin not allowed',status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('sec-fetch-site') == 'cross-site':
        return Response('Cross-site request not allowed',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    return response
@app.get('/api/health')
def health(): return {'status':'ok','mode':'password' if auth.enabled() else 'local-demo'}
@app.get('/api/ready')
def ready():
    try:
        with connection() as c: c.execute('SELECT COUNT(*) FROM records').fetchone()
        from sqlalchemy import text
        from spine.database import engine
        with engine().connect() as c: c.execute(text('SELECT version_num FROM alembic_version')).one()
        probe=DATA/'.readiness'
        probe.write_text('ok'); probe.unlink(missing_ok=True)
    except Exception:
        return Response('Storage unavailable',status_code=503)
    from db import store
    return {'status':'ready','stores':['postgresql','files'] if store()=='postgres' else ['postgresql','sqlite','files'],'pms_store':store()}
@app.get('/api/bootstrap')
def bootstrap(request:Request):
    clinic,actor=identity(request)
    with connection() as c:
        member=owned(c,actor,clinic,'member')
        from spine.reader import native_records
        rs=all_records(c,clinic)+native_records(clinic)
        from read_access import allowed_reads, filter_records, ALL
        reads=allowed_reads(c,clinic,actor)
        rs=filter_records(rs,reads,actor)
        if auth.enabled():
            sess=auth.session(request); clinics=[]
            for membership in c.execute('SELECT clinic_id,member_id FROM auth_memberships WHERE username=?',(sess['username'],)):
                entry=get(c,membership['clinic_id'],membership['clinic_id']); linked=get(c,membership['member_id'],membership['clinic_id'])
                if entry and linked and linked['data'].get('active'):clinics.append({**entry,'member_id':linked['id']})
        else:clinics=[unpack(r) for r in c.execute("SELECT * FROM records WHERE kind='clinic' ORDER BY id")]
        from stripe_payments import configured
        integrations={**providers.available(),'payments':configured(clinic)}
        return {'records':rs,'actor':member,'clinic':get(c,clinic,clinic),'clinics':clinics,'jobs':[unpack(r) for r in c.execute('SELECT * FROM jobs WHERE clinic_id=? ORDER BY created_at DESC LIMIT 20',(clinic,))] if ALL<=reads else [],'permissions':allowed_actions(c,clinic,actor),'read_permissions':sorted(reads),'integrations':integrations,'mode':'password' if auth.enabled() else 'local-demo'}
class Command(BaseModel):
    action:str
    payload:dict[str,Any]=Field(default_factory=dict)
    key:str=Field(min_length=8,max_length=128)
@app.post('/api/actions')
def action(cmd:Command,request:Request):
    clinic,actor=identity(request)
    return execute(cmd.action,cmd.payload,clinic,actor,cmd.key)
@app.get('/api/jobs/{job_id}')
def job(job_id:str,request:Request):
    clinic,_=identity(request)
    with connection() as c:
        r=unpack(c.execute('SELECT * FROM jobs WHERE id=? AND clinic_id=?',(job_id,clinic)).fetchone())
        if not r: fail('Job not found',404)
        return r
@app.post('/api/uploads')
async def upload(request:Request,file:UploadFile=File(...),patient_id:str=Form(...),consultation_id:str=Form('')):
    clinic,actor=identity(request)
    content=await file.read(20*1024*1024+1)
    if len(content)>20*1024*1024: fail('File exceeds 20 MB',413)
    mime=file.content_type or 'application/octet-stream'
    if mime not in ('application/pdf','image/png','image/jpeg','image/webp','text/plain','text/csv'): fail('Use a PDF, image, text or CSV file')
    with connection(True) as c:
        authorize(c,clinic,actor,'source.add')
        owned(c,patient_id,clinic,'patient')
        if consultation_id:
            cr=owned(c,consultation_id,clinic,'consultation')
            if cr['data']['patient_id']!=patient_id: fail('Patient mismatch')
        id=uid(); path=DATA/'files'/id; path.parent.mkdir(exist_ok=True); path.write_bytes(content)
        r=record(c,'attachment',clinic,{'patient_id':patient_id,'consultation_id':consultation_id,'name':Path(file.filename or 'attachment').name,'mime':mime,'size':len(content),'path':str(path),'sha256':hashlib.sha256(content).hexdigest(),'approved':False},id)
        event(c,clinic,patient_id,'document',r['data']['name'],'Document attached. Findings must be entered with a source reference.',[id])
        return r
@app.get('/api/files/{id}')
def file(id:str,request:Request):
    clinic,_=identity(request)
    with connection() as c: r=owned(c,id,clinic,'attachment')
    return FileResponse(r['data']['path'],media_type=r['data']['mime'],filename=r['data']['name'])
@app.put('/api/recordings/{id}/chunks/{index}')
async def chunk(id:str,index:int,request:Request):
    clinic,actor=identity(request)
    if index<0 or index>100000: fail('Invalid chunk index')
    body=await request.body()
    if len(body)>12*1024*1024 or not body: fail('Invalid chunk size')
    sha=hashlib.sha256(body).hexdigest()
    with connection(True) as c:
        authorize(c,clinic,actor,'recording.create')
        r=owned(c,id,clinic,'recording')
        previous=c.execute('SELECT sha256 FROM chunks WHERE recording_id=? AND chunk_index=?',(id,index)).fetchone()
        if previous:
            if previous[0]!=sha: fail('Chunk content does not match the saved chunk',409)
            return {'index':index,'sha256':sha}
        if r['data']['status']=='saved': fail('Recording already completed',409)
        path=DATA/'audio'/id/str(index); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(body)
        c.execute('INSERT INTO chunks VALUES(?,?,?,?)',(id,index,str(path),sha))
    return {'index':index,'sha256':sha}
@app.get('/api/recordings/{id}/manifest')
def manifest(id:str,request:Request):
    clinic,_=identity(request)
    with connection() as c:
        owned(c,id,clinic,'recording'); return {'received':[r[0] for r in c.execute('SELECT chunk_index FROM chunks WHERE recording_id=? ORDER BY chunk_index',(id,))]}
@app.get('/api/recordings/{id}/audio')
def audio(id:str,request:Request):
    clinic,_=identity(request)
    with connection() as c:
        r=owned(c,id,clinic,'recording'); paths=[r[0] for r in c.execute('SELECT path FROM chunks WHERE recording_id=? ORDER BY chunk_index',(id,))]
    from audio_response import audio_response
    return audio_response(b''.join(Path(p).read_bytes() for p in paths),r['data'].get('mime','audio/webm'),request.headers.get('range'))
@app.get('/api/audit')
def audit(request:Request):
    clinic,actor=identity(request)
    with connection() as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin': fail('Administrator access required',403)
        return [dict(r) for r in c.execute('SELECT * FROM audit WHERE clinic_id=? ORDER BY created_at DESC LIMIT 100',(clinic,))]
@app.post('/api/import/preview')
async def preview(request:Request,file:UploadFile=File(...)):
    clinic,actor=identity(request)
    with connection() as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin': fail('Administrator access required',403)
    content=await file.read(2*1024*1024+1)
    if len(content)>2*1024*1024: fail('Import exceeds 2 MB',413)
    try: rows=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
    except Exception: fail('Upload a UTF-8 CSV with a header row')
    if len(rows)>1000: fail('Import at most 1000 patients at a time')
    errors=[]
    for i,row in enumerate(rows):
        for field in ('name','species','owner_name'):
            if not row.get(field,'').strip(): errors.append(f'Row {i+2}: {field} is required')
    return {'rows':rows,'errors':errors,'count':len(rows)}
@app.get('/api/export')
def export(request:Request):
    clinic,actor=identity(request)
    with connection() as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin': fail('Administrator access required',403)
        from spine.reader import native_records
        rs=all_records(c,clinic)+native_records(clinic)
    for r in rs: r['data'].pop('path',None)
    return Response(json.dumps({'schema_version':1,'exported_at':now(),'records':rs},indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="broby-clinic-export.json"'})
class Chat(BaseModel):
    message:str=Field(min_length=1,max_length=2000)
    patient_id:str|None=None
    history:list[str]=Field(default_factory=list,max_length=10)
    conversation_id:str|None=Field(default=None,max_length=100)
    key:str|None=Field(default=None,min_length=8,max_length=128)
@app.post('/api/assistant')
def assistant(body:Chat,request:Request):
    from assistant import answer
    from providers import ProviderError
    clinic,actor=identity(request)
    try:
        if body.key:
            from assistant_history import ask
            return ask(clinic,actor,body.message,body.patient_id,body.conversation_id,body.key)
        with connection() as c:
            result=answer(c,clinic,actor,body.message,body.patient_id,body.history)
            from read_access import require, ALL
            require(c,clinic,actor,ALL)
            return result
    except ProviderError:
        # A saved question remains failed/retryable, with no confirmable action.
        fail('The AI provider could not return a verified answer. No clinic record was changed. Retry this question.',503)

from portal import router as portal_router
from routes_extra import router as extra_router
app.include_router(portal_router)
app.include_router(extra_router)

from exports import router as export_router
app.include_router(export_router)

from spine.routes import router as spine_router
app.include_router(spine_router)

from accounts import router as accounts_router
app.include_router(accounts_router)

from integration_hooks import router as hook_router
app.include_router(hook_router)

from transfers import router as transfers_router
app.include_router(transfers_router)

from stripe_payments import router as stripe_router
app.include_router(stripe_router)

from assistant_history import router as assistant_history_router
app.include_router(assistant_history_router)

from twilio_trial import router as twilio_router
app.include_router(twilio_router)

from scheduling import router as scheduling_router
app.include_router(scheduling_router)

from operations_health import router as operations_router
app.include_router(operations_router)

from financial_reports import router as financial_router
app.include_router(financial_router)

from recalls import router as recalls_router
app.include_router(recalls_router)

from organization_adoption import router as adoption_router
app.include_router(adoption_router)

from access_controls import router as access_router
app.include_router(access_router)
from owner_conversations import router as owner_conversations_router
app.include_router(owner_conversations_router)

from marketing_leads import router as marketing_leads_router
app.include_router(marketing_leads_router)
