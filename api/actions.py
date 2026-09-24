"""The sole write interface: UI, assistant, imports and jobs use these operations."""
import hashlib, json, math, secrets
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from db import connection, get, record, update, all_records, event, uid, now

def fail(message,code=422): raise HTTPException(code,message)
def require(data,key):
    v=data.get(key)
    if v is None or (isinstance(v,str) and not v.strip()): fail(f'{key.replace("_"," ").capitalize()} is required')
    return v.strip() if isinstance(v,str) else v
def number(v,label,minimum=0):
    try: n=float(v)
    except (TypeError,ValueError): fail(f'{label} must be a number')
    if not math.isfinite(n) or n<minimum: fail(f'{label} must be at least {minimum}')
    return n
def integer(v,label,minimum=0):
    n=number(v,label,minimum)
    if not n.is_integer(): fail(f'{label} must be a whole number')
    return int(n)
def owned(c,id,clinic,kind=None):
    r=get(c,id,clinic)
    if not r or (kind and r['kind']!=kind): fail('Record not found',404)
    return r
def version(r,p):
    if p.get('version')!=r['version']: fail('This record changed on another device. Reload the latest version before saving.',409)
def check_patient(c,p,clinic): return owned(c,require(p,'patient_id'),clinic,'patient')
def source_check(c,p,clinic):
    s=owned(c,require(p,'source_id'),clinic,'source')
    if s['data']['patient_id']!=p['patient_id']: fail('Source belongs to another patient')
    return s

# Clinical judgment stays with the vet. Nurses can record source facts but cannot approve notes.
PERMISSIONS={
 'patient.create':{'vet','nurse','admin'},'owner.create':{'vet','nurse','admin'},'patient.update':{'vet','nurse','admin'},
 'consultation.create':{'vet','nurse','admin'},'source.add':{'vet','nurse','admin'},'observation.add':{'vet','nurse','admin'},
 'summary.generate':{'vet','admin'},'summary.save':{'vet','admin'},'consultation.approve':{'vet','admin'},
 'appointment.create':{'vet','nurse','admin'},'appointment.update':{'vet','nurse','admin'},
 'invoice.create':{'vet','nurse','admin'},'payment.record':{'vet','admin'},'inventory.create':{'admin'},'inventory.adjust':{'admin'},'medication.dispense':{'vet','admin'},
 'template.save':{'vet','admin'},'reminder.create':{'vet','nurse','admin'},'reminder.complete':{'vet','nurse','admin'},
 'message.queue':{'vet','nurse','admin'},'message.complete':{'vet','nurse','admin'},'share.create':{'vet','admin'},'share.revoke':{'vet','admin'},
 'feature_locks.save':{'admin'},'attachment.approve':{'vet','admin'},'settings.save':{'admin'},'member.save':{'admin'},'import.patients':{'admin'},'recording.create':{'vet','nurse','admin'},'recording.complete':{'vet','nurse','admin'}
}

from workflows import PERMISSIONS as MORE_PERMISSIONS
PERMISSIONS.update(MORE_PERMISSIONS)

from twilio_trial import PERMISSIONS as TWILIO_PERMISSIONS
PERMISSIONS.update(TWILIO_PERMISSIONS)
from clinic_workflows import PERMISSIONS as CLINIC_PERMISSIONS
PERMISSIONS.update(CLINIC_PERMISSIONS)

from advanced_workflows import PERMISSIONS as ADVANCED_PERMISSIONS
PERMISSIONS.update(ADVANCED_PERMISSIONS)

from test_adapters import PERMISSIONS as ADAPTER_PERMISSIONS
PERMISSIONS.update(ADAPTER_PERMISSIONS)

from organizations import PERMISSIONS as ORGANIZATION_PERMISSIONS
PERMISSIONS.update(ORGANIZATION_PERMISSIONS)

from ontology_workflow import PERMISSIONS as ONTOLOGY_PERMISSIONS
PERMISSIONS.update(ONTOLOGY_PERMISSIONS)

from transfers import PERMISSIONS as TRANSFER_PERMISSIONS
PERMISSIONS.update(TRANSFER_PERMISSIONS)

from migration_plan import PERMISSIONS as MIGRATION_PERMISSIONS
PERMISSIONS.update(MIGRATION_PERMISSIONS)

from stripe_payments import PERMISSIONS as STRIPE_PERMISSIONS
PERMISSIONS.update(STRIPE_PERMISSIONS)
from billing import PERMISSIONS as BILLING_PERMISSIONS
PERMISSIONS.update(BILLING_PERMISSIONS)
from scheduling import PERMISSIONS as SCHEDULING_PERMISSIONS
PERMISSIONS.update(SCHEDULING_PERMISSIONS)
from recalls import PERMISSIONS as RECALL_PERMISSIONS
PERMISSIONS.update(RECALL_PERMISSIONS)
from organization_adoption import PERMISSIONS as ADOPTION_PERMISSIONS
PERMISSIONS.update(ADOPTION_PERMISSIONS)
from access_controls import PERMISSIONS as ACCESS_PERMISSIONS
PERMISSIONS.update(ACCESS_PERMISSIONS)

DEPENDENCIES={
 'recall.prepare':('message.queue',), 'recall.cancel':('message.cancel',),
 'leave.review':('schedule.configure',),
 'credit_note.reverse':('credit_note.create',),
 'stripe.checkout':('payment.record',),'stripe.refund':('payment.refund',),
 'test.lab.receive':('clinical.ingest',),
 'clinical.ingest':('source.add',),
 'recording.create':('source.add',),'recording.complete':('recording.create',),
 'recording.rename':('source.add',),'source.speakers':('source.add',),
 'recording.transcribe':('source.add',),'recording.refine':('recording.transcribe',),'lab.import':('source.add',),
 'observation.add':('source.add',),'observation.record':('source.add',),
 'intake.accept':('source.add',),'reminder.queue_due':('message.queue',),
 'discharge.queue':('message.queue','share.create'),
}

def allowed_actions(c,clinic,actor):
    from read_access import allowed_reads, action_reads
    reads=allowed_reads(c,clinic,actor)
    member=owned(c,actor,clinic,'member')['data'];practice=owned(c,clinic,clinic,'clinic')['data']
    locked=set(practice.get('locked_features',[]))
    from organizations import blocked
    master_locks=blocked(c,clinic,actor)
    def allowed(action):
        return action_reads(action)<=reads and action not in master_locks and member.get('active') and member['role'] in PERMISSIONS[action] and (member['role']=='admin' or action not in locked) and all(allowed(dep) for dep in DEPENDENCIES.get(action,()))
    return [a for a in PERMISSIONS if allowed(a)]

def authorize(c,clinic,actor,action):
    if action not in allowed_actions(c,clinic,actor):fail('Your role or clinic permissions do not allow this action',403)
    return owned(c,actor,clinic,'member')

def execute(action,p,clinic,actor,key):
    if action not in PERMISSIONS: fail('Unknown action',404)
    fingerprint=hashlib.sha256(json.dumps({'action':action,'payload':p},sort_keys=True).encode()).hexdigest()
    with connection(True) as c:
        authorize(c,clinic,actor,action)
        previous=c.execute('SELECT * FROM mutations WHERE clinic_id=? AND actor_id=? AND key=?',(clinic,actor,key)).fetchone()
        if previous:
            if previous['payload_hash']!=fingerprint: fail('Idempotency key was reused with different input',409)
            return json.loads(previous['result'])
        from db import mutation_actor
        token=mutation_actor.set(actor)
        try:result=dispatch(c,action,p,clinic,actor)
        finally:mutation_actor.reset(token)
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),clinic,actor,action,result.get('id',''),now()))
        c.execute('INSERT INTO mutations VALUES(?,?,?,?,?)',(clinic,actor,key,fingerprint,json.dumps(result)))
        return result

def dispatch(c,a,p,clinic,actor):
    from clinic_workflows import calendar_date, clinic_today, revoke_patient_access
    if a in ACCESS_PERMISSIONS:
        from access_controls import dispatch as access_action
        return access_action(c,a,p,clinic,actor)
    if a in ADOPTION_PERMISSIONS:
        from organization_adoption import dispatch as adoption_action
        return adoption_action(c,a,p,clinic,actor)
    if a in RECALL_PERMISSIONS:
        from recalls import dispatch as recall_action
        return recall_action(c,a,p,clinic,actor)
    if a in SCHEDULING_PERMISSIONS:
        from scheduling import dispatch as scheduling_action
        return scheduling_action(c,a,p,clinic,actor)
    if a in BILLING_PERMISSIONS:
        from billing import dispatch as billing_action
        return billing_action(c,a,p,clinic,actor)
    if a in TWILIO_PERMISSIONS:
        from twilio_trial import dispatch as twilio_action
        return twilio_action(c,a,p,clinic,actor)
    if a in STRIPE_PERMISSIONS:
        from stripe_payments import dispatch as stripe_action
        return stripe_action(c,a,p,clinic,actor)
    if a in MIGRATION_PERMISSIONS:
        from migration_plan import dispatch as migration
        return migration(c,a,p,clinic,actor)
    if a in TRANSFER_PERMISSIONS:
        from transfers import dispatch as transfer
        return transfer(c,a,p,clinic,actor)
    if a in ONTOLOGY_PERMISSIONS:
        from ontology_workflow import dispatch as ontology
        return ontology(c,a,p,clinic,actor)
    if a in ORGANIZATION_PERMISSIONS:
        from organizations import dispatch as organization
        return organization(c,a,p,clinic,actor)
    if a in ADAPTER_PERMISSIONS:
        from test_adapters import dispatch as adapter
        return adapter(c,a,p,clinic,actor)
    if a in ADVANCED_PERMISSIONS:
        from advanced_workflows import dispatch as advanced
        return advanced(c,a,p,clinic,actor)
    if a in CLINIC_PERMISSIONS:
        from clinic_workflows import dispatch as workflow
        return workflow(c,a,p,clinic,actor)
    if a=='owner.create':
        return record(c,'owner',clinic,{'name':require(p,'name'),'email':p.get('email',''),'phone':p.get('phone','')})
    if a=='patient.create':
        owner_id=p.get('owner_id')
        if owner_id:
            if owned(c,owner_id,clinic,'owner')['data'].get('merged_into'):fail('Select an active owner')
        else: owner_id=record(c,'owner',clinic,{'name':require(p,'owner_name'),'email':p.get('owner_email',''),'phone':p.get('owner_phone','')})['id']
        external=p.get('external_id','').strip()
        if external and any(r['data'].get('external_id')==external for r in all_records(c,clinic,'patient')): fail('External patient ID already exists',409)
        return record(c,'patient',clinic,{'name':require(p,'name'),'species':require(p,'species'),'breed':p.get('breed',''),'sex':p.get('sex','Unknown'),'weight':number(p.get('weight',0),'Weight'),'age':p.get('age',''),'date_of_birth':calendar_date(p.get('date_of_birth'), 'Date of birth', latest=clinic_today(c,clinic).date(), optional=True),'owner_id':owner_id,'external_id':external})
    if a=='patient.update':
        r=owned(c,p['id'],clinic,'patient'); version(r,p)
        allowed={'name','species','breed','sex','weight','age','date_of_birth','owner_id'}
        d={**r['data'],**{k:v for k,v in p.items() if k in allowed}}
        require(d,'name'); require(d,'species'); d['weight']=number(d['weight'],'Weight'); owned(c,d['owner_id'],clinic,'owner')
        if owned(c,d['owner_id'],clinic,'owner')['data'].get('merged_into'):fail('Select an active owner')
        if 'additional_owner_ids' in d:d['additional_owner_ids']=[x for x in d['additional_owner_ids'] if x!=d['owner_id']]
        d['date_of_birth']=calendar_date(d.get('date_of_birth'), 'Date of birth', latest=clinic_today(c,clinic).date(), optional=True)
        if d['owner_id']!=r['data']['owner_id']: revoke_patient_access(c,clinic,r['id'])
        return update(c,r,d)
    if a=='consultation.create':
        check_patient(c,p,clinic)
        template=p.get('template_id','soap-'+clinic); owned(c,template,clinic,'template')
        return record(c,'consultation',clinic,{'patient_id':p['patient_id'],'title':p.get('title','Consultation'),'status':'in_progress','template_id':template,'summary':[],'source_ids':[],'input_revision':0,'generated_revision':0,'date':datetime.now().date().isoformat()})
    if a=='source.add':
        check_patient(c,p,clinic)
        consultation=owned(c,p['consultation_id'],clinic,'consultation') if p.get('consultation_id') else None
        if consultation and consultation['data']['patient_id']!=p['patient_id']: fail('Consultation belongs to a different patient')
        s=record(c,'source',clinic,{'patient_id':p['patient_id'],'consultation_id':p.get('consultation_id'),'title':p.get('title','Veterinarian note'),'text':require(p,'text'),'section':p.get('section','Subjective'),'category':p.get('category','clinical'),'author':owned(c,actor,clinic,'member')['data']['name'],'recording_id':p.get('recording_id')})
        if consultation:
            d=consultation['data']; d['source_ids']=[*d.get('source_ids',[]),s['id']]; d['input_revision']=d.get('input_revision',0)+1; d['status']='in_progress'; update(c,consultation,d)
        event(c,clinic,p['patient_id'],p.get('category','clinical'),s['data']['title'],s['data']['text'],[s['id']])
        return s
    if a=='observation.add':
        check_patient(c,p,clinic); source_check(c,p,clinic)
        value=number(p.get('value'),'Value',-1e9)
        low=number(p['low'],'Lower range',-1e9) if p.get('low') not in ('',None) else None
        high=number(p['high'],'Upper range',-1e9) if p.get('high') not in ('',None) else None
        if low is not None and high is not None and low>high: fail('Lower range must not exceed upper range')
        d={'patient_id':p['patient_id'],'name':require(p,'name'),'value':value,'unit':require(p,'unit'),'low':low,'high':high,'source_id':p['source_id'],'category':p.get('category','Vitals')}
        r=record(c,'observation',clinic,d)
        event(c,clinic,p['patient_id'],d['category'].lower(),d['name'],f'{value:g} {d["unit"]}',[d['source_id']]); return r
    if a=='summary.generate':
        r=owned(c,p['id'],clinic,'consultation'); version(r,p)
        sources=r['data'].get('source_ids',[])
        if not sources: fail('Add a transcript or note before generating a document')
        template=owned(c,p.get('template_id',r['data']['template_id']),clinic,'template')
        if p.get('mode','verbatim') not in ('verbatim','ai'): fail('Invalid generation mode')
        if p.get('mode')=='ai':
            from providers import available
            if not available()['ai']: fail('Configure the AI provider before generating',503)
        job=uid(); snapshot={'version':r['version'],'source_ids':sources,'sections':template['data']['sections'],'template_id':template['id'],'patient_id':r['data']['patient_id'],'input_revision':r['data']['input_revision'],'mode':p.get('mode','verbatim'),'actor_id':actor,'retention':get(c,'settings-'+clinic,clinic)['data'].get('retention','medical')}
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(job,clinic,r['id'],'queued',json.dumps(snapshot),None,None,now(),now()))
        return {'id':job,'status':'queued'}
    if a=='summary.save':
        r=owned(c,p['id'],clinic,'consultation'); version(r,p)
        sections=p.get('summary',[])
        if not isinstance(sections,list): fail('Summary must be a section list')
        for section in sections:
            require(section,'name'); require(section,'text')
            for sid in section.get('source_ids',[]):
                src=owned(c,sid,clinic,'source')
                if src['data']['patient_id']!=r['data']['patient_id']: fail('A receipt belongs to another patient')
        d=r['data']; d['summary']=sections; d['status']='in_progress'; d['edited_by']=actor; d['generated_revision']=d['input_revision']
        return update(c,r,d)
    if a=='consultation.approve':
        r=owned(c,p['id'],clinic,'consultation'); version(r,p)
        if not r['data'].get('summary'): fail('Create a document before approving')
        if r['data'].get('generated_revision')!=r['data'].get('input_revision'): fail('New notes have been added. Reassemble the document or review and save edits before approving.',409)
        if r['data'].get('status')=='reviewed': return r
        d=r['data']; d['status']='reviewed'; d['approved_by']=actor; d['approved_at']=now(); result=update(c,r,d)
        event(c,clinic,d['patient_id'],'consultation',d['title'],'\n\n'.join(x['name']+'\n'+x['text'] for x in d['summary']),d['source_ids'],True)
        return result
    if a=='appointment.create':
        check_patient(c,p,clinic); clinician=p.get('clinician',clinic+'-vet'); owned(c,clinician,clinic,'member')
        from clinic_workflows import calendar_date
        from scheduling import clock_time
        date=calendar_date(p.get('date')); time=clock_time(p.get('time')); duration=integer(p.get('duration',30),'Duration',5)
        start=datetime.fromisoformat(date+'T'+time)
        from operations_rules import schedule
        schedule(c,clinic,clinician,start,duration,p.get('room',''))
        for r in all_records(c,clinic,'appointment'):
            d=r['data']
            if d['clinician']!=clinician or d['status'] in ('cancelled','completed'): continue
            other=datetime.fromisoformat(d['date']+'T'+d['time'])
            if start<other+timedelta(minutes=d['duration']) and other<start+timedelta(minutes=duration): fail('This clinician already has an appointment at that time',409)
        return record(c,'appointment',clinic,{'patient_id':p['patient_id'],'date':date,'time':time,'duration':duration,'reason':require(p,'reason'),'clinician':clinician,'room':p.get('room',''),'status':'scheduled'})
    if a=='appointment.update':
        r=owned(c,p['id'],clinic,'appointment'); version(r,p)
        if p.get('status') not in ('scheduled','arrived','completed','cancelled'): fail('Invalid appointment status')
        if p['status'] in ('scheduled','arrived'):
            d=r['data']; start=datetime.fromisoformat(d['date']+'T'+d['time'])
            from operations_rules import schedule
            update(c,r,{**d,'status':'cancelled'})
            schedule(c,clinic,d['clinician'],start,d['duration'],d.get('room',''))
            r=get(c,r['id'],clinic)
            for other in all_records(c,clinic,'appointment'):
                o=other['data']
                if other['id']==r['id'] or o['clinician']!=d['clinician'] or o['status'] in ('cancelled','completed'): continue
                other_start=datetime.fromisoformat(o['date']+'T'+o['time'])
                if start<other_start+timedelta(minutes=o['duration']) and other_start<start+timedelta(minutes=d['duration']): fail('This clinician already has an appointment at that time',409)
        return update(c,r,{**r['data'],'status':p['status']})
    if a=='invoice.create':
        check_patient(c,p,clinic); items=[]
        for item in p.get('items',[]): items.append({'name':require(item,'name'),'quantity':integer(item.get('quantity',1),'Quantity',1),'price_cents':integer(item.get('price_cents'),'Price')})
        if not items: fail('Add at least one invoice item')
        from operations_rules import totals
        amounts=totals(items,p);total=amounts['total_cents']
        r=record(c,'invoice',clinic,{'patient_id':p['patient_id'],'items':items,**amounts,'paid_cents':0,'status':'issued','number':'INV-'+str(1001+len(all_records(c,clinic,'invoice')))})
        event(c,clinic,p['patient_id'],'invoice',r['data']['number'],f'SGD {total/100:.2f} invoiced'); return r
    if a=='payment.record':
        r=owned(c,p['id'],clinic,'invoice'); version(r,p); d=r['data'];
        from stripe_payments import guard_invoice
        guard_invoice(c,clinic,r['id'])
        if d['status']=='void': fail('Cannot pay a void invoice')
        amount=integer(require(p,'amount_cents'),'Amount',1)
        from billing import outstanding,invoice_status
        if amount>outstanding(d): fail('Payment exceeds outstanding balance')
        method=require(p,'method')
        if method not in ('cash','card_external','bank_external'): fail('Invalid payment method')
        payment=record(c,'payment',clinic,{'invoice_id':r['id'],'patient_id':d['patient_id'],'amount_cents':amount,'method':method,'reference':p.get('reference',''),'recorded_by':actor})
        d['paid_cents']+=amount; d['status']=invoice_status(d); update(c,r,d)
        event(c,clinic,d['patient_id'],'payment','Payment recorded',f'SGD {amount/100:.2f} · {method}'); return payment
    if a=='inventory.create':
        return record(c,'inventory',clinic,{'name':require(p,'name'),'unit':require(p,'unit'),'stock':integer(p.get('stock',0),'Stock'),'reorder':integer(p.get('reorder',5),'Reorder level'),'price_cents':integer(p.get('price_cents',0),'Price')})
    if a=='inventory.adjust':
        r=owned(c,p['id'],clinic,'inventory'); version(r,p)
        from operations_rules import adjust
        stock=adjust(c,clinic,actor,r,p,integer(p.get('stock',r['data']['stock']),'Stock'))
        return update(c,r,{**r['data'],'stock':stock})
    if a=='medication.dispense':
        check_patient(c,p,clinic); stock=owned(c,p['inventory_id'],clinic,'inventory'); version(stock,p)
        q=integer(require(p,'quantity'),'Quantity',1)
        if q>stock['data']['stock']: fail('Insufficient stock',409)
        from operations_rules import dispense
        allocations=dispense(c,clinic,stock,q)
        d={'lots':allocations,'patient_id':p['patient_id'],'inventory_id':stock['id'],'name':stock['data']['name'],'quantity':q,'dose':require(p,'dose'),'frequency':require(p,'frequency'),'instructions':require(p,'instructions'),'prescribed_by':actor}
        r=record(c,'medication',clinic,d); update(c,stock,{**stock['data'],'stock':stock['data']['stock']-q})
        event(c,clinic,p['patient_id'],'medication',d['name'],f'{d["dose"]} · {d["frequency"]}. {d["instructions"]}',approved=True); return r
    if a=='template.save':
        d={'name':require(p,'name'),'description':p.get('description',''),'sections':p.get('sections',[])}
        if not d['sections'] or any(not isinstance(s,str) or not s.strip() for s in d['sections']): fail('Add named sections')
        if len(set(d['sections']))!=len(d['sections']): fail('Section names must be unique')
        if p.get('id'):
            r=owned(c,p['id'],clinic,'template'); version(r,p); return update(c,r,d)
        return record(c,'template',clinic,d)
    if a=='reminder.create':
        check_patient(c,p,clinic)
        p={**p,'due':calendar_date(require(p,'due'),'Due date')}
        return record(c,'reminder',clinic,{'patient_id':p['patient_id'],'title':require(p,'title'),'due':p['due'],'status':'due'})
    if a=='reminder.complete':
        from clinic_workflows import cancel_reminder_draft
        r=owned(c,p['id'],clinic,'reminder'); version(r,p)
        if r['data']['status']!='due': fail('This reminder is already closed',409)
        cancel_reminder_draft(c,r)
        return update(c,r,{**r['data'],'status':'completed'})
    if a=='message.queue':
        patient=check_patient(c,p,clinic); owner=owned(c,patient['data']['owner_id'],clinic,'owner')
        return record(c,'outbox',clinic,{'patient_id':patient['id'],'owner_id':owner['id'],'recipient':owner['data']['name'],'body':require(p,'body'),'channel':'manual','status':'pending','attempts':0})
    if a=='message.complete':
        r=owned(c,p['id'],clinic,'outbox'); version(r,p)
        if r['data']['status']!='pending': fail('Only pending messages can be marked sent',409)
        from recalls import validate_draft
        validate_draft(c,r)
        result=update(c,r,{**r['data'],'status':'sent_manually','sent_at':now()})
        event(c,clinic,r['data']['patient_id'],'message','Owner communication',r['data']['body']); return result
    if a=='share.create':
        check_patient(c,p,clinic); token=secrets.token_urlsafe(32); expiry=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
        c.execute('INSERT INTO grants VALUES(?,?,?,?,0)',(token,clinic,p['patient_id'],expiry)); return {'id':token,'url':'/owner?token='+token,'expires_at':expiry}
    if a=='share.revoke':
        c.execute('UPDATE grants SET revoked=1 WHERE token=? AND clinic_id=?',(require(p,'token'),clinic)); return {'id':p['token'],'revoked':True}
    if a=='feature_locks.save':
        from read_access import READS
        r=owned(c,clinic,clinic,'clinic'); version(r,p)
        locked=p.get('actions',[])
        if not isinstance(locked,list) or any(not isinstance(x,str) or x not in PERMISSIONS and x not in READS for x in locked): fail('Unknown action in feature locks')
        return update(c,r,{**r['data'],'locked_features':locked})
    if a=='attachment.approve':
        r=owned(c,p['id'],clinic,'attachment'); version(r,p)
        approved=bool(p.get('approved',True))
        return update(c,r,{**r['data'],'approved':approved,'approved_by':actor})
    if a=='settings.save':
        r=owned(c,'settings-'+clinic,clinic,'settings'); version(r,p)
        if p.get('retention') not in ('medical','medical_context'): fail('Invalid retention setting')
        d={**r['data'],**{k:p.get(k,r['data'].get(k)) for k in ('retention','language','emergency_phone','reminder_days')}}; d['reminder_days']=integer(d['reminder_days'],'Reminder days')
        return update(c,r,d)
    if a=='member.save':
        role=require(p,'role')
        if role not in ('vet','nurse','admin'): fail('Invalid role')
        if p.get('id'):
            r=owned(c,p['id'],clinic,'member'); version(r,p)
            if r['id']==actor and (role!='admin' or p.get('active') is False): fail('You cannot remove your own administrative access')
            return update(c,r,{**r['data'],'name':require(p,'name'),'role':role,'active':p.get('active',True)})
        return record(c,'member',clinic,{'name':require(p,'name'),'role':role,'active':True})
    if a=='import.patients':
        rows=p.get('rows',[])
        if not rows or len(rows)>1000: fail('Import must contain 1–1000 rows')
        results=[dispatch(c,'patient.create',row,clinic,actor) for row in rows]
        return {'id':uid(),'count':len(results)}
    if a=='recording.create':
        from live_speech import options
        refinement=options(c,p.get('refinement'),clinic,actor)
        patient=check_patient(c,p,clinic)
        consult=owned(c,require(p,'consultation_id'),clinic,'consultation')
        if consult['data']['patient_id']!=patient['id']: fail('Patient mismatch')
        count=sum(r['data']['consultation_id']==consult['id'] for r in all_records(c,clinic,'recording'))
        return record(c,'recording',clinic,{'patient_id':patient['id'],'consultation_id':consult['id'],'number':count+1,'device':p.get('device','web'),'mime':p.get('mime','audio/webm'),'interrupted':bool(p.get('interrupted',False)),'status':'recording','duration':0,'refinement':refinement})
    if a=='recording.complete':
        r=owned(c,p['id'],clinic,'recording'); expected=integer(p.get('expected_chunks'),'Expected chunks',1)
        received={row[0] for row in c.execute('SELECT chunk_index FROM chunks WHERE recording_id=?',(r['id'],))}
        missing=sorted(set(range(expected))-received)
        if received-set(range(expected)): fail('Chunk count does not match this recording',409)
        if missing: fail({'message':'Audio is incomplete. Retry missing chunks before completion.','missing':missing},409)
        duration=number(p.get('duration',0),'Duration')
        if r['data']['status']=='saved':
            if expected!=r['data']['expected_chunks'] or duration!=r['data'].get('capture_duration',r['data']['duration']): fail('Recording is finalized; its manifest cannot be changed',409)
            return r
        r=update(c,r,{**r['data'],'status':'saved','duration':duration,'capture_duration':duration,'expected_chunks':expected,'interrupted':r['data'].get('interrupted',False) or bool(p.get('interrupted',False))})
        if r['data'].get('refinement'):
            from live_speech import enqueue
            enqueue(c,r,expected)
            r=get(c,r['id'],clinic)
        return r
    from workflows import dispatch as extended_dispatch
    return extended_dispatch(c,a,p,clinic,actor)
