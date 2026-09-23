"""Deterministic PostgreSQL ingestion and contract-shaped reads."""
import base64,hashlib,json,uuid
from datetime import datetime,timezone
from sqlalchemy import select,or_,and_,func
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from .models import Patient,Owner,OwnerPatient,Event,Source,Concept,Observation

def fail(message,status=422):raise HTTPException(status,message)
def utc(value):return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def patient(s,id,clinic):
    p=s.get(Patient,id)
    if not p or p.clinic_id!=clinic:fail('Patient not found',404)
    return p

def source(s,source_id):
    r=s.get(Source,source_id) if source_id else None
    if not r:return None
    return {'kind':r.kind,'id':r.reference_id,'receipt_id':r.id,**{k:getattr(r,k) for k in ('page','start_ms','end_ms') if getattr(r,k) is not None}}
def flag(o):
    if o.ref_low is not None and o.value<o.ref_low:return 'low'
    if o.ref_high is not None and o.value>o.ref_high:return 'high'
    return None

def event_view(s,e):
    obs=s.scalars(select(Observation).where(Observation.event_id==e.id).order_by(Observation.id)).all()
    flags=[] if e.source_id else [{'type':'missing_source'}]
    values=[]
    for o in obs:
        term=s.get(Concept,o.concept_id);f=flag(o)
        if f:flags.append({'type':'out_of_range','observation_id':o.id})
        if not o.source_id:flags.append({'type':'missing_source','observation_id':o.id})
        values.append({'id':o.id,'concept':term.code,'name':term.name,'value':o.value,'unit':term.unit,'ref_low':o.ref_low,'ref_high':o.ref_high,'flag':f,'source':source(s,o.source_id)})
    return {'id':e.id,'event_type':e.event_type,'occurred_at':utc(e.occurred_at),'summary':e.summary,'actor':e.actor,'source':source(s,e.source_id),'body':e.body,'flags':flags,'observations':values}

def add_source(s,clinic,pid,value,id=None):
    if value is None:return None
    r=Source(id=id or str(uuid.uuid4()),clinic_id=clinic,patient_id=pid,kind=value.kind,reference_id=value.id,page=value.page,start_ms=value.start_ms,end_ms=value.end_ms,content={'text':value.text})
    s.add(r);s.flush();return r.id

def ingest(s,clinic,p,event_type='lab_result'):
    patient(s,p.patient_id,clinic)
    payload={'event_type':event_type,**p.model_dump(mode='json')};fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    # Unique constraint plus ON CONFLICT makes dedupe safe across actors/processes.
    eid=str(uuid.uuid4())
    result=s.execute(insert(Event).values(id=eid,clinic_id=clinic,patient_id=p.patient_id,event_type=event_type,occurred_at=p.occurred_at,summary=p.summary,actor=p.actor.model_dump(),body=p.body,dedupe_key=p.dedupe_key,payload_hash=fingerprint).on_conflict_do_nothing(index_elements=['clinic_id','dedupe_key']).returning(Event.id)).scalar_one_or_none()
    if result is None:
        e=s.scalar(select(Event).where(Event.clinic_id==clinic,Event.dedupe_key==p.dedupe_key))
        if e.payload_hash!=fingerprint:fail('Dedupe key was reused with changed content',409)
        return {'id':e.id,'event':event_view(s,e),'duplicate':True}
    e=s.get(Event,eid);e.source_id=add_source(s,clinic,p.patient_id,p.source)
    for m in p.observations:
        cid=str(uuid.uuid5(uuid.NAMESPACE_URL,'broby:concept:'+m.concept+':'+m.unit))
        s.execute(insert(Concept).values(id=cid,code=m.concept,name=m.name,unit=m.unit).on_conflict_do_nothing(index_elements=['code','unit']))
        existing=s.get(Concept,cid)
        if existing.name!=m.name:fail('Concept name conflicts with its existing definition',409)
        sid=add_source(s,clinic,p.patient_id,m.source) if m.source else e.source_id
        s.add(Observation(id=str(uuid.uuid4()),event_id=eid,concept_id=cid,observed_at=p.occurred_at,value=m.value,ref_low=m.ref_low,ref_high=m.ref_high,source_id=sid))
    s.flush();return {'id':eid,'event':event_view(s,e),'duplicate':False}

def cursor_encode(scope,values):return base64.urlsafe_b64encode(json.dumps({'scope':scope,'values':values}).encode()).decode()
def cursor_decode(token,scope):
    if not token:return None
    try:
        d=json.loads(base64.urlsafe_b64decode(token));v=d['values']
        if d['scope']!=scope or not isinstance(v,list) or len(v)!=2 or not all(isinstance(x,str) for x in v):raise ValueError()
        return v
    except Exception:fail('Invalid cursor')
def patient_view(s,p):
    owner=s.scalar(select(Owner).join(OwnerPatient,Owner.id==OwnerPatient.owner_id).where(OwnerPatient.patient_id==p.id).order_by(Owner.id))
    last=s.scalar(select(func.max(Event.occurred_at)).where(Event.patient_id==p.id,Event.event_type=='consult'))
    return {'id':p.id,'name':p.name,'species':p.species,'breed':p.breed,'sex':p.sex,'date_of_birth':p.date_of_birth.isoformat() if p.date_of_birth else None,'owner':{'id':owner.id,'name':owner.name} if owner else None,'last_seen':utc(last) if last else None,'stats':{'visits':s.scalar(select(func.count()).select_from(Event).where(Event.patient_id==p.id,Event.event_type=='consult')),'observations':s.scalar(select(func.count()).select_from(Observation).join(Event).where(Event.patient_id==p.id)),'document_sources':s.scalar(select(func.count()).select_from(Source).where(Source.patient_id==p.id,Source.kind=='document'))}}
def patients(s,clinic,q,limit,cursor):
    scope='patients:'+clinic+':'+q;after=cursor_decode(cursor,scope)
    query=select(Patient).where(Patient.clinic_id==clinic)
    if q:
        text='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        owner_ids=select(OwnerPatient.patient_id).join(Owner,OwnerPatient.owner_id==Owner.id).where(Owner.clinic_id==clinic,Owner.name.ilike(text,escape='\\'))
        query=query.where(or_(Patient.name.ilike(text,escape='\\'),Patient.id.in_(owner_ids)))
    if after:query=query.where(or_(Patient.name>after[0],and_(Patient.name==after[0],Patient.id>after[1])))
    rows=s.scalars(query.order_by(Patient.name,Patient.id).limit(limit+1)).all();items=rows[:limit]
    return {'items':[patient_view(s,p) for p in items],'next_cursor':cursor_encode(scope,[items[-1].name,items[-1].id]) if len(rows)>limit else None}
def timeline(s,clinic,pid,limit,cursor,category='',q='',start=None,end=None):
    patient(s,pid,clinic);scope=json.dumps([clinic,pid,category,q,str(start),str(end)]);after=cursor_decode(cursor,scope)
    query=select(Event).where(Event.clinic_id==clinic,Event.patient_id==pid)
    if category:query=query.where(Event.event_type==category)
    if q:query=query.where(Event.summary.ilike('%'+q.replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
    if start:query=query.where(Event.occurred_at>=datetime.combine(start,datetime.min.time(),timezone.utc))
    if end:query=query.where(Event.occurred_at<=datetime.combine(end,datetime.max.time(),timezone.utc))
    if after:
        try:when=datetime.fromisoformat(after[0])
        except ValueError:fail('Invalid cursor timestamp')
        query=query.where(or_(Event.occurred_at<when,and_(Event.occurred_at==when,Event.id<after[1])))
    rows=s.scalars(query.order_by(Event.occurred_at.desc(),Event.id.desc()).limit(limit+1)).all();items=rows[:limit]
    return {'items':[event_view(s,e) for e in items],'next_cursor':cursor_encode(scope,[utc(items[-1].occurred_at),items[-1].id]) if len(rows)>limit else None}
def concepts(s,clinic,pid):
    patient(s,pid,clinic)
    terms=s.scalars(select(Concept).join(Observation).join(Event).where(Event.clinic_id==clinic,Event.patient_id==pid).distinct().order_by(Concept.name,Concept.unit)).all()
    return [{'id':r.id,'name':r.name,'code':r.code,'unit':r.unit} for r in terms]
def series(s,clinic,pid,code):
    patient(s,pid,clinic)
    terms=s.scalars(select(Concept).where(or_(Concept.id==code,Concept.code==code))).all()
    if not terms:fail('Concept not found',404)
    if len(terms)>1:fail('This concept has multiple units; select its exact concept ID')
    term=terms[0]
    rows=s.scalars(select(Observation).join(Event).where(Event.clinic_id==clinic,Event.patient_id==pid,Observation.concept_id==term.id).order_by(Observation.observed_at,Observation.id)).all()
    return {'concept':{'id':term.id,'name':term.name,'unit':term.unit},'series':[{'observed_at':utc(o.observed_at),'value':o.value,'ref_low':o.ref_low,'ref_high':o.ref_high,'flag':flag(o),'event_id':o.event_id,'source':source(s,o.source_id)} for o in rows]}
