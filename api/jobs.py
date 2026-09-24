"""Durable source-assembly jobs. No fabricated AI response when no model is connected."""
import json, threading, time, secrets
from datetime import datetime,timezone,timedelta
import providers
import audio_windows
from db import connection, get, update, now, unpack, uid, upsert

def authorize(c,clinic,actor,action):
    from actions import authorize as check
    return check(c,clinic,actor,action)

def lease_time(seconds=90):return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()
def claim_job(job_id):
    with connection(True) as c:
        job=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not job or job['status'] not in ('queued','running'):return None
        old=c.execute('SELECT * FROM job_claims WHERE job_id=?',(job_id,)).fetchone()
        if old and (old['lease_until']>now() or old['next_attempt']>now()):return None
        token=secrets.token_hex(24);attempts=(old['attempts'] if old else 0)+1
        upsert(c,'job_claims',{'job_id':job_id,'token':token,'lease_until':lease_time(),'attempts':attempts,'next_attempt':'','last_error':None},['job_id'])
        c.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?",(now(),job_id))
        return token

def owns_claim(c,job_id,token):
    row=c.execute('SELECT token,lease_until FROM job_claims WHERE job_id=?',(job_id,)).fetchone()
    return row and row['token']==token and row['lease_until']>now()

def run_job(job_id):
    token=claim_job(job_id)
    if not token:return
    done=threading.Event()
    def heartbeat():
        while not done.wait(20):
            with connection(True) as c:
                c.execute('UPDATE job_claims SET lease_until=? WHERE job_id=? AND token=?',(lease_time(),job_id,token))
    keeper=threading.Thread(target=heartbeat,daemon=True);keeper.start()
    try:return run_claimed(job_id,token)
    except Exception as exc:
        # Provider failures can recover; authorization/validation failures require attention.
        with connection(True) as c:
            if owns_claim(c,job_id,token):
                attempts=c.execute('SELECT attempts FROM job_claims WHERE job_id=?',(job_id,)).fetchone()[0]
                retry=isinstance(exc,providers.ProviderError) and attempts<3
                error=str(exc) if isinstance(exc,audio_windows.AudioValidationError) else 'Provider request failed; retry scheduled' if retry else 'Job failed; review permissions and provider configuration before retrying'
                c.execute('UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=?',('queued' if retry else 'failed',error,now(),job_id))
                c.execute('UPDATE job_claims SET lease_until=?,next_attempt=?,last_error=? WHERE job_id=? AND token=?',('',lease_time(30*2**(attempts-1)) if retry else '',error,job_id,token))
        raise
    finally:
        done.set();keeper.join(timeout=2)
        with connection(True) as c:c.execute('UPDATE job_claims SET lease_until=? WHERE job_id=? AND token=?',('',job_id,token))

def run_claimed(job_id,token):
    with connection(True) as c:
        job=unpack(c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())
        if not job or job['status'] not in ('queued','running'): return
        c.execute('UPDATE jobs SET status=?,updated_at=? WHERE id=?',('running',now(),job_id))
        snapshot=job['payload']
        authorize(c,job['clinic_id'],snapshot.get('actor_id'),'recording.transcribe' if snapshot.get('kind')=='transcription' else 'summary.generate')
        sources=[get(c,id,job['clinic_id']) for id in snapshot.get('source_ids',[])]
    if snapshot.get('kind')=='transcription':
        return run_transcription(job,snapshot,token)
    # Conservative local mode: quote original text, retaining source receipts.
    # It does not infer facts, diagnoses, or treatments.
    sections=[]
    for name in snapshot['sections']:
        selected=[s for s in sources if s and s['data'].get('section')==name]
        if selected: sections.append({'name':name,'text':'\n\n'.join(s['data']['text'] for s in selected),'source_ids':[s['id'] for s in selected]})
    extra=[s for s in sources if s and s['data'].get('section') not in snapshot['sections']]
    if extra: sections.append({'name':'Additional findings','text':'\n\n'.join(s['data']['text'] for s in extra),'source_ids':[s['id'] for s in extra]})
    omitted=[]
    mode='verbatim_source_assembly'
    if snapshot.get('mode')=='ai':
        sections,omitted=providers.assemble(sources,snapshot['sections'],snapshot.get('retention','medical'));mode='source_verified_excerpts'
    with connection(True) as c:
        if not owns_claim(c,job_id,token):return
        authorize(c,job['clinic_id'],snapshot.get('actor_id'),'summary.generate')
        consult=get(c,job['consultation_id'],job['clinic_id'])
        result={'summary':sections,'mode':mode,'omitted_sources':omitted,'source_ids':snapshot['source_ids'],'context_preference':snapshot.get('retention','medical')}
        if not consult or consult['version']!=snapshot['version']:
            c.execute('UPDATE jobs SET status=?,result=?,error=?,updated_at=? WHERE id=?',('conflict',json.dumps(result),'The consultation changed while this job ran. Newer edits were preserved; regenerate from the latest record.',now(),job_id))
            return
        d=consult['data']; d.update(summary=sections,template_id=snapshot['template_id'],generated_revision=snapshot['input_revision'],generation_mode=mode,context_preference=snapshot.get('retention','medical'),omitted_sources=omitted,status='in_progress')
        update(c,consult,d)
        c.execute('UPDATE jobs SET status=?,result=?,updated_at=? WHERE id=?',('completed',json.dumps(result),now(),job_id))
def tick():
    with connection() as c:
        ids=[r[0] for r in c.execute("SELECT j.id FROM jobs j LEFT JOIN job_claims q ON j.id=q.job_id WHERE j.status IN ('queued','running') AND (q.job_id IS NULL OR (q.lease_until<=? AND q.next_attempt<=?)) ORDER BY j.created_at LIMIT 5",(now(),now()))]
    for id in ids:
        try:run_job(id)
        except Exception:
            # Task failures are durable and do not stop other jobs. A failure
            # before that state was saved is a worker fault, not a healthy tick.
            with connection() as c:
                row=c.execute('SELECT status,error FROM jobs WHERE id=?',(id,)).fetchone()
            if not row or row['status'] not in ('queued','failed') or not row['error']:
                raise


def transcribe_windows(job,payload,token,chunks):
    """Checkpoint each provider result before requesting the next window.

    Recovered jobs reuse completed windows. Speaker numbers are local to a
    provider request, so separate windows never silently identify the same person.
    """
    with audio_windows.prepare(chunks) as audio:
        plan={'audio_sha256':audio.audio_hash,'window_seconds':audio_windows.WINDOW_SECONDS,
              'total_windows':audio.count,'duration':audio.duration,
              'language':payload['language'],'diarize':payload.get('diarize',True)}
        progress=job.get('result') or {}
        if progress.get('plan') and progress['plan']!=plan:
            raise audio_windows.AudioValidationError('The saved speech window plan changed. Review the original audio before retrying.')
        windows=list(progress.get('windows',[]))
        if [w['index'] for w in windows]!=list(range(len(windows))) or len(windows)>audio.count:
            raise audio_windows.AudioValidationError('Saved speech progress is inconsistent. The original audio is preserved.')
        def save_progress(c):
            c.execute('UPDATE jobs SET result=?,updated_at=? WHERE id=?',
                      (json.dumps({'mode':'transcription','plan':plan,'completed_windows':len(windows),
                                   'total_windows':audio.count,'windows':windows}),now(),job['id']))
        with connection(True) as c:
            if not owns_claim(c,job['id'],token):return None
            save_progress(c)
        for index in range(len(windows),audio.count):
            with connection() as c:
                if not owns_claim(c,job['id'],token):return None
                authorize(c,job['clinic_id'],payload['actor_id'],'recording.transcribe')
            start,end=audio.bounds(index)
            output=providers.transcribe(audio.read(index),'audio/wav',payload['language'],
                                        diarize=payload.get('diarize',True),allow_empty=True)
            utterances=[]
            for segment in output['utterances']:
                if segment['start']>end-start or segment['end']>end-start+.5:
                    raise providers.ProviderError('Speech timestamps exceed their audio window')
                speaker=segment.get('speaker')
                utterances.append({**segment,'start':start+segment['start'],
                    'end':min(start+segment['end'],end),'window_index':index,
                    'speaker':(f'{index+1}.{speaker}' if audio.count>1 else speaker) if speaker is not None else None})
            windows.append({'index':index,'start':start,'end':end,**output,'utterances':utterances})
            with connection(True) as c:
                if not owns_claim(c,job['id'],token):return None
                authorize(c,job['clinic_id'],payload['actor_id'],'recording.transcribe')
                save_progress(c)
        text='\n\n'.join(w['text'] for w in windows if w['text'].strip())
        if not text:
            raise audio_windows.AudioValidationError('No speech was recognized. The original audio is preserved; listen to it before creating a replacement recording.')
        return {'text':text,'utterances':[s for w in windows for s in w['utterances']],
                'provider':'deepgram','request_id':windows[0]['request_id'] if len(windows)==1 else None,
                'duration':audio.duration,'diarize':plan['diarize'],
                'refinement_windows':[{k:w[k] for k in ('index','start','end','provider','request_id')} for w in windows]}


def run_transcription(job,payload,token):
    from actions import dispatch,owned,PERMISSIONS,fail
    with connection() as c:
        r=owned(c,payload['recording_id'],job['clinic_id'],'recording')
        if r['data'].get('transcript_source_id'):
            with connection(True) as writer:writer.execute("UPDATE jobs SET status='completed',updated_at=? WHERE id=?",(now(),job['id']))
            return
        chunks=[dict(row) for row in c.execute('SELECT * FROM chunks WHERE recording_id=? ORDER BY chunk_index',(r['id'],))]
        expected=payload['prefix_chunks'] if payload.get('continuous') else r['data']['expected_chunks']
        if payload.get('continuous'):
            chunks=[ch for ch in chunks if ch['chunk_index']<expected]
        if [ch['chunk_index'] for ch in chunks]!=list(range(expected)):
            raise audio_windows.AudioValidationError('Recording has missing chunks; restore the original before transcription.')
        if payload.get('final') and (r['data']['status']!='saved' or expected!=r['data']['expected_chunks']):
            raise audio_windows.AudioValidationError('Finish uploading the complete audio before publishing its transcript.')
    if payload.get('continuous'):
        from live_speech import transcribe_prefix
        output=transcribe_prefix(job,payload,token,chunks)
    else:
        output=transcribe_windows(job,payload,token,chunks)
    if output is None:return
    with connection(True) as c:
        if not owns_claim(c,job['id'],token):return
        authorize(c,job['clinic_id'],payload['actor_id'],'recording.transcribe')
        member=owned(c,payload['actor_id'],job['clinic_id'],'member')
        if not member['data']['active'] or member['data']['role'] not in PERMISSIONS['source.add']:fail('Requesting member no longer has capture permission',403)
        current=owned(c,r['id'],job['clinic_id'],'recording')
        if current['data'].get('transcript_source_id'):
            c.execute("UPDATE jobs SET status='completed',updated_at=? WHERE id=?",(now(),job['id']));return
        locked=owned(c,job['clinic_id'],job['clinic_id'],'clinic')['data'].get('locked_features',[])
        if member['data']['role']!='admin' and any(a in locked for a in ('source.add','recording.transcribe')):fail('Capture was locked while this job ran',403)
        source=dispatch(c,'source.add',{'patient_id':payload['patient_id'],'consultation_id':job['consultation_id'],'recording_id':r['id'],'title':f"Voice note {r['data']['number']} · machine transcript",'text':output['text'],'section':'Subjective','category':'transcript'},job['clinic_id'],payload['actor_id'])
        update(c,source,{**source['data'],'utterances':output['utterances'],'provider':output['provider'],'provider_request_id':output['request_id'],'machine_transcript':True,'diarize':output['diarize'],'refinement_windows':output['refinement_windows']})
        update(c,current,{**current['data'],'transcript_source_id':source['id'],'duration':output['duration']})
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),job['clinic_id'],payload['actor_id'],'recording.transcribe.complete',source['id'],now()))
        c.execute("UPDATE jobs SET status='completed',result=?,updated_at=? WHERE id=?",(json.dumps({'source_id':source['id'],'mode':'transcription','completed_windows':len(output['refinement_windows']),'total_windows':len(output['refinement_windows'])}),now(),job['id']))
