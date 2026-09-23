import json,io,zipfile,hashlib
from pathlib import Path
from fastapi import APIRouter,Request,Response,Query
from pydantic import BaseModel,Field
from db import connection,get,all_records,now,unpack
from actions import owned,fail,PERMISSIONS,allowed_actions
import auth,providers,reads,runtime
router=APIRouter()
def identity(request):
    from main import identity as resolve
    return resolve(request)
@router.get('/api/session')
def session(request:Request):
    sess=auth.session(request) if auth.enabled() else None
    return {'mode':'password' if auth.enabled() else 'demo','authenticated':bool(sess) if auth.enabled() else True,'username':sess['username'] if sess else None}
class Login(BaseModel):
    username:str=Field(min_length=1,max_length=200)
    password:str=Field(min_length=1,max_length=1000)
    code:str=Field(default='',max_length=10)
@router.post('/api/login')
def login(p:Login,request:Request,response:Response):
    token=auth.login(p.username,p.password,request.client.host if request.client else 'local',p.code)
    response.set_cookie('broby_session',token,httponly=True,samesite='strict',max_age=12*3600,secure=runtime.hosted() or request.url.scheme=='https',path='/')
    with connection() as c:
        m=c.execute('SELECT clinic_id,member_id FROM auth_memberships WHERE username=? ORDER BY clinic_id',(p.username,)).fetchone()
    return {'authenticated':True,'clinic':m['clinic_id'],'actor':m['member_id']}
@router.post('/api/logout')
def logout(request:Request,response:Response):
    with connection(True) as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(auth.digest(request.cookies.get('broby_session','')),))
    response.delete_cookie('broby_session',path='/');return {'ok':True}
@router.get('/api/ontology')
def ontology(request:Request):
    from ontology_workflow import definitions
    clinic,_=identity(request)
    with connection() as c:return definitions(c,clinic)
@router.get('/api/handover')
def handover(request:Request):
    clinic,_=identity(request)
    with connection() as c:return reads.handover(c,clinic)
@router.get('/api/patients')
def patients(request:Request,q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    clinic,_=identity(request)
    with connection() as c:
        rs=[r for r in all_records(c,clinic,'patient') if q.lower() in (r['data']['name']+' '+r['data'].get('external_id','')).lower()]
    return {'items':rs[offset:offset+limit],'total':len(rs)}
@router.get('/api/patients/{id}/timeline')
def timeline(id:str,request:Request,category:str='',q:str='',start:str='',end:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    clinic,_=identity(request)
    with connection() as c:rs=reads.patient_records(c,clinic,id,'event',category,start,end,q)
    return {'items':rs[offset:offset+limit],'total':len(rs)}
@router.get('/api/patients/{id}/observations')
def observations(id:str,request:Request):
    clinic,_=identity(request)
    with connection() as c:return reads.patient_records(c,clinic,id,'observation')
@router.get('/api/records/{id}/history')
def history(id:str,request:Request):
    clinic,_=identity(request)
    with connection() as c:
        r=owned(c,id,clinic)
        previous=[unpack(x) for x in c.execute('SELECT * FROM record_versions WHERE record_id=? AND clinic_id=? ORDER BY version DESC',(id,clinic))]
        return {'current':r,'versions':previous}
@router.get('/api/actions/catalog')
def catalog(request:Request):
    clinic,actor=identity(request)
    with connection() as c:
        member=owned(c,actor,clinic,'member');locked=get(c,clinic,clinic)['data'].get('locked_features',[])
        return [{'name':a,'allowed':a in allowed_actions(c,clinic,actor)} for a in PERMISSIONS]
@router.get('/api/backup')
def backup(request:Request):
    clinic,actor=identity(request)
    with connection() as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin':fail('Administrator access required',403)
        rs=all_records(c,clinic);versions=[dict(r) for r in c.execute('SELECT * FROM record_versions WHERE clinic_id=?',(clinic,))]
        chunks=[dict(r) for r in c.execute('SELECT chunks.* FROM chunks JOIN records ON records.id=chunks.recording_id WHERE records.clinic_id=?',(clinic,))]
        output=io.BytesIO();manifest={'version':1,'clinic_id':clinic,'created_at':now(),'records':rs,'history':versions,'ontology':[dict(r) for r in c.execute('SELECT * FROM ontology')],'audit':[dict(r) for r in c.execute('SELECT * FROM audit WHERE clinic_id=?',(clinic,))],'chunks':[],'files':[]}
        from spine.reader import clinical_archive
        spine=clinical_archive(clinic)
        manifest['spine_archive']='spine.json'
        manifest['native_event_count']=sum(e['payload_hash']!='legacy' for e in spine.get('events',[]))
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('spine.json',json.dumps({'clinic_id':clinic,'tables':spine},ensure_ascii=False,indent=2,default=str))
            for r in rs:
                if r['kind']=='attachment':
                    path=Path(r['data']['path']);target='files/'+r['id'];content=path.read_bytes();z.writestr(target,content)
                    r['data']['path']=target;manifest['files'].append({'path':target,'sha256':hashlib.sha256(content).hexdigest()})
            for ch in chunks:
                target=f"audio/{ch['recording_id']}/{ch['chunk_index']}";content=Path(ch['path']).read_bytes();z.writestr(target,content)
                manifest['chunks'].append({**ch,'path':target});manifest['files'].append({'path':target,'sha256':hashlib.sha256(content).hexdigest()})
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="broby-clinic-backup.zip"'})

@router.get('/api/dashboards/{id}')
def saved_dashboard(id:str,request:Request):
    from advanced_workflows import dashboard
    clinic,_=identity(request)
    with connection() as c:
        r=owned(c,id,clinic,'dashboard')
        if r['data'].get('archived'):fail('View was deleted',404)
        return {**r,'result':dashboard(c,clinic,r['data']['query'])}

@router.get('/api/operations/status')
def operation_status(request:Request):
    clinic,actor=identity(request)
    with connection() as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin':fail('Administrator access required',403)
        jobs=[dict(r) for r in c.execute('SELECT j.id,j.status,q.attempts,q.lease_until,q.next_attempt FROM jobs j LEFT JOIN job_claims q ON q.job_id=j.id WHERE j.clinic_id=? ORDER BY j.created_at DESC LIMIT 50',(clinic,))]
        from stripe_payments import configured
        return {'sending_enabled':False,'payment_mode':'stripe_test' if configured(clinic) else 'simulation','lab_mode':'synthetic','jobs':jobs,'pending_escalations':sum(r['data']['status']=='needs_attention' for r in all_records(c,clinic,'escalation'))}

@router.get('/api/organization')
def organization(request:Request):
    from organizations import policy,master
    clinic,actor=identity(request)
    with connection() as c:
        org=policy(c,clinic)
        if not org:return None
        result={'id':org['id'],'name':org['name'],'master':master(c,org,actor),'locked_actions':json.loads(org['locked_actions'])}
        if result['master']:
            result['clinics']=[{'id':r[0],'name':get(c,r[0],r[0])['data']['name']} for r in c.execute('SELECT clinic_id FROM organization_clinics WHERE organization_id=?',(org['id'],))]
        return result
