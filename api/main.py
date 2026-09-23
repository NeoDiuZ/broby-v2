"""Local-only preview API. Synthetic data; no production connection or credentials."""
import csv, hashlib, io, json, os, re, threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from db import init, connection, all_records, get, record, update, event, uid, now, unpack, DATA
from actions import execute, owned, fail, PERMISSIONS
import jobs,auth,providers

@asynccontextmanager
async def lifespan(app):
    init(); auth.setup_tables();
    from spine.projection import setup_queue
    setup_queue(); jobs.stop.clear(); thread=threading.Thread(target=jobs.loop,daemon=True); thread.start()
    yield
    jobs.stop.set(); thread.join(timeout=3)
app=FastAPI(title='Broby local workspace',lifespan=lifespan)

def identity(request):
    if auth.enabled(): return auth.resolve(request)
    clinic=request.headers.get('x-clinic-id','clinic-east')
    actor=request.headers.get('x-actor-id',clinic+'-vet')
    with connection() as c:
        member=owned(c,actor,clinic,'member')
        if not member['data'].get('active'): fail('Member is inactive',403)
    return clinic,actor
@app.middleware('http')
async def local_boundary(request,call_next):
    # Local preview is not an internet-facing authentication deployment.
    origin=request.headers.get('origin','')
    if origin and origin not in ('http://127.0.0.1:3100','http://localhost:3100','http://127.0.0.1:8100') and not origin.startswith('chrome-extension://'):
        return Response('Origin not allowed',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    return response
@app.get('/api/health')
def health(): return {'status':'ok','mode':'local-demo'}
@app.get('/api/bootstrap')
def bootstrap(request:Request):
    clinic,actor=identity(request)
    with connection() as c:
        member=owned(c,actor,clinic,'member')
        rs=all_records(c,clinic)
        if auth.enabled():
            sess=auth.session(request); clinics=[]
            for membership in c.execute('SELECT clinic_id,member_id FROM auth_memberships WHERE username=?',(sess['username'],)):
                entry=get(c,membership['clinic_id'],membership['clinic_id']); linked=get(c,membership['member_id'],membership['clinic_id'])
                if entry and linked and linked['data'].get('active'):clinics.append({**entry,'member_id':linked['id']})
        else:clinics=[unpack(r) for r in c.execute("SELECT * FROM records WHERE kind='clinic' ORDER BY id")]
        return {'records':rs,'actor':member,'clinic':get(c,clinic,clinic),'clinics':clinics,'jobs':[unpack(r) for r in c.execute('SELECT * FROM jobs WHERE clinic_id=? ORDER BY created_at DESC LIMIT 20',(clinic,))],'permissions':[a for a,roles in PERMISSIONS.items() if member['data']['role'] in roles],'integrations':providers.available(),'mode':'password' if auth.enabled() else 'local-demo'}
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
        owned(c,patient_id,clinic,'patient')
        if consultation_id:
            cr=owned(c,consultation_id,clinic,'consultation')
            if cr['data']['patient_id']!=patient_id: fail('Patient mismatch')
        id=uid(); path=DATA/'files'/id; path.parent.mkdir(exist_ok=True); path.write_bytes(content)
        r=record(c,'attachment',clinic,{'patient_id':patient_id,'consultation_id':consultation_id,'name':Path(file.filename or 'attachment').name,'mime':mime,'size':len(content),'path':str(path),'sha256':hashlib.sha256(content).hexdigest(),'approved':False},id)
        event(c,clinic,patient_id,'document',r['data']['name'],'Document attached. Findings must be entered with a source reference.')
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
    return Response(b''.join(Path(p).read_bytes() for p in paths),media_type=r['data'].get('mime','audio/webm'))
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
        rs=all_records(c,clinic)
    for r in rs: r['data'].pop('path',None)
    return Response(json.dumps({'schema_version':1,'exported_at':now(),'records':rs},indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="broby-clinic-export.json"'})
class Chat(BaseModel):
    message:str=Field(min_length=1,max_length=2000)
    patient_id:str|None=None
    history:list[str]=Field(default_factory=list,max_length=10)
@app.post('/api/assistant')
def assistant(body:Chat,request:Request):
    from assistant import answer
    clinic,actor=identity(request)
    with connection() as c:return answer(c,clinic,actor,body.message,body.patient_id,body.history)

from portal import router as portal_router
from routes_extra import router as extra_router
app.include_router(portal_router)
app.include_router(extra_router)

from exports import router as export_router
app.include_router(export_router)

from spine.routes import router as spine_router
app.include_router(spine_router)
