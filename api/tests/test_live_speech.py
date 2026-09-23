"""Growing original containers, queued appends, final publication and recovery."""
import hashlib
from io import BytesIO
import json
import subprocess
import uuid
import wave

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import actions
import audio_windows
import db
import jobs
import main
import providers


def wav(seconds):
    content=BytesIO()
    with wave.open(content,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
        audio.writeframes(b'\0\0'*round(seconds*16000))
    return content.getvalue()


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB',tmp_path/'test.sqlite3')
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr('spine.reader.native_records',lambda *a,**k:[])
    monkeypatch.setattr(providers,'available',lambda:{'transcription':True,'ai':False})
    monkeypatch.setattr(audio_windows,'WINDOW_SECONDS',2)
    db.init()


def act(action,payload,actor='clinic-east-vet',clinic='clinic-east'):
    return actions.execute(action,payload,clinic,actor,str(uuid.uuid4()))


def row(id):
    with db.connection() as c:return db.get(c,id)


def job(id):
    with db.connection() as c:return db.unpack(c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone())


def create():
    return act('recording.create',{'patient_id':'luna','consultation_id':'consult-luna',
                                   'refinement':{'language':'en','diarize':True}})['id']


def put(id,index,content):
    assert TestClient(main.app).put(f'/api/recordings/{id}/chunks/{index}',content=content).status_code==200


def prefix(id,count=1):
    return act('recording.refine',{'id':id,'expected_chunks':count})['id']


def complete(id,count=2):
    return act('recording.complete',{'id':id,'expected_chunks':count,'duration':0})


def provider(monkeypatch):
    calls=[]
    def transcribe(content,mime,language,**options):
        calls.append(hashlib.sha256(content).hexdigest())
        return {'text':f'Synthetic section {len(calls)}','utterances':[{'start':0,'end':.5,'text':'Synthetic speech','speaker':0}],
                'provider':'synthetic','request_id':str(uuid.uuid4())}
    monkeypatch.setattr(providers,'transcribe',transcribe)
    return calls,transcribe


def growing():
    id=create();audio=wav(7);split=44+5*32000
    put(id,0,audio[:split]);return id,audio,split


def test_live_preview_retained_but_not_a_source_then_final_reuses_pcm(monkeypatch):
    calls,_=provider(monkeypatch);id,audio,split=growing();jid=prefix(id)
    jobs.run_job(jid)
    assert job(jid)['status']=='waiting' and len(calls)==1
    first=job(jid)['result']['windows'][0]
    assert job(jid)['result']['provisional'] is True
    assert row('consult-luna')['data']['source_ids']==[]
    assert row(id)['data']['status']=='recording' and not row(id)['data'].get('transcript_source_id')
    assert prefix(id)==jid; jobs.run_job(jid);assert len(calls)==1
    put(id,1,audio[split:]);complete(id)
    assert job(jid)['status']=='queued'
    jobs.run_job(jid);jobs.run_job(jid)
    assert len(calls)==4 and job(jid)['status']=='completed'
    recording=row(id);source=row(recording['data']['transcript_source_id'])
    assert recording['data']['duration']==7
    assert source['data']['refinement_windows'][0]['request_id']==first['request_id']
    assert [u['start'] for u in source['data']['utterances']]==[0,2,4,6]
    assert [u['speaker'] for u in source['data']['utterances']]==['1.0','2.0','3.0','4.0']
    assert row('consult-luna')['data']['source_ids']==[source['id']]
    assert TestClient(main.app).get(f'/api/recordings/{id}/audio').content==audio
    # Replayed completion compares the capture duration, not the decoded duration.
    assert complete(id)['id']==id
    assert act('recording.transcribe',{'id':id})['id']==source['id']


def test_finish_during_provider_call_preserves_new_final_request(monkeypatch):
    calls,normal=provider(monkeypatch);id,audio,split=growing();jid=prefix(id)
    def finish(*a,**kw):
        if not calls:put(id,1,audio[split:]);complete(id)
        return normal(*a,**kw)
    monkeypatch.setattr(providers,'transcribe',finish)
    jobs.run_job(jid)
    assert job(jid)['status']=='queued' and job(jid)['payload']['final'] is True
    assert not row(id)['data'].get('transcript_source_id')
    jobs.run_job(jid)
    assert job(jid)['status']=='completed' and len(calls)==4


def test_provider_failure_preserves_preview_and_retries_only_unfinished(monkeypatch):
    calls,normal=provider(monkeypatch);id,audio,split=growing();jid=prefix(id);jobs.run_job(jid)
    put(id,1,audio[split:]);complete(id)
    monkeypatch.setattr(providers,'transcribe',lambda *a,**k:(_ for _ in ()).throw(providers.ProviderError('offline')))
    with pytest.raises(providers.ProviderError):jobs.run_job(jid)
    assert job(jid)['status']=='queued' and job(jid)['result']['completed_windows']==1
    with db.connection(True) as c:c.execute("UPDATE job_claims SET next_attempt='' WHERE job_id=?",(jid,))
    monkeypatch.setattr(providers,'transcribe',normal);jobs.run_job(jid)
    assert len(calls)==4 and job(jid)['status']=='completed'


def test_changed_pcm_never_promotes_preview_to_medical_source(monkeypatch):
    calls,_=provider(monkeypatch);id,audio,split=growing();jid=prefix(id);jobs.run_job(jid)
    with db.connection(True) as c:
        progress=job(jid)['result'];progress['windows'][0]['pcm_sha256']='different'
        c.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps(progress),jid))
    put(id,1,audio[split:]);complete(id)
    with pytest.raises(audio_windows.AudioValidationError,match='changed on final decoding'):jobs.run_job(jid)
    assert job(jid)['status']=='failed' and len(calls)==1
    assert not row(id)['data'].get('transcript_source_id') and row('consult-luna')['data']['source_ids']==[]


def test_no_full_window_no_provider_request_and_silent_window_checkpointed(monkeypatch):
    calls,normal=provider(monkeypatch);id=create();put(id,0,wav(1));jid=prefix(id);jobs.run_job(jid)
    assert job(jid)['status']=='waiting' and calls==[]
    complete(id,1);jobs.run_job(jid);assert len(calls)==1
    id,audio,split=growing()
    monkeypatch.setattr(providers,'transcribe',lambda *a,**k:{'text':'','utterances':[],'provider':'synthetic','request_id':'silent'})
    jid=prefix(id);jobs.run_job(jid)
    assert job(jid)['result']['windows'][0]['text']==''
    put(id,1,audio[split:]);complete(id)
    monkeypatch.setattr(providers,'transcribe',normal);jobs.run_job(jid)
    source=row(row(id)['data']['transcript_source_id'])
    assert source['data']['utterances'][0]['start']==2


def test_revocation_and_replaced_worker_lease_cannot_checkpoint(monkeypatch):
    calls,normal=provider(monkeypatch);id,_,_=growing();jid=prefix(id)
    def revoke(*a,**kw):
        with db.connection(True) as c:
            member=db.get(c,'clinic-east-vet');db.update(c,member,{**member['data'],'active':False})
        return normal(*a,**kw)
    monkeypatch.setattr(providers,'transcribe',revoke)
    with pytest.raises(HTTPException):jobs.run_job(jid)
    assert job(jid)['status']=='failed' and job(jid)['result']['completed_windows']==0
    with db.connection(True) as c:
        member=db.get(c,'clinic-east-vet');db.update(c,member,{**member['data'],'active':True})
    act('job.retry',{'id':jid})
    def replace(*a,**kw):
        with db.connection(True) as c:c.execute("UPDATE job_claims SET token='replacement' WHERE job_id=?",(jid,))
        return normal(*a,**kw)
    monkeypatch.setattr(providers,'transcribe',replace);jobs.run_job(jid)
    assert job(jid)['result']['completed_windows']==0


def test_prefix_scope_gaps_settings_and_permission_dependency(monkeypatch):
    calls,_=provider(monkeypatch);id=create();put(id,1,wav(5))
    with pytest.raises(HTTPException) as error:prefix(id,2)
    assert error.value.status_code==409
    with pytest.raises(HTTPException) as error:act('recording.refine',{'id':id,'expected_chunks':2},'clinic-west-vet','clinic-west')
    assert error.value.status_code==404
    with pytest.raises(HTTPException):act('recording.create',{'patient_id':'luna','consultation_id':'consult-luna','refinement':{'diarize':'true'}})
    with db.connection(True) as c:
        clinic=db.get(c,'clinic-east');db.update(c,clinic,{**clinic['data'],'locked_features':['recording.transcribe']})
    with pytest.raises(HTTPException) as error:prefix(id)
    assert error.value.status_code==403
    with pytest.raises(HTTPException):create()
    # Capture alone remains permitted when speech is locked.
    assert act('recording.create',{'patient_id':'luna','consultation_id':'consult-luna'})['id']
    assert calls==[]


def test_bad_prefix_checksums_never_reach_provider(monkeypatch):
    calls,_=provider(monkeypatch);id,_,_=growing();jid=prefix(id)
    with db.connection(True) as c:c.execute("UPDATE chunks SET sha256='tampered' WHERE recording_id=?",(id,))
    with pytest.raises(audio_windows.AudioValidationError,match='checksum'):jobs.run_job(jid)
    assert calls==[] and job(jid)['status']=='failed'


@pytest.mark.parametrize('extension,codec,extra',[('webm','libopus',['-live','1']),('mp4','aac',['-movflags','frag_keyframe+empty_moov+default_base_moof','-frag_duration','1000000'])])
def test_fragmented_browser_containers_reuse_identical_full_windows(tmp_path,monkeypatch,extension,codec,extra):
    calls,_=provider(monkeypatch)
    source=tmp_path/'source.wav';source.write_bytes(wav(20))
    target=tmp_path/('source.'+extension)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(source),'-c:a',codec,*extra,str(target)],check=True)
    audio=target.read_bytes();split=int(len(audio)*.7)
    if extension=='mp4':
        # Browser MP4 chunks end at complete fragments; incomplete ones wait.
        offset=0;ends=[]
        while offset+8<len(audio):
            size=int.from_bytes(audio[offset:offset+4],'big')
            if size<8:break
            offset+=size;ends.append(offset)
        split=max(end for end in ends if end<split)
    id=create();put(id,0,audio[:split]);jid=prefix(id)
    jobs.run_job(jid)
    count=job(jid)['result']['completed_windows']
    assert count>=1 and job(jid)['status']=='waiting'
    receipts=[w['request_id'] for w in job(jid)['result']['windows']]
    put(id,1,audio[split:]);complete(id);jobs.run_job(jid)
    assert job(jid)['status']=='completed'
    source=row(row(id)['data']['transcript_source_id'])['data']
    assert [w['request_id'] for w in source['refinement_windows'][:count]]==receipts
    assert len(calls)==len(source['refinement_windows'])


def test_undecodable_growing_container_waits_but_final_fails(monkeypatch):
    calls,_=provider(monkeypatch);id=create();put(id,0,b'\x1aE\xdf\xa3' + b'broken'*20);jid=prefix(id)
    jobs.run_job(jid);assert job(jid)['status']=='waiting'
    complete(id,1)
    with pytest.raises(audio_windows.AudioValidationError):jobs.run_job(jid)
    assert job(jid)['status']=='failed' and calls==[]
