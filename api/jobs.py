"""Durable source-assembly jobs. No fabricated AI response when no model is connected."""
import json, threading, time
from pathlib import Path
import providers
from db import connection, get, update, now, unpack, uid

def authorize(c,clinic,actor,action):
    from actions import owned,PERMISSIONS,fail
    member=owned(c,actor,clinic,'member')
    if not member['data'].get('active') or member['data']['role'] not in PERMISSIONS[action]:fail('Requesting member no longer has permission for this job',403)
    locked=owned(c,clinic,clinic,'clinic')['data'].get('locked_features',[])
    if member['data']['role']!='admin' and action in locked:fail('This job was locked by the clinic administrator',403)

stop=threading.Event()
def run_job(job_id):
    with connection(True) as c:
        job=unpack(c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())
        if not job or job['status'] not in ('queued','running'): return
        c.execute('UPDATE jobs SET status=?,updated_at=? WHERE id=?',('running',now(),job_id))
        snapshot=job['payload']
        authorize(c,job['clinic_id'],snapshot.get('actor_id'),'recording.transcribe' if snapshot.get('kind')=='transcription' else 'summary.generate')
        sources=[get(c,id,job['clinic_id']) for id in snapshot.get('source_ids',[])]
    if snapshot.get('kind')=='transcription':
        return run_transcription(job,snapshot)
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
        authorize(c,job['clinic_id'],snapshot.get('actor_id'),'summary.generate')
        consult=get(c,job['consultation_id'],job['clinic_id'])
        result={'summary':sections,'mode':mode,'omitted_sources':omitted,'source_ids':snapshot['source_ids']}
        if not consult or consult['version']!=snapshot['version']:
            c.execute('UPDATE jobs SET status=?,result=?,error=?,updated_at=? WHERE id=?',('conflict',json.dumps(result),'The consultation changed while this job ran. Newer edits were preserved; regenerate from the latest record.',now(),job_id))
            return
        d=consult['data']; d.update(summary=sections,template_id=snapshot['template_id'],generated_revision=snapshot['input_revision'],generation_mode=mode,omitted_sources=omitted,status='in_progress')
        update(c,consult,d)
        c.execute('UPDATE jobs SET status=?,result=?,updated_at=? WHERE id=?',('completed',json.dumps(result),now(),job_id))
def loop():
    with connection(True) as c: c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
    while not stop.wait(.4):
        with connection() as c: ids=[r[0] for r in c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 5")]
        for id in ids:
            try: run_job(id)
            except Exception as e:
                with connection(True) as c: c.execute('UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=?',('failed',str(e),now(),id))


def run_transcription(job,payload):
    from actions import dispatch,owned,PERMISSIONS,fail
    with connection() as c:
        r=owned(c,payload['recording_id'],job['clinic_id'],'recording')
        if r['data'].get('transcript_source_id'):
            with connection(True) as writer:writer.execute("UPDATE jobs SET status='completed',updated_at=? WHERE id=?",(now(),job['id']))
            return
        paths=[row[0] for row in c.execute('SELECT path FROM chunks WHERE recording_id=? ORDER BY chunk_index',(r['id'],))]
    output=providers.transcribe(b''.join(Path(x).read_bytes() for x in paths),r['data'].get('mime','audio/webm'),payload['language'])
    with connection(True) as c:
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
