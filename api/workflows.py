"""Additional patient and PMS actions, sharing the transaction and permissions layer."""
from datetime import datetime,timedelta
import json
from db import all_records,get,record,update,event,uid,now

PERMISSIONS={
 'lab.import':{'vet','nurse','admin'},
 'owner.update':{'vet','nurse','admin'}, 'owner.merge':{'admin'},
 'consultation.archive':{'vet','admin'},'template.archive':{'vet','admin'},
 'appointment.reschedule':{'vet','nurse','admin'}, 'appointment.series':{'vet','nurse','admin'},
 'observation.record':{'vet','nurse','admin'}, 'ontology.save':{'admin'},
 'intake.accept':{'vet','nurse','admin'},'intake.close':{'vet','nurse','admin'},
 'recording.approve':{'vet','admin'}, 'job.retry':{'vet','admin'},
 'recording.transcribe':{'vet','nurse','admin'}, 'reminder.queue_due':{'vet','nurse','admin'},
 'message.update':{'vet','nurse','admin'},'message.cancel':{'vet','nurse','admin'},
 'payment.refund':{'vet','admin'},'invoice.void':{'vet','admin'},
 'inventory.receive':{'admin'},'import.records':{'admin'},
}

def dispatch(c,a,p,clinic,actor):
    from actions import owned,require,version,fail,number,integer,dispatch as base
    if a=='lab.import':
        import csv,io
        owned(c,p['patient_id'],clinic,'patient')
        raw=require(p,'csv')
        if not isinstance(raw,str) or len(raw)>1000000:fail('Lab CSV must be under 1 MB')
        rows=list(csv.DictReader(io.StringIO(raw)))
        if not rows or len(rows)>500:fail('Provide 1–500 lab results')
        source=base(c,'source.add',{'patient_id':p['patient_id'],'title':require(p,'title'),'text':raw,'category':'bloods','section':'Objective'},clinic,actor)
        created=[]
        for row in rows:
            result=base(c,'observation.add',{**row,'patient_id':p['patient_id'],'source_id':source['id'],'category':'Bloods'},clinic,actor)
            created.append(result['id'])
        return {'id':source['id'],'count':len(created),'observation_ids':created}
    if a=='owner.update':
        r=owned(c,p['id'],clinic,'owner');version(r,p)
        return update(c,r,{**r['data'],'name':require(p,'name'),'email':p.get('email',''),'phone':p.get('phone','')})
    if a=='owner.merge':
        source=owned(c,p['id'],clinic,'owner');version(source,p)
        target=owned(c,require(p,'target_id'),clinic,'owner')
        if source['id']==target['id']:fail('Choose two different owners')
        if source['data'].get('merged_into') or target['data'].get('merged_into'):fail('An owner has already been merged',409)
        from clinic_workflows import owner_ids
        for r in all_records(c,clinic,'patient'):
            if source['id'] in owner_ids(r):
                primary=target['id'] if r['data']['owner_id']==source['id'] else r['data']['owner_id']
                extra=list(dict.fromkeys(target['id'] if x==source['id'] else x for x in r['data'].get('additional_owner_ids',[])))
                update(c,r,{**r['data'],'owner_id':primary,'additional_owner_ids':[x for x in extra if x!=primary]})
        return update(c,source,{**source['data'],'merged_into':target['id']})
    if a in ('consultation.archive','template.archive'):
        r=owned(c,p['id'],clinic,a.split('.')[0]);version(r,p)
        if r['id']=='soap-'+clinic:fail('The default SOAP template cannot be archived')
        return update(c,r,{**r['data'],'archived':True})
    if a=='appointment.reschedule':
        r=owned(c,p['id'],clinic,'appointment');version(r,p)
        old=r['data'];update(c,r,{**old,'status':'cancelled'})
        # Reuse collision validation and roll back the temporary state on any failure.
        candidate=base(c,'appointment.create',{**old,**p},clinic,actor)
        c.execute('DELETE FROM records WHERE id=?',(candidate['id'],))
        return update(c,get(c,r['id'],clinic),candidate['data'])
    if a=='appointment.series':
        count=integer(p.get('count',1),'Occurrences',1);interval=integer(p.get('interval_days',7),'Interval',1)
        if count>52:fail('Create at most 52 occurrences')
        try:start=datetime.fromisoformat(require(p,'date'))
        except ValueError:fail('Invalid start date')
        created=[]
        for i in range(count):created.append(base(c,'appointment.create',{**p,'date':(start+timedelta(days=i*interval)).date().isoformat()},clinic,actor)['id'])
        return {'id':created[0],'ids':created,'count':len(created)}
    if a=='ontology.save':
        code=require(p,'code');name=require(p,'name');typ=require(p,'value_type')
        if not code.replace('_','').isalnum() or typ not in ('number','text','boolean'):fail('Invalid observation definition')
        if c.execute('SELECT code FROM ontology WHERE code=?',(code,)).fetchone():fail('Observation code exists; definitions are immutable',409)
        c.execute('INSERT INTO ontology VALUES(?,?,?,?,?)',(code,name,typ,p.get('unit',''),require(p,'category')))
        return {'id':code}
    if a=='observation.record':
        patient=owned(c,p['patient_id'],clinic,'patient');src=owned(c,require(p,'source_id'),clinic,'source')
        if src['data']['patient_id']!=patient['id']:fail('Source belongs to another patient')
        from ontology_workflow import lookup
        term=lookup(c,clinic,require(p,'code'))
        if not term:fail('Choose an observation definition')
        typ=term['value_type'];value=p.get('value')
        if typ=='number':
            r=base(c,'observation.add',{**p,'name':term['name'],'unit':term['unit'],'category':term['category']},clinic,actor)
            return update(c,r,{**r['data'],'code':term['code'],'value_type':'number'})
        if typ=='boolean':
            if value not in (True,False,'true','false'):fail('Boolean value required')
            value=value in (True,'true')
        else:value=require(p,'value')
        r=record(c,'observation',clinic,{'patient_id':patient['id'],'code':term['code'],'name':term['name'],'value':value,'value_type':typ,'unit':term['unit'],'category':term['category'],'source_id':src['id'],'low':None,'high':None})
        event(c,clinic,patient['id'],term['category'].lower(),term['name'],str(value),[src['id']]);return r
    if a in ('intake.accept','intake.close'):
        r=owned(c,p['id'],clinic,'intake');version(r,p)
        if r['data']['status']!='new':fail('This intake has already been handled',409)
        if a=='intake.accept':
            source=base(c,'source.add',{'patient_id':r['data']['patient_id'],'title':'Owner-reported pre-consult information','text':r['data']['text'],'category':'owner','section':'Subjective','consultation_id':p.get('consultation_id')},clinic,actor)
            d={**r['data'],'status':'accepted','source_id':source['id'],'handled_by':actor}
        else:d={**r['data'],'status':'closed','handled_by':actor}
        return update(c,r,d)
    if a=='recording.approve':
        r=owned(c,p['id'],clinic,'recording');version(r,p)
        if r['data']['status']!='saved':fail('Finish uploading this recording first')
        return update(c,r,{**r['data'],'approved':bool(p.get('approved',True)),'approved_by':actor})
    if a=='recording.transcribe':
        import providers
        if not providers.available()['transcription']:fail('Configure the speech provider before transcribing',503)
        r=owned(c,p['id'],clinic,'recording')
        if r['data']['status']!='saved':fail('Recording has missing chunks or is incomplete')
        if r['data'].get('transcript_source_id'):return {'id':r['data']['transcript_source_id'],'status':'completed'}
        for job in c.execute("SELECT * FROM jobs WHERE clinic_id=? AND status IN ('queued','running')",(clinic,)):
            payload=json.loads(job['payload'])
            if payload.get('recording_id')==r['id']:return {'id':job['id'],'status':job['status']}
        if p.get('language','multi') not in ('multi','en','zh','ms'): fail('Unsupported speech language')
        job=uid();payload={'kind':'transcription','recording_id':r['id'],'patient_id':r['data']['patient_id'],'actor_id':actor,'language':p.get('language','multi')}
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(job,clinic,r['data']['consultation_id'],'queued',json.dumps(payload),None,None,now(),now()))
        return {'id':job,'status':'queued'}
    if a=='job.retry':
        r=c.execute('SELECT * FROM jobs WHERE id=? AND clinic_id=?',(p['id'],clinic)).fetchone()
        if not r:fail('Job not found',404)
        if r['status']!='failed':fail('Only failed jobs can be retried. Regenerate conflicting documents from current sources.',409)
        c.execute('DELETE FROM job_claims WHERE job_id=?',(r['id'],))
        c.execute("UPDATE jobs SET status='queued',error=NULL,updated_at=? WHERE id=?",(now(),r['id']))
        return {'id':r['id'],'status':'queued'}
    if a=='reminder.queue_due':
        from clinic_workflows import queue_due
        from actions import authorize
        authorize(c,clinic,actor,'message.queue')
        return queue_due(c,clinic,actor)
    if a in ('message.update','message.cancel'):
        r=owned(c,p['id'],clinic,'outbox');version(r,p)
        if r['data']['status'] not in ('pending','failed'):fail('This message cannot be changed after delivery starts',409)
        if a=='message.cancel' and r['data'].get('grant_token'):c.execute('UPDATE grants SET revoked=1 WHERE token=? AND clinic_id=?',(r['data']['grant_token'],clinic))
        return update(c,r,{**r['data'],**({'body':require(p,'body')} if a=='message.update' else {'status':'cancelled'})})
    if a=='payment.refund':
        payment=owned(c,p['id'],clinic,'payment');invoice=owned(c,payment['data']['invoice_id'],clinic,'invoice');version(invoice,p)
        amount=integer(require(p,'amount_cents'),'Refund amount',1)
        already=sum(r['data']['amount_cents'] for r in all_records(c,clinic,'refund') if r['data']['payment_id']==payment['id'])
        if amount>payment['data']['amount_cents']-already:fail('Refund exceeds the unrefunded payment')
        refund=record(c,'refund',clinic,{'payment_id':payment['id'],'invoice_id':invoice['id'],'patient_id':invoice['data']['patient_id'],'amount_cents':amount,'reason':require(p,'reason'),'recorded_by':actor})
        d=invoice['data'];d['paid_cents']-=amount;d['status']='partial' if d['paid_cents'] else 'issued';update(c,invoice,d)
        event(c,clinic,d['patient_id'],'payment','Refund recorded',f'SGD {amount/100:.2f} · {p["reason"]}')
        return refund
    if a=='invoice.void':
        r=owned(c,p['id'],clinic,'invoice');version(r,p)
        if r['data']['paid_cents']:fail('Record any externally completed refunds before voiding')
        return update(c,r,{**r['data'],'status':'void','void_reason':require(p,'reason')})
    if a=='inventory.receive':
        r=owned(c,p['id'],clinic,'inventory');version(r,p);q=integer(require(p,'quantity'),'Quantity',1)
        if p.get('expiry'):
            try:datetime.fromisoformat(p['expiry'])
            except ValueError:fail('Invalid expiry date')
        from operations_rules import receive
        lot=receive(c,clinic,actor,r,p,q)
        delivery=record(c,'stock_receipt',clinic,{'lot_id':lot['id'],'purchase_order_id':p.get('purchase_order_id'),'inventory_id':r['id'],'quantity':q,'batch':require(p,'batch'),'expiry':p.get('expiry',''),'supplier':require(p,'supplier'),'received_by':actor})
        update(c,r,{**r['data'],'stock':r['data']['stock']+q});return delivery
    if a=='import.records':
        # Explicit structured import; reject missing references before committing anything.
        items=p.get('records',[])
        if not items or len(items)>5000:fail('Provide 1–5000 records')
        kinds={'owner','patient','source','event','observation','consultation','template','reminder','inventory','invoice','payment','medication'}
        ids={r.get('id') for r in items}
        if len(ids)!=len(items) or None in ids:fail('Every record needs a unique ID')
        existing={r['id']:r for r in all_records(c,clinic)}
        for r in items:
            if r.get('kind') not in kinds or not isinstance(r.get('data'),dict):fail('Unsupported or malformed record')
            if get(c,r['id']):fail('An imported ID already exists; no records were imported',409)
            if r['kind'] in ('payment','invoice','medication','inventory'):fail('Financial and stock history require reconciled migration; use patient/clinical records in this importer')
        by_id={**existing,**{r['id']:r for r in items}}
        refs={'owner_id':'owner','patient_id':'patient','source_id':'source','consultation_id':'consultation','template_id':'template'}
        for r in items:
            for key,kind in refs.items():
                target=r['data'].get(key)
                if target and (target not in by_id or by_id[target]['kind']!=kind):fail(f'Invalid {key} on {r["id"]}')
            if r['kind']=='patient' and (not r['data'].get('owner_id') or not r['data'].get('name') or not r['data'].get('species')):fail('Patient identity fields are missing')
            if r['kind'] in ('source','event','observation','consultation','reminder') and not r['data'].get('patient_id'):fail('Clinical records need a patient ID')
            for sid in r['data'].get('source_ids',[]):
                if sid not in by_id or by_id[sid]['kind']!='source' or by_id[sid]['data'].get('patient_id')!=r['data'].get('patient_id'):fail('Invalid or cross-patient source receipt')
        from import_validation import validate
        validate(items,by_id)
        for r in items:record(c,r['kind'],clinic,r['data'],r['id'])
        return {'id':uid(),'count':len(items)}
    fail('Unknown action',404)
