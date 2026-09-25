"""Append-only clinician dispositions; originals remain forensic evidence, never rewritten."""
import hashlib
import json
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
import db
from actions import fail, owned

router=APIRouter()
PERMISSIONS={'clinical.reconcile':{'vet','admin'}}
KINDS={'source','event','observation','attachment','recording','medication','medication_history','consultation','intake','outbox','reminder','owner_thread','owner_turn','test_message'}
LIMIT=1000


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def fingerprint(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def safe(row):return {**row,'data':{k:v for k,v in row['data'].items() if k!='path'}}
def rows(c,clinic,kind=None):return db.all_records(c,clinic,kind)


def dependency_ids(row):
    d=row['data'];ids=set(d.get('source_ids',[]))
    if d.get('source_id'):ids.add(d['source_id'])
    if row['kind']=='source' and d.get('recording_id'):ids.add(d['recording_id'])
    if row['kind']=='consultation':
        for section in d.get('summary',[]):ids.update(section.get('source_ids',[]))
    return ids


def media_receipt(c,row):
    """Verify original bytes without exposing local paths or loading whole files."""
    from pathlib import Path
    parts=[];d=row['data'];total=0
    if row['kind']=='attachment':
        expected=[{'index':0,'path':d['path'],'sha256':d['sha256'],'size':d['size']}]
    elif row['kind']=='recording':
        expected=[dict(chunk) for chunk in c.execute('SELECT chunk_index AS "index",path,sha256 FROM chunks WHERE recording_id=? ORDER BY chunk_index',(row['id'],))]
        if [part['index'] for part in expected]!=list(range(d.get('expected_chunks',0))):return {'verified':False,'reason':'Audio manifest is incomplete'}
    else:return None
    for part in expected:
        try:
            path=Path(part['path']);size=path.stat().st_size
            if size+total>200*1024*1024:return {'verified':False,'reason':'Media exceeds the bounded review size'}
            digest=hashlib.sha256()
            with path.open('rb') as file:
                for chunk in iter(lambda:file.read(1024*1024),b''):digest.update(chunk)
            total+=size;actual=digest.hexdigest()
            parts.append({'index':part['index'],'sha256':actual,'size':size,'verified':actual==part['sha256'] and size==part.get('size',size)})
        except (OSError,KeyError):return {'verified':False,'reason':'Original media is unavailable'}
    return {'verified':bool(parts) and all(part['verified'] for part in parts),'parts':parts,'bytes':total}


def eligibility(c,clinic,include_native=True):
    """Read-time holds; cached only within callers' request/transaction, never persisted
    onto original records. Forward-copy holds are qualifications, not corrections."""
    decisions=[db.unpack(r) for r in c.execute("SELECT * FROM records WHERE kind='clinical_reconciliation_review' ORDER BY created_at,id")]
    if not decisions:return {'excluded':{},'patients':{},'patient_epochs':{},'epoch':fingerprint([])}
    latest={}
    for receipt in decisions:
        for group in receipt['data']['decisions']:
            latest[(receipt['clinic_id'],group['group_key'])]=(receipt,group)
    bad={};local_decisions={}
    for receipt,group in [(receipt,group) for receipt in decisions for group in receipt['data']['decisions']]:
        owner=receipt['clinic_id']
        if owner==clinic:local_decisions.setdefault(group['patient_id'],set()).add(receipt['id'])
        stale=False
        if group['disposition']=='retain':
            for original in receipt['data'].get('reviewed_identities',[]):
                current=db.get(c,original['id'],owner)
                if not current or fingerprint(safe(current))!=original['fingerprint']:stale=True;break
            for original in group['records']:
                current=db.get(c,original['id'],owner)
                if not current or fingerprint(safe(current))!=original['fingerprint']:
                    stale=True;break
                if original.get('media') is not None and media_receipt(c,current)!=original['media']:stale=True;break
        if group['disposition']!='retain' or stale:
            status='review_changed' if stale else group['disposition']
            if latest[(owner,group['group_key'])][0]['id']!=receipt['id']:status='patient_identity_hold'
            # An amended group cannot certify untraceable old derivatives. This
            # bounded workflow has no patient-level release operation.
            for original in group['records']:
                bad[(owner,original['id'])]={'status':status,'decision_id':receipt['id'],'record_id':original['id'],'patient_id':group['patient_id'],'source_clinic_id':owner}
    # Known source references form the only dependency graph. No clinical or identity
    # equivalence is inferred from matching prose, names, measurements or files.
    active_clinics={owner for owner,_ in bad}
    candidates={owner:rows(c,owner) for owner in active_clinics|{clinic}}
    for _ in range(LIMIT):
        added=False
        for owner,records in list(candidates.items()):
            held_patients={value['patient_id']:value for (row_clinic,_),value in bad.items() if row_clinic==owner and value.get('patient_id')}
            for row in records:
                if (owner,row['id']) in bad:continue
                reasons=[bad[(owner,id)] for id in dependency_ids(row) if (owner,id) in bad]
                d=row['data'];upstream=bad.get((d.get('origin_clinic_id'),d.get('origin_id')))
                ambiguous=held_patients.get(d.get('patient_id')) if row['kind'] in KINDS else next(iter(held_patients.values()),None) if row['kind']=='handover' else next((held_patients[item.get('patient_id')] for item in d.get('items',[]) if item.get('patient_id') in held_patients),None) if row['kind']=='recall_campaign' else None
                if reasons or upstream or ambiguous:
                    reason=upstream or (reasons[0] if reasons else ambiguous)
                    bad[(owner,row['id'])]={**reason,'status':'source_dispute' if upstream else 'dependent_record' if reasons else 'patient_identity_hold','record_id':row['id'],'patient_id':d.get('patient_id') or reason.get('patient_id'),'upstream_record_id':d.get('origin_id') if upstream else reason['record_id']}
                    added=True
        if include_native:
            from spine.reconciliation import native_dependents
            for owner in list(candidates):
                local={rid:value for (row_clinic,rid),value in bad.items() if row_clinic==owner}
                if local:
                    for rid,value in native_dependents(owner,local).items():
                        if (owner,rid) not in bad:bad[(owner,rid)]=value;added=True
        # Find exact known onward copies, including receiving clinics outside this
        # request. Only their identifiers/status cross back; never their clinical text.
        ids=sorted({rid for _,rid in bad})
        if ids:
            for start in range(0,len(ids),200):
                batch=ids[start:start+200];slots=','.join('?' for _ in batch)
                hits=c.execute('SELECT * FROM records WHERE '+db.json_text(c,'data','origin_id')+' IN ('+slots+')',tuple(batch)).fetchall()
                for hit in hits:
                    row=db.unpack(hit);owner=row['clinic_id'];d=row['data']
                    reason=bad.get((d.get('origin_clinic_id'),d.get('origin_id')))
                    if reason and (owner,row['id']) not in bad:
                        bad[(owner,row['id'])]={**reason,'status':'source_dispute','record_id':row['id'],'patient_id':d.get('patient_id'),'upstream_record_id':d['origin_id']}
                        if owner not in candidates:candidates[owner]=rows(c,owner)
                        added=True
        if not added:break
    else:fail('Clinical source dependencies exceed the reconciliation limit; current use is unavailable',409)
    local={rid:value for (owner,rid),value in bad.items() if owner==clinic}
    patients={}
    for value in local.values():
        if value.get('patient_id'):patients.setdefault(value['patient_id'],[]).append(value)
    for value in local.values():
        if value.get('patient_id'):local_decisions.setdefault(value['patient_id'],set()).add(value['decision_id'])
    epochs={pid:fingerprint([sorted(ids),sorted((rid,value['status']) for rid,value in local.items() if value.get('patient_id')==pid)]) for pid,ids in local_decisions.items()}
    return {'excluded':local,'patients':patients,'patient_epochs':epochs,'epoch':fingerprint(sorted(epochs.items())) if epochs else fingerprint([])}


def current_records(c,clinic,records,state=None,clinical_use=False):
    state=state or eligibility(c,clinic)
    result=[]
    for row in records:
        if row['id'] in state['excluded']:
            if row['kind']=='owner_thread' and not clinical_use:
                administrative={k:v for k,v in row['data'].items() if k in {'patient_id','status','urgent','ack_due_at','pending_owner_turn','last_owner_turn','last_message_at','last_reply_at','acknowledged_at','acknowledged_by'}}
                result.append({**row,'data':{**administrative,'title':'Owner follow-up · clinical identity review','text':'Contact and review are needed. Open the qualified conversation; prior clinical wording is withheld.'},'clinical_reconciliation':{'status':'administrative_attention_only','current_clinical_use':False}})
            continue
        if isinstance(row['data'].get('patient_id'),str) and row['data']['patient_id'] in state['patients']:
            if clinical_use:continue
            row={**row,'clinical_reconciliation':{'status':'historical_clinical_identity_unverified','current_clinical_use':False,'notice':'Administrative receipt preserved. Clinical wording must not be used as a current patient fact while identity is under review.'}}
        if row['kind']=='patient' and row['id'] in state['patients']:
            row={**row,'data':{**row['data'],'weight':None,'clinical_reconciliation':{'status':'current_use_restricted','record_count':len(state['patients'][row['id']]),'epoch':state['epoch'],'references':state['patients'][row['id']]}}}
        result.append(row)
    return result


def qualified(row,state):
    status=state['excluded'].get(row['id'])
    return {**row,'clinical_reconciliation':status} if status else row


def require_records(c,clinic,ids,state=None):
    state=state or eligibility(c,clinic)
    if any(id in state['excluded'] for id in ids):
        fail('A referenced clinical record is excluded pending reconciliation. Refresh the patient and use the qualified historical review; do not approve, export or generate from it.',409)
    return state['epoch']


def consultation_ids(row):
    return [row['id'],*dependency_ids(row)]


def known_onward(c,clinic,patient_ids):
    """Exact accepted-copy references for the potential patient-level hold closure."""
    queue=[(clinic,pid,pid) for pid in patient_ids];seen=set();copies={}
    while queue:
        source,pid,root=queue.pop(0)
        if (source,pid,root) in seen:continue
        seen.add((source,pid,root))
        if len(seen)>LIMIT:fail('Known receiving-copy chain exceeds the bounded review; arrange archive reconciliation',422)
        for row in c.execute('SELECT source_clinic,source_patient,target_clinic,kind,origin_id,revision,target_id,request_id FROM transfer_revisions WHERE source_clinic=? AND source_patient=? ORDER BY target_clinic,kind,origin_id,revision',(source,pid)):
            item=dict(row);target=db.get(c,item['target_id'],item['target_clinic']);target_patient=target['data'].get('patient_id') if target else None
            key=(item['source_clinic'],item['target_clinic'],item['kind'],item['origin_id'],item['revision'])
            entry=copies.setdefault(key,{**item,'target_patient_id':target_patient,'root_patient_ids':[],'status':'separate_receiving_clinic_review_required_if_source_patient_held'})
            if root not in entry['root_patient_ids']:entry['root_patient_ids'].append(root)
            if target_patient:queue.append((item['target_clinic'],target_patient,root))
            if len(copies)>LIMIT:fail('Known receiving copies exceed the bounded review; arrange archive reconciliation',422)
    return [copies[key] for key in sorted(copies)]


def review(c,clinic,id):
    from transfers import legacy_review,receiving_owners
    correction=owned(c,id,clinic,'transfer_mapping_correction');d=correction['data']
    patient_ids=[d['previous_patient_id'],d['patient_id']]
    identities=[owned(c,pid,clinic,'patient') for pid in patient_ids]
    context=[];records=[]
    source_request={'target_clinic':clinic,'source_clinic':d['source_clinic_id'],'patient_id':d['source_patient_id']}
    for patient in identities:
        history=legacy_review(c,source_request,patient,mode='clinical_reconciliation')
        extras=[safe(row) for row in rows(c,clinic) if row['data'].get('patient_id')==patient['id'] and row['kind'] in KINDS and row['id'] not in {old['id'] for old in history['existing_records']}]
        history['existing_records'].extend(extras)
        context.append({'patient':patient,'owners':receiving_owners(c,patient),'history':history})
        records.extend(history['existing_records'])
    if len(records)>LIMIT:fail('This reconciliation exceeds the reviewed record limit',422)
    revisions=[dict(x) for x in c.execute('SELECT * FROM transfer_revisions WHERE source_clinic=? AND source_patient=? AND target_clinic=? ORDER BY kind,origin_id,revision',(d['source_clinic_id'],d['source_patient_id'],clinic))]
    previous=rows(c,clinic,'clinical_reconciliation_review');latest={}
    for receipt in sorted(previous,key=lambda r:(r['created_at'],r['id'])):
        for item in receipt['data']['decisions']:latest[item['group_key']]={'receipt_id':receipt['id'],'reviewed_by':receipt['data']['reviewed_by'],'reviewed_at':receipt['created_at'],**item}
    grouped={};unresolved=[]
    for row in records:
        v=row['data']
        if v.get('origin_clinic_id')!=d['source_clinic_id'] or v.get('origin_patient_id')!=d['source_patient_id']:continue
        origin=next((r for r in revisions if r['kind']==v.get('origin_kind') and r['origin_id']==v.get('origin_id') and r['revision']==v.get('origin_revision') and r['fingerprint']==v.get('origin_fingerprint')),None)
        if not origin:
            unresolved.append(row);continue
        key=fingerprint([v['patient_id'],origin['kind'],origin['origin_id'],origin['revision']])
        group=grouped.setdefault(key,{'group_key':key,'patient_id':v['patient_id'],'origin':{**origin,'payload':json.loads(origin['payload'])},'records':[],'previous_decision':latest.get(key)})
        group['records'].append(row)
    groups=[]
    for key,group in sorted(grouped.items()):
        kinds={x['kind'] for x in group['records']};required={'source','event'}|{'file':{'attachment'},'audio':{'recording'},'medication':{'medication_history'}}.get(group['origin']['kind'],set())
        complete=required<=kinds and any(x['id']==group['origin']['target_id'] for x in group['records']) and fingerprint(group['origin']['payload'])==group['origin']['fingerprint']
        if not complete:
            unresolved.extend(group['records']);continue
        group['records'].sort(key=lambda x:(x['kind'],x['id']))
        group['media']={row['id']:media_receipt(c,db.get(c,row['id'],clinic)) for row in group['records'] if row['kind'] in ('attachment','recording')}
        group['versions']={}
        for row in group['records']:
            versions=[]
            for old in c.execute('SELECT version,data,recorded_at FROM record_versions WHERE record_id=? AND clinic_id=? ORDER BY version',(row['id'],clinic)):
                payload=json.loads(old['data']);payload.pop('path',None)
                versions.append({'version':old['version'],'data':payload,'recorded_at':old['recorded_at']})
            if versions:group['versions'][row['id']]=versions
        groups.append(group)
    state=eligibility(c,clinic)
    all_ids={x['id'] for group in groups for x in group['records']}
    derivatives=[safe(row) for row in rows(c,clinic) if row['data'].get('patient_id') in patient_ids and row['id'] not in all_ids and dependency_ids(row)&all_ids]
    downstream=known_onward(c,clinic,patient_ids)
    unresolved_ids={row['id'] for row in unresolved}
    unresolved.extend(row for row in records if row['id'] not in all_ids and row['id'] not in unresolved_ids)
    result={'correction':correction,'identities':context,'groups':groups,'unresolved_legacy_records':unresolved,'known_derivatives':derivatives,'known_onward_copies':downstream,'eligibility_epoch':state['epoch'],'decisions':previous,'patient_hold_preview':{'patient_ids':patient_ids,'policy':'A wrong-patient or unresolved disposition suspends current clinical use for that patient and known receiving-copy patients. Untraceable historical text may depend on disputed facts; all clinical history, owner media, prior answers, discharge drafts, approval, export and AI use remain held after any wrong-patient, unresolved or stale disposition. Later group retention cannot release the patient hold; complete historical-lineage review requires a separate workflow. Original evidence remains in this forensic review.'},'limitations':['Original records and media remain unchanged. No clinical equivalence is inferred.','Known onward copies are independent records and require receiving-clinic review.','Previously downloaded and offline copies cannot be recalled. Offline access still expires within 12 hours; refresh before new clinical use.']}
    if len(encoded(result).encode())>5*1024*1024:fail('This reconciliation exceeds the reviewed metadata limit',422)
    result['digest']=fingerprint(result);return result


def dispatch(c,action,p,clinic,actor):
    from actions import require
    current=review(c,clinic,require(p,'correction_id'))
    if p.get('expected_digest')!=current['digest']:fail('Clinical records or dispositions changed. Reload the entire reconciliation review.',409)
    if p.get('acknowledge_patient_hold') is not True:fail('Review and explicitly acknowledge the patient-level current-use hold and known onward-copy limitations',409)
    if p.get('confirm_review') is not True:fail('Explicitly confirm review of the original source, identities and every selected receiving record',409)
    choices=p.get('decisions')
    if not isinstance(choices,list) or not 1<=len(choices)<=LIMIT:fail('Choose at least one reviewed origin group',422)
    seen=set();decisions=[];groups={g['group_key']:g for g in current['groups']}
    for choice in choices:
        if not isinstance(choice,dict):fail('Invalid reconciliation decision',422)
        group=groups.get(choice.get('group_key'))
        if not group or group['group_key'] in seen:fail('Choose each complete reviewed origin group at most once',422)
        seen.add(group['group_key']);status=choice.get('disposition');reason=choice.get('reason')
        if status not in ('retain','wrong_patient','unresolved'):fail('Choose retain, wrong patient, or unresolved for each origin group',422)
        if not isinstance(reason,str) or not 10<=len(reason.strip())<=1000:fail('Record a reason of 10–1,000 characters for every decision',422)
        reviewed=choice.get('record_decisions')
        if not isinstance(reviewed,list) or any(not isinstance(item,dict) or not isinstance(item.get('id'),str) for item in reviewed):fail('Explicitly review every record in the selected origin group',409)
        ids=[item['id'] for item in reviewed]
        if len(ids)!=len(set(ids)) or set(ids)!={r['id'] for r in group['records']}:fail('Explicitly review every record in the selected origin group',409)
        per_record={item['id']:item for item in reviewed}
        for item in reviewed:
            if item.get('disposition')!=status:fail('An inseparable origin group needs a consistent disposition for every record; otherwise leave it unresolved',409)
            reason_item=item.get('reason')
            if not isinstance(reason_item,str) or not 10<=len(reason_item.strip())<=1000:fail('Record a reason of 10–1,000 characters for each individual record',422)
        if status=='retain' and any(not item['verified'] for item in group['media'].values()):fail('Original media could not be verified; keep this origin group unresolved',409)
        decisions.append({'group_key':group['group_key'],'patient_id':group['patient_id'],'disposition':status,'reason':reason.strip(),'origin':group['origin'],'records':[{'id':r['id'],'kind':r['kind'],'version':r['version'],'fingerprint':fingerprint(r),'media':group['media'].get(r['id']),'disposition':status,'reason':per_record[r['id']]['reason'].strip()} for r in group['records']]})
    result=db.record(c,'clinical_reconciliation_review',clinic,{'correction_id':current['correction']['id'],'patient_id':current['correction']['data']['patient_id'],'previous_patient_id':current['correction']['data']['previous_patient_id'],'reviewed_by':actor,'reviewed_digest':current['digest'],'reviewed_identities':[{'id':r['id'],'fingerprint':fingerprint(safe(r))} for identity in current['identities'] for r in [identity['patient'],*identity['owners']]],'decisions':decisions,'known_onward_copies':current['known_onward_copies'],'clinical_equivalence_asserted':False})
    for pid in {d['patient_id'] for d in decisions}:
        db.event(c,clinic,pid,'clinical','Clinician reviewed transferred record identity','A clinician recorded per-record identity dispositions. Original facts and media remain available in the qualified reconciliation review. No clinical equivalence was inferred. Review receipt: '+result['id'])
    return result


@router.get('/api/clinical-reconciliation/{id}')
def get_review(id:str,request:Request):
    from main import identity
    from actions import authorize
    clinic,actor=identity(request)
    with db.connection(snapshot=True) as c:
        authorize(c,clinic,actor,'clinical.reconcile');return review(c,clinic,id)


@router.get('/api/clinical-reconciliation/{id}/media/{record_id}')
def original_media(id:str,record_id:str,request:Request,acknowledge_historical:bool=False):
    from main import identity
    from actions import authorize
    clinic,actor=identity(request)
    with db.connection() as c:
        authorize(c,clinic,actor,'clinical.reconcile')
        correction=owned(c,id,clinic,'transfer_mapping_correction');row=owned(c,record_id,clinic)
        if not acknowledge_historical or row['kind'] not in ('attachment','recording') or row['data'].get('patient_id') not in (correction['data']['patient_id'],correction['data']['previous_patient_id']):fail('Explicit historical-media review required',409)
        if row['kind']=='attachment':return FileResponse(row['data']['path'],media_type=row['data']['mime'],filename='RECONCILIATION-ORIGINAL-'+row['data']['name'],headers={'X-Broby-Clinical-Status':'historical-unverified'})
        from pathlib import Path
        from audio_response import audio_response
        content=b''.join(Path(x[0]).read_bytes() for x in c.execute('SELECT path FROM chunks WHERE recording_id=? ORDER BY chunk_index',(record_id,)))
    response=audio_response(content,row['data'].get('mime','audio/webm'),request.headers.get('range'))
    response.headers['X-Broby-Clinical-Status']='historical-unverified';return response


def require_patient(c,clinic,patient_id,state=None):
    state=state or eligibility(c,clinic)
    if patient_id in state['patients']:
        fail('Current clinical use is on hold for this patient because historical identity or derivative provenance is unresolved. Open the qualified reconciliation review; reconnect and refresh before any new approval, export or AI action.',409)
    return state['epoch']


def guard_action(c,action,p,clinic):
    # A held patient's source lineage cannot safely be reconstructed from free
    # text. Preserve capture and forensic evidence, but block clinical reuse.
    guarded={'summary.generate','summary.save','consultation.approve','attachment.approve',
             'recording.approve','recording.transcribe','recording.refine','clinical.approve',
             'conversation.reply','discharge.queue','message.queue','message.update','message.complete','test.message.create','twilio.trial_send','medication.dispense'}
    references={v for k,v in p.items() if (k=='id' or k.endswith('_id')) and isinstance(v,str)}
    if action in guarded or action in {'source.add','observation.add','observation.record','clinical.ingest'}:
        state=eligibility(c,clinic)
        require_records(c,clinic,references,state)
        if action in guarded:
            patients={p.get('patient_id')}
            for id in references:
                row=db.get(c,id,clinic)
                if row:patients.add(row['data'].get('patient_id'))
            for pid in patients:
                if pid:require_patient(c,clinic,pid,state)
        if action in {'summary.save','source.add'}:
            require_records(c,clinic,dependency_ids({'kind':'consultation','data':p}),state)


def job_view(c,clinic,job,state=None):
    state=state or eligibility(c,clinic)
    payload=job.get('payload') or {}
    pid=payload.get('patient_id')
    consult=db.get(c,job.get('consultation_id'),clinic)
    if consult:pid=consult['data'].get('patient_id')
    if pid in state['patients']:
        return {**job,'result':None,'clinical_reconciliation':{'status':'current_use_restricted','patient_id':pid},'error':'Historical clinical result is restricted pending patient identity review. Original evidence remains in the clinic archive.'}
    return job


def guard_job(c,job,payload):
    state=eligibility(c,job['clinic_id'])
    ids=[job.get('consultation_id'),payload.get('recording_id'),*payload.get('source_ids',[])]
    require_records(c,job['clinic_id'],ids,state)
    require_patient(c,job['clinic_id'],payload.get('patient_id'),state)
    expected=payload.get('clinical_epoch')
    if expected is not None and expected!=scope_epoch(state,payload.get('patient_id')):fail('Clinical identity review changed while this job ran. Refresh and prepare a new job.',409)
    return scope_epoch(state,payload.get('patient_id'))


def scope_epoch(state,patient_id=None):
    return state.get("patient_epochs",{}).get(patient_id,fingerprint([])) if patient_id else state["epoch"]


def has_reviews(c):
    return bool(c.execute("SELECT 1 FROM records WHERE kind='clinical_reconciliation_review' LIMIT 1").fetchone())


@router.get('/api/clinical-reconciliation/patients/{patient_id}/history')
def patient_history(patient_id:str,request:Request):
    """Receiving-clinic forensic access without purporting to settle another clinic's copy."""
    from main import identity
    from actions import authorize
    from spine.reader import native_records
    clinic,actor=identity(request)
    with db.connection(snapshot=True) as c:
        authorize(c,clinic,actor,'clinical.reconcile')
        patient=owned(c,patient_id,clinic,'patient');state=eligibility(c,clinic)
        originals=[safe(row) for row in rows(c,clinic)+native_records(clinic,patient_id) if row['data'].get('patient_id')==patient_id]
        if len(originals)>LIMIT:fail('This patient exceeds the bounded historical review; use a qualified clinic archive',422)
        return {'purpose':'forensic_history','current_clinical_use':False,'patient':patient,'records':originals,'qualifications':state['patients'].get(patient_id,[]),'status':'unresolved','limitation':'Originals remain unchanged. Source disputes and independent receiving copies require separate receiving-clinic review; this read does not resolve them.'}


@router.get('/api/clinical-reconciliation/patients/{patient_id}/media/{record_id}')
def patient_original_media(patient_id:str,record_id:str,request:Request,acknowledge_historical:bool=False):
    from main import identity
    from actions import authorize
    clinic,actor=identity(request)
    with db.connection() as c:
        authorize(c,clinic,actor,'clinical.reconcile');owned(c,patient_id,clinic,'patient')
        row=owned(c,record_id,clinic)
        if row['data'].get('patient_id')!=patient_id:fail('Historical record not found',404)
        if not acknowledge_historical or row['kind'] not in ('attachment','recording'):fail('Explicit historical-media review required',409)
        if row['kind']=='attachment':return FileResponse(row['data']['path'],media_type=row['data']['mime'],filename='RECONCILIATION-ORIGINAL-'+row['data']['name'],headers={'X-Broby-Clinical-Status':'historical-unverified'})
        from pathlib import Path
        from audio_response import audio_response
        content=b''.join(Path(x[0]).read_bytes() for x in c.execute('SELECT path FROM chunks WHERE recording_id=? ORDER BY chunk_index',(record_id,)))
    response=audio_response(content,row['data'].get('mime','audio/webm'),request.headers.get('range'))
    response.headers['X-Broby-Clinical-Status']='historical-unverified';return response
