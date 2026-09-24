"""Durable projection of existing local PMS facts; never synthesizes clinical facts."""
import re,uuid
from datetime import datetime,timezone,date
from sqlalchemy import select,delete,text
from .models import Clinic,Owner,Patient,OwnerPatient,Source,Event,Concept,Observation,Person,Member,Projection
from .database import session
import db

def stamp(value):
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def setup_queue():
    with db.connection(True) as c:
        if c.dialect=='postgres':
            from pms_postgres import projection_queue
            projection_queue(c)
            return
        c.executescript('''CREATE TABLE IF NOT EXISTS spine_changes(sequence INTEGER PRIMARY KEY AUTOINCREMENT,clinic_id TEXT);
        CREATE TRIGGER IF NOT EXISTS spine_insert AFTER INSERT ON records BEGIN INSERT INTO spine_changes(clinic_id) VALUES(NEW.clinic_id); END;
        CREATE TRIGGER IF NOT EXISTS spine_membership_insert AFTER INSERT ON auth_memberships BEGIN INSERT INTO spine_changes(clinic_id) VALUES(NEW.clinic_id); END;
        CREATE TRIGGER IF NOT EXISTS spine_membership_update AFTER UPDATE ON auth_memberships BEGIN INSERT INTO spine_changes(clinic_id) VALUES(NEW.clinic_id); END;
        CREATE TRIGGER IF NOT EXISTS spine_membership_delete AFTER DELETE ON auth_memberships BEGIN INSERT INTO spine_changes(clinic_id) VALUES(OLD.clinic_id); END;
        CREATE TRIGGER IF NOT EXISTS spine_update AFTER UPDATE ON records BEGIN INSERT INTO spine_changes(clinic_id) VALUES(NEW.clinic_id); END;
        ''')

def sync(clinic):
    with session() as s,s.begin():
        # Serialize the bridge per clinic across API workers. Native ingest is independent.
        s.execute(text('SELECT pg_advisory_xact_lock(hashtext(:name))'),{'name':'broby-projection:'+clinic})
        checkpoint=s.get(Projection,clinic)
        with db.connection(snapshot=True) as c:
            seq=c.execute('SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id=?',(clinic,)).fetchone()[0]
            if checkpoint and checkpoint.sequence==seq:return
            records=db.all_records(c,clinic)
            memberships=[dict(r) for r in c.execute('SELECT * FROM auth_memberships WHERE clinic_id=?',(clinic,))]
        by_id={r['id']:r for r in records};practice=by_id.get(clinic)
        if not practice:return
        s.merge(Clinic(id=clinic,name=practice['data']['name']));s.flush()
        for r in records:
            d=r['data']
            if r['kind']=='owner':s.merge(Owner(id=r['id'],clinic_id=clinic,name=d['name'],email=d.get('email',''),phone=d.get('phone','')))
        s.flush()
        for r in records:
            d=r['data']
            if r['kind']=='patient':
                dob=date.fromisoformat(d['date_of_birth']) if d.get('date_of_birth') else None
                s.merge(Patient(id=r['id'],clinic_id=clinic,name=d['name'],species=d['species'].lower(),breed=d.get('breed',''),sex=d.get('sex','Unknown'),date_of_birth=dob))
        s.flush()
        for r in records:
            d=r['data']
            if r['kind']=='patient':
                s.execute(delete(OwnerPatient).where(OwnerPatient.patient_id==r['id']))
                from clinic_workflows import owner_ids
                for oid in owner_ids(r):s.add(OwnerPatient(owner_id=oid,patient_id=r['id'],is_primary=oid==d.get('owner_id')))
            if r['kind']=='member':
                linked=next((m for m in memberships if m['member_id']==r['id']),None)
                person_id='account:'+linked['username'] if linked else r['id']
                s.merge(Person(id=person_id,name=d['name']));s.flush();s.merge(Member(person_id=person_id,clinic_id=clinic,role=d['role'],active=d['active']))
            if r['kind'] in ('source','intake','attachment'):
                recording=d.get('recording_id');segments=d.get('utterances',[])
                s.merge(Source(id=r['id'],clinic_id=clinic,patient_id=d['patient_id'],kind='document' if r['kind']=='attachment' else 'audio' if recording else 'human',reference_id=recording or r['id'],start_ms=round(segments[0]['start']*1000) if segments else None,end_ms=round(segments[-1]['end']*1000) if segments else None,content={'text':d.get('text',''),'title':d.get('title',''),'author':d.get('author',''),'legacy':True}))
        s.flush()
        events=[r for r in records if r['kind']=='event'];source_events={}
        for r in events:
            d=r['data'];src=next((x for x in d.get('source_ids',[]) if x in by_id and by_id[x]['kind'] in ('source','intake','attachment')),None)
            from .categories import canonical
            typ=canonical(d['category'])
            s.merge(Event(id=r['id'],clinic_id=clinic,patient_id=d['patient_id'],event_type=typ,occurred_at=stamp(d['occurred_at']),summary=d['title'],actor={'kind':'human','name':by_id[src]['data'].get('author','Recorded in clinic') if src else 'Recorded in clinic'},source_id=src,body={'text':d['body'],'legacy':True,'approved':bool(d.get('approved'))},dedupe_key='legacy:'+r['id'],payload_hash='legacy'))
            if src:source_events[(d['patient_id'],src)]=r['id']
        s.flush()
        for r in records:
            d=r['data']
            if r['kind']!='observation':continue
            typ=d.get('value_type','number')
            source_id=d.get('source_id');source_id=source_id if source_id in by_id and by_id[source_id]['kind']=='source' else None
            eid=source_events.get((d['patient_id'],source_id))
            if not eid:
                eid='observation-event:'+r['id']
                s.merge(Event(id=eid,clinic_id=clinic,patient_id=d['patient_id'],event_type='measurement',occurred_at=stamp(r['created_at']),summary=d['name'],actor={'kind':'human','name':'Recorded in clinic'},source_id=source_id,body={'legacy':True},dedupe_key='legacy:'+eid,payload_hash='legacy'));s.flush()
            code=d.get('code') or re.sub(r'[^a-z0-9]+','_',d['name'].lower()).strip('_');cid=str(uuid.uuid5(uuid.NAMESPACE_URL,'broby:concept:'+code+':'+d['unit']))
            if not s.get(Concept,cid):s.add(Concept(id=cid,code=code,name=d['name'],unit=d['unit'],value_type=typ));s.flush()
            s.merge(Observation(id=r['id'],event_id=eid,concept_id=cid,observed_at=stamp(d.get('observed_at',r['created_at'])),value=d['value'] if typ=='number' else None,value_type=typ,text_value=d['value'] if typ=='text' else None,boolean_value=d['value'] if typ=='boolean' else None,ref_low=d.get('low'),ref_high=d.get('high'),source_id=source_id))
        s.merge(Projection(name=clinic,sequence=seq))
