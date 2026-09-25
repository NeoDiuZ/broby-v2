#!/usr/bin/env python3
"""Synthetic growing-audio acceptance with real configured speech-provider calls.

Run preview, inspect the hosted preview in a browser, then finish. This replays
an encoded fixture; it does not claim to test a physical 25-minute microphone.
"""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
import time
import uuid
import httpx
from continuous_fixture import bind_existing_fixture,new_binding

p=argparse.ArgumentParser()
p.add_argument('base_url');p.add_argument('--credentials',type=Path,required=True)
p.add_argument('--state',type=Path,required=True);p.add_argument('--audio',type=Path)
p.add_argument('--prefix-bytes',type=int);p.add_argument('--phase',choices=['preview','finish','verify'],required=True)
a=p.parse_args();checks=[]
if a.phase=='preview' and a.state.exists():p.error('Preview requires a fresh state path; preserve the existing fixture')
state=json.loads(a.state.read_text()) if a.phase!='preview' else {}
if state.get('base_url') and state['base_url']!=a.base_url.rstrip('/'):p.error('Saved fixture belongs to a different host; authentication was not attempted')

def check(condition,label):
    if not condition:raise AssertionError(label)
    checks.append(label);print('PASS '+label,flush=True)

with httpx.Client(base_url=a.base_url.rstrip('/')+'/api/',timeout=120) as client:
    def request(method,path,**kwargs):
        r=client.request(method,path,**kwargs)
        if r.status_code!=200:raise AssertionError(f'{method} {path.split("/")[0]} returned {r.status_code}')
        return r
    def act(action,payload,key=None):
        return request('POST','actions',json={'action':action,'payload':payload,'key':key or str(uuid.uuid4())}).json()
    def save():
        state['checks']=list(dict.fromkeys(state.get('checks',[])+checks))
        a.state.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile('w',dir=a.state.parent,prefix='.continuous-state-',delete=False) as file:
            temporary=Path(file.name)
            try:
                json.dump(state,file,indent=2);file.flush();os.fsync(file.fileno())
                os.replace(temporary,a.state)
            finally:temporary.unlink(missing_ok=True)
    def records():return {r['id']:r for r in request('GET','bootstrap').json()['records']}
    def poll():
        previous=None
        for _ in range(180):
            j=request('GET','jobs/'+state['job']).json()
            current=(j['status'],(j.get('result') or {}).get('completed_windows',0))
            if current!=previous:print('Speech job: '+str(current),flush=True);previous=current
            if j['status'] in ('waiting','failed','completed','conflict'):return j
            time.sleep(5)
        raise AssertionError('Speech job did not reach a reviewable state')
    credentials=json.loads(a.credentials.read_text())
    login=request('POST','login',json={k:credentials[k] for k in ('username','password')}).json()
    client.headers.update({'x-clinic-id':login['clinic'],'x-actor-id':login['actor']})
    check(request('GET','ready').json()['status']=='ready','deployed service ready')
    if a.phase!='preview':
        memberships=request('GET','bootstrap').json()['clinics']
        def history(clinic,actor,recording):
            response=client.get('records/'+recording+'/history',headers={'x-clinic-id':clinic,'x-actor-id':actor})
            if response.status_code==404:return None
            if response.status_code!=200:raise AssertionError('Fixture binding read failed; refusing default-clinic fallback')
            return response.json()
        state.update(bind_existing_fixture(state,a.base_url,memberships,history))
        client.headers.update({'x-clinic-id':state['clinic'],'x-actor-id':state['actor']});save()
        check(True,'saved recording identity and clinic membership verified independently of login default')
        bound_records=records()
        check(state['recording'] in bound_records and state['consultation'] in bound_records,'bound fixture is currently accessible before any audio upload or provider action')
    if a.phase=='preview':
        if not a.audio or not a.prefix_bytes:p.error('Preview requires --audio and --prefix-bytes')
        original=a.audio.read_bytes()
        if not 0<a.prefix_bytes<len(original):p.error('Prefix must leave a tail to append')
        patient=act('patient.create',{'name':'SYNTHETIC Continuous Speech '+uuid.uuid4().hex[:6],
                     'species':'Dog','owner_name':'Synthetic Continuous Test Owner'})
        consultation=act('consultation.create',{'patient_id':patient['id'],'title':'Synthetic continuous transcription acceptance'})
        recording=act('recording.create',{'patient_id':patient['id'],'consultation_id':consultation['id'],
                     'device':'synthetic-growing-webm','mime':'audio/webm','refinement':{'language':'en','diarize':True}})
        state={**new_binding(a.base_url,login['clinic'],login['actor']),'patient':patient['id'],'consultation':consultation['id'],'recording':recording['id'],
               'audio_sha256':hashlib.sha256(original).hexdigest(),'prefix_bytes':a.prefix_bytes}
        save()
        parts=[original[i:min(i+5*1024*1024,a.prefix_bytes)] for i in range(0,a.prefix_bytes,5*1024*1024)]
        state['prefix_count']=len(parts)
        for n,part in enumerate(parts):request('PUT',f'recordings/{state["recording"]}/chunks/{n}',content=part)
        state['job']=act('recording.refine',{'id':state['recording'],'expected_chunks':len(parts)})['id'];save()
        j=poll();check(j['status']=='waiting','live provider finished a prefix while recording remains open')
        windows=j['result']['windows'];state['preview_receipts']=windows
        check(len(windows)==1 and windows[0]['end']==1500,'exact 25-minute preview section saved')
        check('blue marker' in windows[0]['text'].lower(),'real provider recognized the synthetic preview marker')
        rs=records()
        check(rs[state['recording']]['data']['status']=='recording','preview did not stop recording')
        check(not rs[state['consultation']]['data']['source_ids'] and not rs[state['recording']]['data'].get('transcript_source_id'),
              'provisional text cannot enter the medical source list')
        retry=act('recording.refine',{'id':state['recording'],'expected_chunks':len(parts)})
        check(retry['id']==state['job'] and retry['status']=='waiting','replayed prefix does not queue another provider request')
    else:
        if a.phase=='finish':
            if not a.audio:p.error('Finish requires --audio')
            original=a.audio.read_bytes();check(hashlib.sha256(original).hexdigest()==state['audio_sha256'],'same original fixture used for final append')
            tail=original[state['prefix_bytes']:]
            parts=[tail[i:i+5*1024*1024] for i in range(0,len(tail),5*1024*1024)]
            for n,part in enumerate(parts,state['prefix_count']):request('PUT',f'recordings/{state["recording"]}/chunks/{n}',content=part)
            state['expected_chunks']=state['prefix_count']+len(parts);save()
            act('recording.complete',{'id':state['recording'],'expected_chunks':state['expected_chunks'],'duration':0})
            check(poll()['status']=='completed','Finish automatically processes the tail and completes one transcript')
        rs=records()
        check(state['recording'] in rs,'bound recording is currently available; inspect any clinical hold or access change before proceeding')
        rec=rs[state['recording']]['data'];state['source']=rec['transcript_source_id']
        check(state['source'] in rs and state['consultation'] in rs,'bound transcript and consultation are currently available')
        src=rs[state['source']]['data']
        receipt=src['refinement_windows'][0];previous=state['preview_receipts'][0]
        check(receipt['request_id']==previous['request_id'] and receipt['pcm_sha256']==previous['pcm_sha256'],
              'final audio reused the exact preview provider receipt and verified decoded bytes')
        check(len(src['refinement_windows'])==2 and src['refinement_windows'][1]['start']==1500,'tail joins at the exact original timestamp')
        check('blue marker' in src['text'].lower() and 'green marker' in src['text'].lower(),'both synthetic speech markers appear in the final transcript')
        check(rs[state['consultation']]['data']['source_ids']==[state['source']],'exactly one source attached')
        audio=request('GET',f'recordings/{state["recording"]}/audio').content
        check(hashlib.sha256(audio).hexdigest()==state['audio_sha256'],'original audio is byte-identical after growing upload')
        if a.phase=='finish':
            check(act('recording.complete',{'id':state['recording'],'expected_chunks':state['expected_chunks'],'duration':0})['id']==state['recording'],
                  'final upload retry succeeds after decoded duration is updated')
    check(request('GET','operations/status').json()['sending_enabled'] is False,'customer messaging stays disabled')
    save();print(f'{len(checks)} {a.phase} checks passed',flush=True)
