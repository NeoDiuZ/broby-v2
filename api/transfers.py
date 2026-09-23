"""Owner-consented transfers to authenticated receiving clinics, with revocable requests."""
import hashlib,secrets,json
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Request
from pydantic import BaseModel,Field
from db import connection,get,record,update,all_records,now,uid
from actions import fail,owned
router=APIRouter()
PERMISSIONS={'transfer.accept':{'vet','admin'}}

def setup(c):
    c.execute('CREATE TABLE IF NOT EXISTS transferred_patients(source_clinic TEXT,source_patient TEXT,target_clinic TEXT,target_patient TEXT,PRIMARY KEY(source_clinic,source_patient,target_clinic))')
    c.execute('CREATE TABLE IF NOT EXISTS transfer_requests(id TEXT PRIMARY KEY,source_clinic TEXT,target_clinic TEXT,patient_id TEXT,grant_token TEXT,status TEXT,expires_at TEXT,result TEXT)')
class Consent(BaseModel):
    target_clinic:str=Field(min_length=1,max_length=200)
    consent:bool

@router.get('/api/owner/{token}/transfer-clinics')
def clinics(token:str):
    from portal import grant
    with connection() as c:
        g=grant(c,token)
        return [{'id':r['id'],'name':r['data']['name']} for r in [__import__('db').unpack(row) for row in c.execute("SELECT * FROM records WHERE kind='clinic'")] if r['id']!=g['clinic_id']]

@router.post('/api/owner/{token}/transfers')
def request_transfer(token:str,p:Consent):
    from portal import grant
    if not p.consent:fail('Explicit sharing consent is required')
    with connection(True) as c:
        g=grant(c,token);owned(c,p.target_clinic,p.target_clinic,'clinic')
        if p.target_clinic==g['clinic_id']:fail('Choose a different clinic')
        existing=c.execute("SELECT * FROM transfer_requests WHERE grant_token=? AND target_clinic=? AND status='pending' AND expires_at>?",(g['token'],p.target_clinic,now())).fetchone()
        if existing:return {'id':existing['id'],'status':'pending','expires_at':existing['expires_at']}
        id=uid();expiry=min(g['expires_at'],(datetime.now(timezone.utc)+timedelta(days=7)).isoformat())
        c.execute('INSERT INTO transfer_requests VALUES(?,?,?,?,?,?,?,NULL)',(id,g['clinic_id'],p.target_clinic,g['patient_id'],g['token'],'pending',expiry))
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),g['clinic_id'],'owner-grant','transfer.consented',id,now()))
        return {'id':id,'status':'pending','expires_at':expiry}

@router.delete('/api/owner/{token}/transfers/{id}')
def revoke_transfer(token:str,id:str):
    from portal import grant
    with connection(True) as c:
        g=grant(c,token);r=c.execute('SELECT * FROM transfer_requests WHERE id=? AND grant_token=?',(id,g['token'])).fetchone()
        if not r:fail('Transfer not found',404)
        if r['status']=='accepted':fail('The receiving clinic already imported its copy; contact that clinic about its medical records',409)
        c.execute("UPDATE transfer_requests SET status='revoked' WHERE id=?",(id,))
    return {'revoked':True}

@router.get('/api/transfers/incoming')
def incoming(request:Request):
    from main import identity
    from portal import grant
    from fastapi import HTTPException
    clinic,actor=identity(request)
    with connection() as c:
        from actions import authorize
        authorize(c,clinic,actor,'transfer.accept')
        results=[]
        for r in c.execute("SELECT * FROM transfer_requests WHERE target_clinic=? AND status='pending' AND expires_at>?",(clinic,now())):
            try:grant(c,r['grant_token'])
            except HTTPException:continue
            results.append({'id':r['id'],'patient_name':owned(c,r['patient_id'],r['source_clinic'],'patient')['data']['name'],'source_clinic':owned(c,r['source_clinic'],r['source_clinic'],'clinic')['data']['name'],'expires_at':r['expires_at']})
        return results

def dispatch(c,a,p,clinic,actor):
    from portal import grant,view
    from actions import require
    r=c.execute('SELECT * FROM transfer_requests WHERE id=? AND target_clinic=?',(require(p,'id'),clinic)).fetchone()
    if not r:fail('Transfer request not found',404)
    if r['status']=='accepted':return json.loads(r['result'])
    if r['status']!='pending' or r['expires_at']<now():fail('Transfer request expired or revoked',409)
    g=grant(c,r['grant_token']);data=view(c,g)
    if len(data['files'])>25 or sum(f['data']['size'] for f in data['files'])>100*1024*1024:fail('Transfer exceeds 25 files or 100 MB; arrange a reviewed archive transfer')
    source_patient=owned(c,r['patient_id'],r['source_clinic'],'patient')
    owner=owned(c,source_patient['data']['owner_id'],r['source_clinic'],'owner')
    previous=c.execute('SELECT target_patient FROM transferred_patients WHERE source_clinic=? AND source_patient=? AND target_clinic=?',(r['source_clinic'],source_patient['id'],clinic)).fetchone()
    if previous:fail('This source patient was already transferred. Reconcile further updates with the receiving clinic; no duplicate patient was created.',409)
    new_owner=record(c,'owner',clinic,{k:owner['data'].get(k,'') for k in ('name','phone','email')})
    patient=record(c,'patient',clinic,{**{k:v for k,v in source_patient['data'].items() if k not in ('owner_id','additional_owner_ids','external_id')},'owner_id':new_owner['id'],'external_id':'transfer:'+r['source_clinic']+':'+source_patient['id'],'transfer_request_id':r['id']})
    c.execute('INSERT INTO transferred_patients VALUES(?,?,?,?)',(r['source_clinic'],source_patient['id'],clinic,patient['id']))
    for e in data['events']:
        d=e['data'];text=d['body']
        for o in d.get('observations',[]):text+='\n'+f"{o['name']}: {o['value']} {o['unit']} (supplied range {o['ref_low']}–{o['ref_high']})"
        source=record(c,'source',clinic,{'patient_id':patient['id'],'title':'Transferred approved record','text':text,'section':'Objective','category':d['category'],'author':'Consented transfer from '+r['source_clinic'],'origin_event_id':e['id'],'origin_patient_id':source_patient['id'],'origin_clinic_id':r['source_clinic']})
        record(c,'event',clinic,{'patient_id':patient['id'],'category':d['category'],'title':d['title'],'body':text,'source_ids':[source['id']],'occurred_at':d['occurred_at'],'approved':False,'transfer_request_id':r['id']})
        for o in d.get('observations',[]):record(c,'observation',clinic,{'patient_id':patient['id'],'code':o['concept'],'name':o['name'],'value':o['value'],'value_type':o['value_type'],'unit':o['unit'],'low':o['ref_low'],'high':o['ref_high'],'source_id':source['id'],'category':d['category'],'observed_at':d['occurred_at']})
    # Copy approved media into the receiving clinic's own records. Source permissions
    # can be withdrawn before acceptance; an accepted medical copy is independent.
    from pathlib import Path
    import db
    copied=[]
    for media in data['files']:
        original=owned(c,media['id'],r['source_clinic'],'attachment');content=Path(original['data']['path']).read_bytes()
        if hashlib.sha256(content).hexdigest()!=original['data']['sha256']:fail('Transferred file checksum mismatch',409)
        fid=uid();path=db.DATA/'files'/fid;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        attachment=record(c,'attachment',clinic,{**original['data'],'patient_id':patient['id'],'consultation_id':'','approved':False,'path':str(path),'transfer_request_id':r['id'],'origin_id':media['id']},fid)
        copied.append(attachment['id'])
    result={'id':patient['id'],'transferred_events':len(data['events']),'transfer_id':r['id'],'files_copied':len(copied)}
    c.execute("UPDATE transfer_requests SET status='accepted',result=? WHERE id=?",(json.dumps(result),r['id']))
    return result

@router.get('/api/owner-account/transfer-clinics')
@router.get('/api/owner-account/pets/{patient_id}/transfer-clinics')
def account_clinics(request:Request,patient_id:str|None=None):
    from portal import saved_token
    return clinics(saved_token(request,patient_id))
@router.post('/api/owner-account/transfers')
@router.post('/api/owner-account/pets/{patient_id}/transfers')
def account_transfer(p:Consent,request:Request,patient_id:str|None=None):
    from portal import saved_token
    return request_transfer(saved_token(request,patient_id),p)
@router.delete('/api/owner-account/transfers/{id}')
@router.delete('/api/owner-account/pets/{patient_id}/transfers/{id}')
def account_revoke(id:str,request:Request,patient_id:str|None=None):
    from portal import saved_token
    return revoke_transfer(saved_token(request,patient_id),id)
