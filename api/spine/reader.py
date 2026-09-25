"""Adapt native PostgreSQL facts to the existing record consumers without copying them.

Local clinical records remain durably projected; native events are never written back
into SQLite. Callers retain their clinic/patient/approval filters.
"""
from sqlalchemy import select
from . import database,service
from .models import Event,Observation,Concept


def observation_fields(clinic, limit=200):
    """List recorded native concepts without materializing events or sources."""
    with database.session() as s:
        rows=s.execute(select(Concept.code,Concept.name,Concept.unit).join(
            Observation,Observation.concept_id==Concept.id).join(
            Event,Observation.event_id==Event.id).where(
            Event.clinic_id==clinic,Event.payload_hash!='legacy').distinct().order_by(
            Concept.code,Concept.name,Concept.unit).limit(limit)).all()
        return [tuple(row) for row in rows]

def clinical_archive(clinic):
    """Clinic-scoped SQL rows for archival; global concepts are limited to used IDs."""
    from .models import Patient,Owner,OwnerPatient,Source
    with database.session() as s:
        s.connection(execution_options={'isolation_level':'REPEATABLE READ'})
        models=(Owner,Patient,Source,Event)
        data={m.__tablename__:[dict(r) for r in s.execute(select(m.__table__).where(m.clinic_id==clinic)).mappings()] for m in models}
        data['owner_patients']=[dict(r) for r in s.execute(select(OwnerPatient.__table__).join(Patient).where(Patient.clinic_id==clinic)).mappings()]
        data['observations']=[dict(r) for r in s.execute(select(Observation.__table__).join(Event).where(Event.clinic_id==clinic)).mappings()]
        ids={r['concept_id'] for r in data['observations']}
        data['concepts']=[dict(r) for r in s.execute(select(Concept.__table__).where(Concept.id.in_(ids))).mappings()]
        return data

def native_records(clinic,patient_id=None):
    with database.session() as s:
        query=select(Event).where(Event.clinic_id==clinic,Event.payload_hash!='legacy')
        if patient_id:query=query.where(Event.patient_id==patient_id)
        result=[];source_ids=set()
        events=list(s.scalars(query.order_by(Event.occurred_at.desc())))
        context=service.event_context(s,events)
        for e in events:
            view=service.event_view(s,e,context);when=service.utc(e.occurred_at)
            def row(id,kind,data):return {'id':id,'kind':kind,'clinic_id':clinic,'version':1,'created_at':when,'updated_at':when,'data':data}
            result.append(row(e.id,'event',{'patient_id':e.patient_id,'title':e.summary,'category':view['event_type'],'occurred_at':when,'body':e.body.get('text',''),'approved':e.body.get('owner_approved') is True,'native_spine':True,'source_ids':[e.source_id] if e.source_id else [],'receipt':view['source'],'observations':view['observations']}))
            for receipt in [view['source'],*[o['source'] for o in view['observations']]]:
                if receipt and receipt['receipt_id'] not in source_ids:
                    src=context['sources'][receipt['receipt_id']];source_ids.add(src.id)
                    result.append(row(src.id,'source',{'patient_id':e.patient_id,'title':src.content.get('title') or src.reference_id,'text':src.content.get('text',''),'receipt':receipt,'native_spine':True}))
            for o in view['observations']:
                result.append(row(o['id'],'observation',{'patient_id':e.patient_id,'event_id':e.id,'name':o['name'],'code':o['concept'],'value':o['value'],'value_type':o['value_type'],'unit':o['unit'],'low':o['ref_low'],'high':o['ref_high'],'source_id':o['source']['receipt_id'] if o['source'] else None,'receipt':o['source'],'category':view['event_type'],'native_spine':True}))
        return result
