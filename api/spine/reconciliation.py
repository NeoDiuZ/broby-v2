"""Apply authoritative PMS dispositions to native/source-derived clinical reads."""
from sqlalchemy import select
from .models import Event, Source, Observation


def native_dependents(clinic,excluded):
    from .database import session
    bad=dict(excluded)
    with session() as s:
        sources=list(s.scalars(select(Source).where(Source.clinic_id==clinic)))
        events=list(s.scalars(select(Event).where(Event.clinic_id==clinic)))
        event_by_id={event.id:event for event in events}
        observations=list(s.scalars(select(Observation).join(Event).where(Event.clinic_id==clinic)))
        held={v['patient_id']:v for v in bad.values() if v.get('patient_id')}
        for row in [*sources,*events]:
            if row.patient_id in held and row.id not in bad:bad[row.id]={**held[row.patient_id],'status':'patient_identity_hold','record_id':row.id,'patient_id':row.patient_id}
        for src in sources:
            if src.reference_id in bad and src.id not in bad:bad[src.id]={**bad[src.reference_id],'status':'dependent_record','record_id':src.id,'patient_id':src.patient_id}
        for obs in observations:
            if obs.source_id in bad and obs.event_id not in bad:
                event=event_by_id[obs.event_id]
                bad[event.id]={**bad[obs.source_id],'status':'dependent_record','record_id':event.id,'patient_id':event.patient_id}
        for event in events:
            if event.source_id in bad and event.id not in bad:bad[event.id]={**bad[event.source_id],'status':'dependent_record','record_id':event.id,'patient_id':event.patient_id}
        for obs in observations:
            if obs.event_id in bad:bad[obs.id]={**bad[obs.event_id],'status':'dependent_record','record_id':obs.id}
    return {id:value for id,value in bad.items() if id not in excluded}


def state(s,clinic):
    key='clinical-reconciliation:'+clinic
    if key not in s.info:
        import db
        from clinical_reconciliation import eligibility
        with db.connection(snapshot=True) as c:s.info[key]=eligibility(c,clinic)
    return s.info[key]


def active(s,clinic,column):
    ids=list(state(s,clinic)['excluded'])
    return column.not_in(ids) if ids else column.is_not(None)


def require(s,clinic,ids):
    from actions import fail
    if any(id in state(s,clinic)['excluded'] for id in ids):fail('This clinical record is excluded from current use. Open the qualified reconciliation review for the retained original.',409)
