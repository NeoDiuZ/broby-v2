"""Owner capability access, intake, approved audio and onward sharing."""
import hashlib,secrets,json
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Request,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from pathlib import Path
from db import connection,get,record,update,event,uid,now,all_records
from actions import fail,owned
router=APIRouter()

def grant(c,token,allow_expired=False):
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
    patient=owned(c,g['patient_id'],g['clinic_id'],'patient');rs=all_records(c,g['clinic_id'])
    selected=[r for r in rs if r['data'].get('patient_id')==patient['id']]
    def safe(r):return {**r,'data':{k:v for k,v in r['data'].items() if k not in ('path','source_ids','source_id','owner_id')}}
    return {'patient':safe(patient),'events':[safe(r) for r in selected if r['kind']=='event' and r['data'].get('approved')],
            'medications':[safe(r) for r in selected if r['kind']=='medication'],'reminders':[safe(r) for r in selected if r['kind']=='reminder'],
            'files':[safe(r) for r in selected if r['kind']=='attachment' and r['data'].get('approved')],
            'audio':[safe(r) for r in selected if r['kind']=='recording' and r['data'].get('approved')],
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
def audio(token:str,id:str):
    with connection() as c:
        g=grant(c,token);r=owned(c,id,g['clinic_id'],'recording')
        if r['data']['patient_id']!=g['patient_id'] or not r['data'].get('approved'):fail('Recording not shared',404)
        parts=[Path(x[0]).read_bytes() for x in c.execute('SELECT path FROM chunks WHERE recording_id=? ORDER BY chunk_index',(id,))]
    return Response(b''.join(parts),media_type=r['data'].get('mime','audio/webm'))
class Intake(BaseModel):
    reason:str=Field(min_length=1,max_length=4000)
    appetite:str=Field(default='',max_length=1000)
    medications:str=Field(default='',max_length=2000)
    questions:str=Field(default='',max_length=2000)
    urgent:bool=False
    key:str=Field(min_length=8,max_length=128)
@router.post('/api/owner/{token}/intake')
def intake(token:str,p:Intake):
    with connection(True) as c:
        g=grant(c,token)
        key=hashlib.sha256((token+p.key).encode()).hexdigest()
        fingerprint=hashlib.sha256(p.model_dump_json(exclude={'key'}).encode()).hexdigest()
        existing=get(c,key,g['clinic_id'])
        if existing:
            if existing['data'].get('fingerprint')!=fingerprint:fail('Submission key was reused with different information',409)
            return {'id':existing['id'],'status':'received'}
        text='\n\n'.join(f'{label}: {value}' for label,value in [('Reason for visit',p.reason),('Appetite / drinking',p.appetite),('Current medication reported by owner',p.medications),('Questions',p.questions)] if value)
        r=record(c,'intake',g['clinic_id'],{'patient_id':g['patient_id'],'text':text,'status':'new','urgent':p.urgent,'fingerprint':fingerprint,'origin':'owner_portal'},key)
        event(c,g['clinic_id'],g['patient_id'],'owner','Owner submitted pre-consult information',text,[r['id']])
        return {'id':r['id'],'status':'received'}
@router.post('/api/owner/{token}/claim')
def claim(token:str,response:Response):
    with connection(True) as c:
        g=grant(c,token);secret=secrets.token_urlsafe(32);expiry=(datetime.now(timezone.utc)+timedelta(days=90)).isoformat()
        c.execute('INSERT INTO owner_claims VALUES(?,?,?)',(hashlib.sha256(secret.encode()).hexdigest(),token,expiry))
    response.set_cookie('broby_owner',secret,httponly=True,samesite='strict',max_age=90*86400,secure=False,path='/api/owner-account')
    return {'saved':True,'expires_at':expiry}
@router.get('/api/owner-account')
def account(request:Request):
    with connection() as c:
        h=hashlib.sha256(request.cookies.get('broby_owner','').encode()).hexdigest()
        saved=c.execute('SELECT * FROM owner_claims WHERE token_hash=? AND expires_at>?',(h,now())).fetchone()
        if not saved:fail('Open a valid clinic link to save access on this device',401)
        g=grant(c,saved['grant_token'],allow_expired=True)
        result=view(c,g);result['expires_at']=saved['expires_at'];result['saved_access']=True
        # This endpoint returns approved records only, never the raw clinic grant.
        return result
@router.post('/api/owner/{token}/share')
def share(token:str):
    with connection(True) as c:
        g=grant(c,token);secret=secrets.token_urlsafe(32)
        expiry=min(g['expires_at'],(datetime.now(timezone.utc)+timedelta(days=7)).isoformat())
        c.execute('INSERT INTO grants VALUES(?,?,?,?,0)',(secret,g['clinic_id'],g['patient_id'],expiry))
        c.execute('INSERT INTO grant_parents VALUES(?,?)',(secret,token))
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

# Cookie-authenticated vault routes keep approved media and intake available after
# the initial short-lived link expires. Revoking the root grant still revokes access.
@router.get('/api/owner-account/files/{id}')
def account_file(id:str,request:Request):return file('saved:'+request.cookies.get('broby_owner',''),id)
@router.get('/api/owner-account/audio/{id}')
def account_audio(id:str,request:Request):return audio('saved:'+request.cookies.get('broby_owner',''),id)
@router.post('/api/owner-account/intake')
def account_intake(p:Intake,request:Request):return intake('saved:'+request.cookies.get('broby_owner',''),p)
@router.post('/api/owner-account/help')
def account_help(p:Question,request:Request):return help_owner('saved:'+request.cookies.get('broby_owner',''),p)
