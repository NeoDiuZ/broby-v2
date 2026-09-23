"""Durable source-assembly jobs. No fabricated AI response when no model is connected."""
import json, threading, time, secrets
from datetime import datetime,timezone,timedelta
from pathlib import Path
import providers
from db import connection, get, update, now, unpack, uid

def authorize(c,clinic,actor,action):
    from actions import authorize as check
    return check(c,clinic,actor,action)

stop=threading.Event()
def lease_time(seconds=90):return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()
def claim_job(job_id):
    with connection(True) as c:
        job=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not job or job['status'] not in ('queued','running'):return None
        old=c.execute('SELECT * FROM job_claims WHERE job_id=?',(job_id,)).fetchone()
        if old and (old['lease_until']>now() or old['next_attempt']>now()):return None
        token=secrets.token_hex(24);attempts=(old['attempts'] if old else 0)+1
        c.execute('INSERT OR REPLACE INTO job_claims VALUES(?,?,?,?,?,?)',(job_id,token,lease_time(),attempts,'',None))
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
                error='Provider request failed; retry scheduled' if retry else 'Job failed; review permissions and provider configuration before retrying'
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
def loop():
    while not stop.wait(.4):
        with connection() as c:
            ids=[r[0] for r in c.execute("SELECT j.id FROM jobs j LEFT JOIN job_claims q ON j.id=q.job_id WHERE j.status IN ('queued','running') AND (q.job_id IS NULL OR (q.lease_until<=? AND q.next_attempt<=?)) ORDER BY j.created_at LIMIT 5",(now(),now()))]
        for id in ids:
            try:run_job(id)
            except Exception:pass  # run_job persists the bounded, sanitized failure state.


def run_transcription(job,payload,token):
    from actions import dispatch,owned,PERMISSIONS,fail
    with connection() as c:
        r=owned(c,payload['recording_id'],job['clinic_id'],'recording')
        if r['data'].get('transcript_source_id'):
            with connection(True) as writer:writer.execute("UPDATE jobs SET status='completed',updated_at=? WHERE id=?",(now(),job['id']))
            return
        paths=[row[0] for row in c.execute('SELECT path FROM chunks WHERE recording_id=? ORDER BY chunk_index',(r['id'],))]
    output=providers.transcribe(b''.join(Path(x).read_bytes() for x in paths),r['data'].get('mime','audio/webm'),payload['language'])
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
        update(c,source,{**source['data'],'utterances':output['utterances'],'provider':output['provider'],'provider_request_id':output['request_id'],'machine_transcript':True})
        update(c,current,{**current['data'],'transcript_source_id':source['id']})
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),job['clinic_id'],payload['actor_id'],'recording.transcribe.complete',source['id'],now()))
        c.execute("UPDATE jobs SET status='completed',result=?,updated_at=? WHERE id=?",(json.dumps({'source_id':source['id'],'mode':'transcription'}),now(),job['id']))
