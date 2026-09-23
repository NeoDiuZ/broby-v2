"""Owner capability access, intake, approved audio and onward sharing."""
import hashlib,secrets,json
import runtime
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Request,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,field_validator
from pathlib import Path
from db import connection,get,record,update,event,uid,now,all_records
from actions import fail,owned
router=APIRouter()

def grant(c,token,allow_expired=False):
    if token.startswith('vault:'):
        from fastapi import HTTPException
        parts=token.removeprefix('vault:').split(':',1)
        if len(parts)!=2 or not all(parts):fail('Invalid saved access',404)
        secret,patient_id=parts
        digest=hashlib.sha256(secret.encode()).hexdigest()
        entries=c.execute('SELECT grant_token FROM saved_pets WHERE vault_hash=? AND expires_at>? UNION SELECT grant_token FROM owner_claims WHERE token_hash=? AND expires_at>?',(digest,now(),digest,now())).fetchall()
        for entry in entries:
            try: current=grant(c,entry[0],allow_expired=True)
            except HTTPException: continue
            if current['patient_id']==patient_id:return current
        fail('Saved access has expired or was revoked',404)
    if token.startswith('saved:'):
        secret=token.removeprefix('saved:')
        saved=c.execute('SELECT * FROM owner_claims WHERE token_hash=? AND expires_at>?',(hashlib.sha256(secret.encode()).hexdigest(),now())).fetchone()
        if not saved:fail('Saved access has expired; open a current clinic link',401)
        return grant(c,saved['grant_token'],allow_expired=True)
    g=c.execute('SELECT * FROM grants WHERE token=? AND revoked=0',(token,)).fetchone()
    if not g or (not allow_expired and g['expires_at']<now()):fail('This link has expired or was revoked',404)
    seen={token};parent=c.execute('SELECT parent_token FROM grant_parents WHERE token=?',(token,)).fetchone()
    while parent:
        if parent[0] in seen:fail('Invalid sharing chain',404)
        seen.add(parent[0]);ancestor=c.execute('SELECT * FROM grants WHERE token=? AND revoked=0',(parent[0],)).fetchone()
        if not ancestor or ancestor['expires_at']<now():fail('The original sharing permission was revoked or expired',404)
        parent=c.execute('SELECT parent_token FROM grant_parents WHERE token=?',(parent[0],)).fetchone()
    return g

def view(c,g):
    from spine.reader import native_records
    patient=owned(c,g['patient_id'],g['clinic_id'],'patient');rs=all_records(c,g['clinic_id'])+native_records(g['clinic_id'],g['patient_id'])
    selected=[r for r in rs if r['data'].get('patient_id')==patient['id']]
    def safe(r):
        r={**r,'data':dict(r['data'])}
        if 'observations' in r['data']:r['data']['observations']=[{k:v for k,v in o.items() if k!='source'} for o in r['data']['observations']]
        return {**r,'data':{k:v for k,v in r['data'].items() if k not in ('path','source_ids','source_id','owner_id','additional_owner_ids','owner_access','fingerprint','edit_key','edit_fingerprint','receipt')}}
    selected.sort(key=lambda r:r['data'].get('occurred_at',r['created_at']),reverse=True)
    return {'patient':safe(patient),'events':[safe(r) for r in selected if r['kind']=='event' and r['data'].get('approved')],
            'medications':[safe(r) for r in selected if r['kind']=='medication'],'reminders':sorted([safe(r) for r in selected if r['kind']=='reminder'],key=lambda r:r['data']['due']),
            'files':[safe(r) for r in selected if r['kind']=='attachment' and r['data'].get('approved')],
            'audio':[safe(r) for r in selected if r['kind']=='recording' and r['data'].get('approved')],
            'intakes':[safe(r) for r in selected if r['kind']=='intake' and r['data'].get('owner_access')==hashlib.sha256(g['token'].encode()).hexdigest()],
            'today':__import__('clinic_workflows').clinic_today(c,g['clinic_id']).date().isoformat(),
            'expires_at':g['expires_at'],'emergency_phone':get(c,'settings-'+g['clinic_id'],g['clinic_id'])['data'].get('emergency_phone','')}

@router.get('/api/owner/{token}')
def owner(token:str):
    with connection() as c:return view(c,grant(c,token))
@router.get('/api/owner/{token}/files/{id}')
def file(token:str,id:str):
    with connection() as c:
        g=grant(c,token);r=owned(c,id,g['clinic_id'],'attachment')
        if r['data']['patient_id']!=g['patient_id'] or not r['data'].get('approved'):fail('File not shared',404)
    return FileResponse(r['data']['path'],media_type=r['data']['mime'],filename=r['data']['name'])
@router.get('/api/owner/{token}/audio/{id}')
def audio(token:str,id:str,request:Request):
    with connection() as c:
        g=grant(c,token);r=owned(c,id,g['clinic_id'],'recording')
        if r['data']['patient_id']!=g['patient_id'] or not r['data'].get('approved'):fail('Recording not shared',404)
        parts=[Path(x[0]).read_bytes() for x in c.execute('SELECT path FROM chunks WHERE recording_id=? ORDER BY chunk_index',(id,))]
    from audio_response import audio_response
    return audio_response(b''.join(parts),r['data'].get('mime','audio/webm'),request.headers.get('range'))
class Intake(BaseModel):
    reason:str=Field(min_length=1,max_length=4000)
    appetite:str=Field(default='',max_length=1000)
    medications:str=Field(default='',max_length=2000)
    questions:str=Field(default='',max_length=2000)
    urgent:bool=False
    key:str=Field(min_length=8,max_length=128)
    @field_validator('reason','appetite','medications','questions')
    @classmethod
    def trim(cls,value,info):
        value=value.strip()
        if info.field_name=='reason' and not value: raise ValueError('Reason for visit is required')
        return value
@router.post('/api/owner/{token}/intake')
def intake(token:str,p:Intake):
    with connection(True) as c:
        g=grant(c,token)
        key=hashlib.sha256((g['token']+p.key).encode()).hexdigest()
        fingerprint=hashlib.sha256(p.model_dump_json(exclude={'key'}).encode()).hexdigest()
        existing=get(c,key,g['clinic_id'])
        if existing:
            if existing['data'].get('fingerprint')!=fingerprint:fail('Submission key was reused with different information',409)
            return {'id':existing['id'],'status':'received'}
        text='\n\n'.join(f'{label}: {value}' for label,value in [('Reason for visit',p.reason),('Appetite / drinking',p.appetite),('Current medication reported by owner',p.medications),('Questions',p.questions)] if value)
        r=record(c,'intake',g['clinic_id'],{'patient_id':g['patient_id'],'text':text,'status':'new','urgent':p.urgent,'fingerprint':fingerprint,'origin':'owner_portal','fields':p.model_dump(exclude={'key'}),'owner_access':hashlib.sha256(g['token'].encode()).hexdigest()},key)
        if p.urgent:
            from test_adapters import escalate
            escalate(c,g['clinic_id'],g['patient_id'],r['id'])
        event(c,g['clinic_id'],g['patient_id'],'owner','Owner submitted pre-consult information',text,[r['id']])
        return {'id':r['id'],'status':'received'}
@router.post('/api/owner/{token}/claim')
@router.post('/api/owner-account/claim/{token}')
def claim(token:str,response:Response,request:Request):
    with connection(True) as c:
        g=grant(c,token);secret=request.cookies.get('broby_owner','')
        known=c.execute('SELECT grant_token,expires_at FROM owner_claims WHERE token_hash=? AND expires_at>?',(hashlib.sha256(secret.encode()).hexdigest(),now())).fetchone() if secret else None
        if not known: secret=secrets.token_urlsafe(32)
        expiry=(datetime.now(timezone.utc)+timedelta(days=90)).isoformat()
        digest=hashlib.sha256(secret.encode()).hexdigest()
        if known:c.execute('INSERT OR IGNORE INTO saved_pets VALUES(?,?,?)',(digest,known['grant_token'],known['expires_at']))
        c.execute('INSERT OR REPLACE INTO owner_claims VALUES(?,?,?)',(digest,g['token'],expiry))
        c.execute('INSERT OR REPLACE INTO saved_pets VALUES(?,?,?)',(digest,g['token'],expiry))
    response.delete_cookie('broby_owner',path='/api/owner-account')
    response.set_cookie('broby_owner',secret,httponly=True,samesite='strict',max_age=90*86400,secure=runtime.hosted(),path='/api/')
    return {'saved':True,'expires_at':expiry}
def saved_grants(c,request):
    from fastapi import HTTPException
    digest=hashlib.sha256(request.cookies.get('broby_owner','').encode()).hexdigest()
    entries=[dict(x) for x in c.execute('SELECT grant_token,expires_at FROM saved_pets WHERE vault_hash=? AND expires_at>? ORDER BY expires_at DESC',(digest,now()))]
    old=c.execute('SELECT grant_token,expires_at FROM owner_claims WHERE token_hash=? AND expires_at>?',(digest,now())).fetchone()
    if old and not any(x['grant_token']==old['grant_token'] for x in entries):entries.append(dict(old))
    valid={}
    for entry in entries:
        try:g=grant(c,entry['grant_token'],allow_expired=True)
        except HTTPException:continue
        if g['patient_id'] not in valid:valid[g['patient_id']]=(g,entry['expires_at'])
    if not valid:fail('Open a valid clinic link to save access on this device',404 if entries else 401)
    return valid

def saved_grant(c,request,patient_id=None):
    entries=saved_grants(c,request)
    if patient_id and patient_id not in entries:fail('Pet is not saved on this device',404)
    return entries[patient_id] if patient_id else next(iter(entries.values()))

@router.get('/api/owner-account')
@router.get('/api/owner-account/pets/{patient_id}')
def account(request:Request,patient_id:str|None=None):
    with connection() as c:
        entries=saved_grants(c,request);g,expiry=saved_grant(c,request,patient_id)
        result=view(c,g);result['expires_at']=expiry;result['saved_access']=True
        result['pets']=[{'id':pid,'name':owned(c,pid,item[0]['clinic_id'],'patient')['data']['name']} for pid,item in entries.items()]
        return result

@router.post('/api/owner/{token}/share')
def share(token:str):
    with connection(True) as c:
        g=grant(c,token);secret=secrets.token_urlsafe(32)
        expiry=min(g['expires_at'],(datetime.now(timezone.utc)+timedelta(days=7)).isoformat())
        c.execute('INSERT INTO grants VALUES(?,?,?,?,0)',(secret,g['clinic_id'],g['patient_id'],expiry))
        c.execute('INSERT INTO grant_parents VALUES(?,?)',(secret,g['token']))
        return {'url':'/owner?token='+secret,'expires_at':expiry}
class Question(BaseModel):message:str=Field(min_length=1,max_length=2000)
@router.post('/api/owner/{token}/help')
def help_owner(token:str,p:Question):
    with connection() as c:
        g=grant(c,token);data=view(c,g);text=p.message.lower()
        if any(x in text for x in ('med','dose','tablet')):
            answer='\n'.join(f"{m['data']['name']}: {m['data']['dose']} · {m['data']['frequency']}. {m['data']['instructions']}" for m in data['medications']) or 'No prescribed medication instructions are shared. Contact the clinic before changing medication.'
        elif any(x in text for x in ('due','appointment','vaccine','reminder')):
            answer='\n'.join(f"{r['data']['title']} — {r['data']['due']}" for r in data['reminders'] if r['data']['status']=='due') or 'No care reminders are currently shared.'
        else:answer='I can show the clinic’s saved medication instructions and care reminders. I cannot assess symptoms or decide whether it is safe to wait. Submit the pre-consult form for the clinic to review.'
        return {'text':answer,'emergency_phone':data['emergency_phone'],'notice':'For urgent concerns, contact the clinic or an emergency veterinary service directly. This portal is not monitored continuously.'}

# Saved access resolves only explicitly claimed, independently revocable grants.
def saved_token(request,patient_id=None):
    with connection() as c:
        g,_=saved_grant(c,request,patient_id)
        return 'vault:'+request.cookies.get('broby_owner','')+':'+g['patient_id']

@router.get('/api/owner-account/files/{id}')
@router.get('/api/owner-account/pets/{patient_id}/files/{id}')
def account_file(id:str,request:Request,patient_id:str|None=None):return file(saved_token(request,patient_id),id)
@router.get('/api/owner-account/audio/{id}')
@router.get('/api/owner-account/pets/{patient_id}/audio/{id}')
def account_audio(id:str,request:Request,patient_id:str|None=None):return audio(saved_token(request,patient_id),id,request)
@router.post('/api/owner-account/intake')
@router.post('/api/owner-account/pets/{patient_id}/intake')
def account_intake(p:Intake,request:Request,patient_id:str|None=None):return intake(saved_token(request,patient_id),p)
@router.post('/api/owner-account/help')
@router.post('/api/owner-account/pets/{patient_id}/help')
def account_help(p:Question,request:Request,patient_id:str|None=None):return help_owner(saved_token(request,patient_id),p)

class IntakeEdit(Intake):
    version:int=Field(ge=1)

@router.put('/api/owner/{token}/intake/{id}')
def edit_intake(token:str,id:str,p:IntakeEdit):
    from actions import version
    with connection(True) as c:
        g=grant(c,token);r=owned(c,id,g['clinic_id'],'intake')
        if r['data']['patient_id']!=g['patient_id'] or r['data'].get('owner_access')!=hashlib.sha256(g['token'].encode()).hexdigest():fail('Submission not found',404)
        fingerprint=hashlib.sha256(p.model_dump_json(exclude={'key','version'}).encode()).hexdigest()
        if r['data'].get('edit_key')==p.key:
            if r['data'].get('edit_fingerprint')!=fingerprint:fail('Submission key was reused with different information',409)
            return {'id':id,'status':r['data']['status']}
        version(r,p.model_dump())
        if r['data']['status']!='new':fail('The clinic has already handled this submission; send an update instead',409)
        text='\n\n'.join(f'{label}: {value}' for label,value in [('Reason for visit',p.reason),('Appetite / drinking',p.appetite),('Current medication reported by owner',p.medications),('Questions',p.questions)] if value)
        update(c,r,{**r['data'],'text':text,'fields':p.model_dump(exclude={'key','version'}),'urgent':p.urgent,'edit_key':p.key,'edit_fingerprint':fingerprint})
        event(c,g['clinic_id'],g['patient_id'],'owner','Owner updated pre-consult information',text,[id])
        return {'id':id,'status':'new'}

@router.put('/api/owner-account/intake/{id}')
@router.put('/api/owner-account/pets/{patient_id}/intake/{id}')
def account_edit_intake(id:str,p:IntakeEdit,request:Request,patient_id:str|None=None):return edit_intake(saved_token(request,patient_id),id,p)

@router.get('/api/owner/{token}/discharge.pdf')
def discharge_pdf(token:str):
    from exports import discharge_document
    with connection() as c:
        g=grant(c,token);data=view(c,g);practice=get(c,g['clinic_id'],g['clinic_id'])
        content=discharge_document(practice,data)
    return Response(content,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="care-instructions.pdf"'})

@router.get('/api/owner-account/discharge.pdf')
@router.get('/api/owner-account/pets/{patient_id}/discharge.pdf')
def account_discharge(request:Request,patient_id:str|None=None):return discharge_pdf(saved_token(request,patient_id))
