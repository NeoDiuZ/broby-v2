#!/usr/bin/env python3
"""Synthetic V2 hosted acceptance for independent, overlapping voice notes.

Creates a new synthetic patient and consultation on the isolated V2 host only.
It never reads customer media, calls a speech provider, or touches original Broby.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import uuid
import wave

import httpx

V2_HOST='https://frontend-production-1283.up.railway.app'
parser=argparse.ArgumentParser()
parser.add_argument('--credentials',type=Path,required=True)
args=parser.parse_args()
credentials=json.loads(args.credentials.read_text())


def check(label,condition):
    if not condition: raise AssertionError(label)
    print('PASS '+label,flush=True)


def request(client,method,path,**kwargs):
    response=client.request(method,path,**kwargs)
    if response.status_code!=200:
        raise AssertionError(f'{method} API returned HTTP {response.status_code}')
    return response


def command(client,name,payload,key=None):
    return request(client,'POST','actions',json={
        'action':name,'payload':payload,'key':key or str(uuid.uuid4())
    }).json()


def wav(sample):
    out=io.BytesIO()
    with wave.open(out,'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(sample.to_bytes(2,'little',signed=True)*8000)
    return out.getvalue()


with httpx.Client(base_url=V2_HOST+'/api/',timeout=60) as first_device, \
     httpx.Client(base_url=V2_HOST+'/api/',timeout=60) as second_device:
    for client in (first_device,second_device):
        request(client,'POST','login',json=credentials)
        check('independent authenticated session',request(client,'GET','session').json()['authenticated'])
    check('V2 PostgreSQL and files ready',request(first_device,'GET','ready').json()['pms_store']=='postgres')

    run=uuid.uuid4().hex[:8]
    patient=command(first_device,'patient.create',{
        'name':'SYNTHETIC handoff '+run,'species':'Cat','owner_name':'Synthetic Handoff Owner'
    })
    consult=command(first_device,'consultation.create',{
        'patient_id':patient['id'],'title':'SYNTHETIC overlapping voice notes'
    })
    payload={'patient_id':patient['id'],'consultation_id':consult['id'],'mime':'audio/wav'}
    first_audio=wav(101)
    second_audio=wav(-103)
    first=command(first_device,'recording.create',{**payload,'device':'synthetic-device-one'})
    first_part=len(first_audio)//2
    request(first_device,'PUT',f"recordings/{first['id']}/chunks/0",content=first_audio[:first_part])
    second=command(second_device,'recording.create',{**payload,'device':'synthetic-device-two'})
    check('distinct numbered notes',first['id']!=second['id'] and [first['data']['number'],second['data']['number']]==[1,2])
    request(second_device,'PUT',f"recordings/{second['id']}/chunks/0",content=second_audio)
    finish_second={'id':second['id'],'expected_chunks':1,'duration':1}
    saved_second=command(second_device,'recording.complete',finish_second,'synthetic-handoff-'+run+'-second')
    check('second device finishes independently',saved_second['data']['status']=='saved')
    first_current=request(first_device,'GET',f"records/{first['id']}/history").json()['current']
    check('first device remains in progress',first_current['data']['status']=='recording')
    check('first chunk retained',request(first_device,'GET',f"recordings/{first['id']}/manifest").json()['received']==[0])
    request(first_device,'PUT',f"recordings/{first['id']}/chunks/1",content=first_audio[first_part:])
    saved_first=command(first_device,'recording.complete',{'id':first['id'],'expected_chunks':2,'duration':2})
    check('first device can finish later',saved_first['data']['status']=='saved')
    for client,note,original in ((first_device,first,first_audio),(second_device,second,second_audio)):
        actual=request(client,'GET',f"recordings/{note['id']}/audio").content
        check('independent original WAV bytes '+note['data']['device'],hashlib.sha256(actual).digest()==hashlib.sha256(original).digest())
    replay=command(second_device,'recording.complete',finish_second,'synthetic-handoff-'+run+'-second')
    check('completion retry is idempotent',replay==saved_second)
    records=request(first_device,'GET','bootstrap').json()['records']
    check('both notes visible on consultation',len([r for r in records if r['kind']=='recording' and r['data']['consultation_id']==consult['id']])==2)
    print('Synthetic V2 handoff acceptance complete. Original Broby untouched.')
