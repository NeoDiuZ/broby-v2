#!/usr/bin/env python3
"""Synthetic same-origin acceptance for the clinic-workflow release. No messages sent."""
import argparse,json,time,uuid,os
from pathlib import Path
from datetime import datetime,timezone
import httpx

parser=argparse.ArgumentParser()
parser.add_argument('base_url');parser.add_argument('--credentials',type=Path)
parser.add_argument('--state',type=Path,required=True);parser.add_argument('--audio',type=Path)
parser.add_argument('--verify-only',action='store_true');parser.add_argument('--close-links',action='store_true')
a=parser.parse_args();base=a.base_url.rstrip('/');checks=[]
c=httpx.Client(base_url=base,timeout=45,headers={'x-clinic-id':'clinic-east','x-actor-id':'clinic-east-admin'})
owner=httpx.Client(base_url=base,timeout=45)
def check(ok,label):
    if not ok:raise AssertionError(label)
    checks.append(label);print('PASS '+label,flush=True)
def req(method,path,expected=200,client=c,**kw):
    r=client.request(method,'/api'+path,**kw)
    if r.status_code!=expected:
        raise AssertionError(f'{method} request expected {expected}, received {r.status_code}: '+r.text[:300])
    return r

def act(action,p,key=None):return req('POST','/actions',json={'action':action,'payload':p,'key':key or str(uuid.uuid4())}).json()
def snapshot():return req('GET','/bootstrap').json()
def record(id):return next(r for r in snapshot()['records'] if r['id']==id)
def job_wait(id):
    for _ in range(90):
        result=req('GET','/jobs/'+id).json()
        if result['status'] not in ('queued','running'):
            check(result['status']=='completed','background job completed');return result
        time.sleep(1)
    raise AssertionError('Job did not complete within 90 seconds')
def save(state):
    a.state.parent.mkdir(parents=True,exist_ok=True);a.state.write_text(json.dumps(state,indent=2));a.state.chmod(0o600)

if a.credentials:
    credentials=json.loads(a.credentials.read_text());req('POST','/login',json={'username':credentials['username'],'password':credentials['password']})
state={}
try:
    check(req('GET','/ready').json()['status']=='ready','same-origin deployment is ready')
    check(req('GET','/session').json()['authenticated'],'clinic session authenticated')
    if a.verify_only or a.close_links:
        state=json.loads(a.state.read_text())
        p=record(state['patient']);check(p['data']['date_of_birth']=='2022-05-14','patient birth date persisted')
        check(req('GET','/v2/patients/'+p['id']).json()['owner']['id']==p['data']['owner_id'],'primary contact persisted in patient spine')
        check(record(state['recording'])['data']['title']=='Synthetic discharge explanation','recording title persisted')
        check(record(state['handover'])['data']['acknowledged_by'],'handover acknowledgement persisted')
        if a.close_links:
            if state.get('package'):
                package=record(state['package'])
                if package['data']['status'] in ('pending','failed'):act('message.cancel',{'id':package['id'],'version':package['version']})
            if state.get('reminder'):
                reminder=record(state['reminder'])
                if reminder['data']['status']=='due':act('reminder.cancel',{'id':reminder['id'],'version':reminder['version']})
            for token in state['links']:act('share.revoke',{'token':token})
            state['links_closed']=True;save(state)
        if state.get('links_closed'):
            for token in state['links']:req('GET','/owner/'+token,expected=404,client=owner)
            check(True,'all synthetic owner links revoked')
        print(f'{len(checks)} workflow persistence checks passed',flush=True)
        raise SystemExit(0)
    suffix=uuid.uuid4().hex[:8]
    patient=act('patient.create',{'name':'SYNTHETIC Workflow '+suffix,'species':'Dog','owner_name':'Synthetic Owner '+suffix,'date_of_birth':'2022-05-14'})
    pid=patient['id'];state.update(patient=pid,links=[])
    invalid=req('POST','/actions',expected=422,json={'action':'patient.update','payload':{'id':pid,'version':patient['version'],'date_of_birth':'2999-01-01'},'key':str(uuid.uuid4())})
    check(record(pid)['version']==patient['version'],'invalid birth date rejected without mutation')
    extra=act('owner.create',{'name':'Synthetic Additional Owner '+suffix})
    old=act('share.create',{'patient_id':pid})
    act('patient.owners',{'id':pid,'version':patient['version'],'owner_id':patient['data']['owner_id'],'additional_owner_ids':[extra['id']]})
    req('GET','/owner/'+old['id'],expected=404,client=owner)
    check(True,'ownership change revokes earlier owner access')
    profile=req('GET','/v2/patients/'+pid).json()
    check(profile['date_of_birth']=='2022-05-14' and profile['owner']['id']==patient['data']['owner_id'],'DOB and primary owner project correctly')
    second=act('patient.create',{'name':'SYNTHETIC Second Pet '+suffix,'species':'Cat','owner_id':patient['data']['owner_id']})
    links=[act('share.create',{'patient_id':p})['id'] for p in (pid,second['id'])];state['links']=links;save(state)
    for token in links:req('POST','/owner/'+token+'/claim',client=owner)
    check({p['id'] for p in req('GET','/owner-account',client=owner).json()['pets']}=={pid,second['id']},'both explicitly saved pets appear')
    req('GET','/owner-account/pets/'+pid,client=owner)
    url='/owner/'+links[0]
    req('POST',url+'/intake',expected=422,client=owner,json={'reason':'  ','key':'empty-'+suffix})
    intake=req('POST',url+'/intake',client=owner,json={'reason':'Synthetic initial owner report','key':'initial-'+suffix}).json()
    revised={'reason':'Synthetic revised owner report','version':1,'key':'revision-'+suffix}
    req('PUT',url+'/intake/'+intake['id'],client=owner,json=revised);req('PUT',url+'/intake/'+intake['id'],client=owner,json=revised)
    check(record(intake['id'])['version']==2,'intake edit retry is idempotent')
    accepted=act('intake.accept',{'id':intake['id'],'version':2})
    check('revised owner report' in record(accepted['data']['source_id'])['data']['text'],'staff accepts the revised owner facts')
    req('PUT',url+'/intake/'+intake['id'],expected=409,client=owner,json={**revised,'version':3,'key':'late-'+suffix})
    check(True,'accepted intake cannot be overwritten by owner')
    source=act('source.add',{'patient_id':pid,'category':'x-ray','title':'Synthetic imaging '+suffix,'text':'Unique category search evidence '+suffix})
    for category in ('x-ray','x_ray'):
        check(len(req('GET','/v2/patients/'+pid+'/timeline',params={'category':category,'q':'Unique category search evidence'}).json()['items'])==1,'category alias and recorded-text search '+category)
    lab=req('POST','/v2/ingest/lab',json={'patient_id':pid,'dedupe_key':'workflow:'+suffix,'occurred_at':datetime.now(timezone.utc).isoformat(),'summary':'Synthetic laboratory evidence','actor':{'kind':'system','name':'Synthetic workflow test'},'source':{'kind':'human','id':source['id'],'text':'Synthetic result 8; supplied range 2 to 5.'},'body':{},'observations':[{'concept':'workflow_marker','name':'Workflow marker','value':8,'unit':'test-unit','ref_low':2,'ref_high':5}]}).json()
    check(any(r['event_id']==lab['id'] for r in req('GET','/v2/overview').json()['flagged']),'native lab result appears in clinic clinical overview')
    consult=act('consultation.create',{'patient_id':pid,'title':'Synthetic workflow consultation'})
    act('source.add',{'patient_id':pid,'consultation_id':consult['id'],'title':'Synthetic instructions','text':'Synthetic care instructions for software verification only.','section':'Plan'})
    consult=record(consult['id']);j=act('summary.generate',{'id':consult['id'],'version':consult['version']});job_wait(j['id'])
    consult=record(consult['id']);check(consult['data']['context_preference'] in ('medical','medical_context'),'document records its actual context preference')
    act('consultation.approve',{'id':consult['id'],'version':consult['version']})
    rec=act('recording.create',{'patient_id':pid,'consultation_id':consult['id'],'mime':'audio/wav'})
    audio=a.audio.read_bytes() if a.audio else b'0123456789';split=max(1,len(audio)//2)
    req('PUT','/recordings/'+rec['id']+'/chunks/0',content=audio[:split]);req('PUT','/recordings/'+rec['id']+'/chunks/0',content=audio[:split])
    req('POST','/actions',expected=409,json={'action':'recording.complete','payload':{'id':rec['id'],'expected_chunks':2,'duration':10},'key':str(uuid.uuid4())})
    req('PUT','/recordings/'+rec['id']+'/chunks/1',content=audio[split:])
    rec=act('recording.complete',{'id':rec['id'],'expected_chunks':2,'duration':10})
    rec=act('recording.rename',{'id':rec['id'],'version':rec['version'],'title':'Synthetic discharge explanation'})
    state['recording']=rec['id'];check(rec['data']['number']==1,'recording rename preserves numbering')
    req('GET',url+'/audio/'+rec['id'],expected=404,client=owner)
    rec=act('recording.approve',{'id':rec['id'],'version':rec['version']})
    ranged=req('GET',url+'/audio/'+rec['id'],expected=206,client=owner,headers={'Range':'bytes=0-9'})
    check(ranged.content==audio[:10],'approved owner audio supports byte-range seeking')
    if a.audio and snapshot()['integrations'].get('transcription'):
        j=act('recording.transcribe',{'id':rec['id'],'language':'en'});speech=job_wait(j['id']);src=record(speech['result']['source_id'])
        check(bool(src['data'].get('provider_request_id')) and bool(src['data']['utterances']),'real speech provider returned timestamped evidence and a receipt')
        labels={str(u['speaker']):'Synthetic speaker '+str(u['speaker']) for u in src['data']['utterances'] if u.get('speaker') is not None}
        labelled=act('source.speakers',{'id':src['id'],'version':src['version'],'speaker_labels':labels})
        check(labelled['data']['utterances']==src['data']['utterances'],'speaker review preserves original transcript evidence')
        state['transcript']=src['id']
    today=req('GET',url,client=owner).json()['today']
    reminder=act('reminder.create',{'patient_id':pid,'title':'SYNTHETIC Scheduled Recall '+suffix,'due':today})
    state['reminder']=reminder['id']
    settings=next(r for r in snapshot()['records'] if r['kind']=='settings');d=settings['data']
    try:
        act('automation.save',{'version':settings['version'],'auto_reminders':True,'auto_handover':bool(d.get('auto_handover')),'handover_at':d.get('handover_at','07:00')})
        for _ in range(40):
            reminder=record(reminder['id'])
            if reminder['data'].get('outbox_id'):break
            time.sleep(1)
        check(bool(reminder['data'].get('outbox_id')),'running scheduler prepared a reminder draft')
        out=record(reminder['data']['outbox_id']);check(out['data']['status']=='pending' and out['data']['channel']=='manual','scheduled message remains an unsent manual draft')
    finally:
        current=record(settings['id']);act('automation.save',{'version':current['version'],'auto_reminders':bool(d.get('auto_reminders')),'auto_handover':bool(d.get('auto_handover')),'handover_at':d.get('handover_at','07:00')})
    act('reminder.update',{'id':reminder['id'],'version':reminder['version'],'title':'SYNTHETIC Updated Recall '+suffix,'due':today})
    check(record(out['id'])['data']['status']=='cancelled','editing reminder cancels its unsent previous draft')
    handover=act('handover.prepare',{});act('handover.acknowledge',{'id':handover['id']});state['handover']=handover['id']
    check(bool(record(handover['id'])['data']['acknowledged_by']),'handover acknowledgement saved')
    package=act('discharge.queue',{'patient_id':pid},key='care-package-'+suffix)
    state['links'].append(package['data']['grant_token']);state['package']=package['id']
    check(package['data']['share_url'] in package['data']['body'] and package['data']['status']=='pending','approved care package includes an unsent owner link')
    pdf=req('GET',url+'/discharge.pdf',client=owner)
    check(pdf.content.startswith(b'%PDF-'),'owner care instructions download as a real PDF')
    act('share.revoke',{'token':links[1]})
    req('GET','/owner-account/pets/'+second['id'],expected=404,client=owner)
    check(req('GET','/owner-account/pets/'+pid,client=owner).json()['patient']['id']==pid,'revoking one saved pet preserves the other')
    state.update(checks=checks,base_url=base,created_at=datetime.now(timezone.utc).isoformat(),consultation=consult['id'])
    save(state);print(f'{len(checks)} workflow checks passed. Synthetic state saved privately.',flush=True)
finally:
    if a.credentials:c.post('/api/logout')
    c.close();owner.close()
