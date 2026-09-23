from datetime import date
from fastapi import APIRouter,Request,Query,HTTPException
from sqlalchemy import select
from . import database,service,projection
from .models import Event,Source
from .contracts import LabInput,EventInput
router=APIRouter(prefix='/api/v2',tags=['Patient spine'])

@router.get('/overview')
def overview(request:Request,days:int=Query(30,ge=1,le=366)):
    from datetime import datetime,timezone,timedelta
    from sqlalchemy import func,or_
    from .models import Patient,Observation,Concept
    from .categories import canonical
    clinic,_=identity(request)
    since=datetime.now(timezone.utc)-timedelta(days=days)
    with database.session() as s:
        groups=s.execute(select(Event.event_type,func.count()).where(Event.clinic_id==clinic,Event.occurred_at>=since).group_by(Event.event_type)).all()
        counts={}
        for category,count in groups:
            name=canonical(category);counts[name]=counts.get(name,0)+count
        flagged=s.execute(select(Observation,Concept,Event,Patient).join(Concept,Observation.concept_id==Concept.id).join(Event,Observation.event_id==Event.id).join(Patient,Event.patient_id==Patient.id).where(Event.clinic_id==clinic,Observation.observed_at>=since,or_(Observation.value<Observation.ref_low,Observation.value>Observation.ref_high)).order_by(Observation.observed_at.desc()).limit(50)).all()
        return {'days':days,'since':service.utc(since),'categories':[{'name':k,'count':v} for k,v in sorted(counts.items())],
                'patient_count':s.scalar(select(func.count()).select_from(Patient).where(Patient.clinic_id==clinic)),
                'event_count':sum(counts.values()),'flagged_limit':50,
                'flagged':[{'patient_id':p.id,'patient_name':p.name,'event_id':e.id,'name':t.name,'value':o.value,'unit':t.unit,'ref_low':o.ref_low,'ref_high':o.ref_high,'flag':service.flag(o),'source':service.source(s,o.source_id)} for o,t,e,p in flagged]}
def identity(request):
    from main import identity
    clinic,actor=identity(request)
    projection.sync(clinic)
    return clinic,actor

def can_write(clinic,actor):
    import db
    from actions import owned,fail,PERMISSIONS
    with db.connection() as c:
        member=owned(c,actor,clinic,'member');practice=owned(c,clinic,clinic,'clinic')
        if not member['data'].get('active') or member['data']['role'] not in PERMISSIONS['source.add']:fail('Capture permission required',403)
        if 'source.add' in practice['data'].get('locked_features',[]) and member['data']['role']!='admin':fail('Capture is locked by the administrator',403)
@router.get('/patients')
def patients(request:Request,q:str=Query('',max_length=200),limit:int=Query(50,ge=1,le=200),cursor:str=''):
    clinic,_=identity(request)
    with database.session() as s:return service.patients(s,clinic,q,limit,cursor)
@router.get('/patients/{id}')
def patient(id:str,request:Request):
    clinic,_=identity(request)
    with database.session() as s:return service.patient_view(s,service.patient(s,id,clinic))
@router.get('/patients/{id}/timeline')
def timeline(id:str,request:Request,limit:int=Query(25,ge=1,le=200),cursor:str='',category:str='',q:str='',start:date|None=None,end:date|None=None):
    clinic,_=identity(request)
    if start and end and start>end:raise HTTPException(422,'Start must not follow end')
    with database.session() as s:return service.timeline(s,clinic,id,limit,cursor,category,q,start,end)
@router.get('/patients/{id}/concepts')
def concepts(id:str,request:Request):
    clinic,_=identity(request)
    with database.session() as s:return service.concepts(s,clinic,id)
@router.get('/patients/{id}/observations')
def observations(id:str,request:Request,concept:str):
    clinic,_=identity(request)
    with database.session() as s:return service.series(s,clinic,id,concept)
@router.get('/patients/{id}/events/{event_id}')
def event(id:str,event_id:str,request:Request):
    clinic,_=identity(request)
    with database.session() as s:
        service.patient(s,id,clinic);e=s.get(Event,event_id)
        if not e or e.clinic_id!=clinic or e.patient_id!=id:raise HTTPException(404,'Event not found')
        return service.event_view(s,e)
@router.get('/sources/{id}')
def source(id:str,request:Request):
    clinic,_=identity(request)
    with database.session() as s:
        r=s.get(Source,id)
        if not r or r.clinic_id!=clinic:raise HTTPException(404,'Source not found')
        content_url=None
        import db
        with db.connection() as c:
            old=db.get(c,r.reference_id,clinic)
            if old and old['data'].get('patient_id')==r.patient_id:
                if r.kind=='document' and old['kind']=='attachment':content_url='/api/files/'+old['id']
                elif r.kind=='audio' and old['kind']=='recording':content_url='/api/recordings/'+old['id']+'/audio'
        return {**service.source(s,id),'text':r.content.get('text',''),'title':r.content.get('title',r.reference_id),'content_url':content_url}
@router.post('/ingest/lab')
def lab(payload:LabInput,request:Request):
    clinic,actor=identity(request);can_write(clinic,actor)
    if not payload.observations:raise HTTPException(422,'Lab results require at least one measurement')
    with database.session() as s,s.begin():return service.ingest(s,clinic,payload)
@router.post('/events')
def write_event(payload:EventInput,request:Request):
    clinic,actor=identity(request);can_write(clinic,actor)
    with database.session() as s,s.begin():return service.ingest(s,clinic,payload,payload.event_type)
