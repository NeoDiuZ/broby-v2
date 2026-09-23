"""Exercise an isolated synthetic clinic through its public, same-origin API.

Creates clearly marked synthetic records; never sends messages or charges cards.
Credentials and persisted test IDs stay in the explicitly supplied private files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid
import httpx

parser=argparse.ArgumentParser()
parser.add_argument('url')
parser.add_argument('--credentials',required=True,type=Path)
parser.add_argument('--state',required=True,type=Path)
parser.add_argument('--verify-only',action='store_true')
parser.add_argument('--audio',type=Path)
args=parser.parse_args()
base=args.url.rstrip('/')
credentials=json.loads(args.credentials.read_text())
client=httpx.Client(base_url=base,timeout=60,headers={'Origin':base})
checks=[]

def check(name,condition):
    if not condition:raise AssertionError(name)
    checks.append(name)
    print('PASS:',name,flush=True)

def request(method,path,**kwargs):
    response=client.request(method,'/api'+path,**kwargs)
    if response.status_code>=400:
        # Do not include URLs with owner capabilities, cookies, or credentials.
        raise AssertionError(f'{method} API returned HTTP {response.status_code}')
    return response

def action(name,payload,key=None):
    return request('POST','/actions',json={'action':name,'payload':payload,'key':key or str(uuid.uuid4())}).json()

def current(record_id):
    return request('GET','/records/'+record_id+'/history').json()['current']

def wait_job(job_id):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        job=request('GET','/jobs/'+job_id).json()
        if job['status'] in ('completed','failed','conflict'):
            check('background job completed',job['status']=='completed')
            return job
        time.sleep(1)
    raise AssertionError('Background job timed out')

for route in ['/','/app','/owner','/privacy']:
    check('website route '+route,client.get(route).status_code==200)
check('both databases and file storage ready',request('GET','/ready').json()['status']=='ready')
check('anonymous clinic access rejected',client.get('/api/bootstrap').status_code==401)
check('forged actor rejected',client.get('/api/v2/patients',headers={'x-actor-id':'clinic-east-admin'}).status_code==401)
check('foreign browser origin rejected',client.post('/api/login',headers={'Origin':'https://invalid.example'},json=credentials).status_code==403)
login=request('POST','/login',json=credentials)
check('secure session established','Secure' in login.headers['set-cookie'])
check('cross-clinic access rejected',client.get('/api/bootstrap',headers={'x-clinic-id':'clinic-river'}).status_code==403)
bootstrap=request('GET','/bootstrap').json()
check('authenticated clinic loaded',bootstrap['actor']['data']['role']=='admin')
check('patient directory loaded',bool(request('GET','/v2/patients').json()['items']))

if args.verify_only:
    state=json.loads(args.state.read_text())
    check('SQLite patient survived redeploy',current(state['patient_id'])['data']['name']==state['patient_name'])
    check('PostgreSQL lab survived redeploy',request('GET',f"/v2/patients/{state['patient_id']}/events/{state['event_id']}").json()['id']==state['event_id'])
    content=request('GET','/files/'+state['attachment_id']).content
    check('uploaded file survived redeploy',hashlib.sha256(content).hexdigest()==state['file_sha256'])
    check('completed job survived redeploy',request('GET','/jobs/'+state['job_id']).json()['status']=='completed')
else:
    run=uuid.uuid4().hex[:8]
    state={'patient_name':'SYNTHETIC Deployment Test '+run}
    patient=action('patient.create',{'name':state['patient_name'],'species':'Dog','owner_name':'Synthetic Test Owner','owner_email':'deployment@example.test'})
    pid=state['patient_id']=patient['id']
    check('new patient projected into PostgreSQL',request('GET','/v2/patients/'+pid).json()['id']==pid)
    consult=action('consultation.create',{'patient_id':pid,'title':'SYNTHETIC deployment verification'})
    cid=state['consultation_id']=consult['id']
    source_payload={'patient_id':pid,'consultation_id':cid,'title':'SYNTHETIC source','text':'Synthetic test: owner reports a normal appetite. No medication was prescribed.','section':'Subjective'}
    source_key=str(uuid.uuid4())
    source=action('source.add',source_payload,source_key)
    check('action retry deduplicated',action('source.add',source_payload,source_key)['id']==source['id'])
    consult=current(cid)
    job=action('summary.generate',{'id':cid,'version':consult['version']})
    state['job_id']=job['id'];wait_job(job['id'])
    pdf=request('GET','/consultations/'+cid+'/pdf').content
    check('consultation PDF generated',pdf.startswith(b'%PDF-'))
    blob=b'SYNTHETIC upload persistence verification. No real patient data.'
    attachment=request('POST','/uploads',data={'patient_id':pid},files={'file':('synthetic.txt',blob,'text/plain')}).json()
    state.update(attachment_id=attachment['id'],file_sha256=hashlib.sha256(blob).hexdigest())
    check('upload downloaded unchanged',request('GET','/files/'+attachment['id']).content==blob)
    lab={'patient_id':pid,'dedupe_key':'smoke:'+run,'occurred_at':'2026-09-23T00:00:00Z','summary':'SYNTHETIC potassium result','actor':{'kind':'system','name':'Deployment verification'},'source':{'kind':'document','id':attachment['id'],'page':1,'text':'Synthetic potassium 5.8 mmol/L, reference 3.5 to 5.1'},'observations':[{'concept':'potassium','name':'Potassium','value':5.8,'unit':'mmol/L','ref_low':3.5,'ref_high':5.1}]}
    event=request('POST','/v2/ingest/lab',json=lab).json()
    state['event_id']=event['id']
    check('lab reference flag calculated',event['event']['observations'][0]['flag']=='high')
    check('lab retry deduplicated',request('POST','/v2/ingest/lab',json=lab).json()['duplicate'])
    check('chart points link to lab event',request('GET',f'/v2/patients/{pid}/observations?concept=potassium').json()['series'][0]['event_id']==event['id'])
    receipt=event['event']['source']['receipt_id']
    check('source receipt resolves',request('GET','/v2/sources/'+receipt).json()['content_url']=='/api/files/'+attachment['id'])
    share=action('share.create',{'patient_id':pid});token=share['id']
    with httpx.Client(base_url=base,headers={'Origin':base},timeout=30) as owner:
        check('owner sees only approved files',owner.get('/api/owner/'+token).json()['files']==[])
        check('unapproved file is protected',owner.get('/api/owner/'+token+'/files/'+attachment['id']).status_code==404)
        intake=owner.post('/api/owner/'+token+'/intake',json={'reason':'Synthetic pre-visit check','key':str(uuid.uuid4())})
        check('owner intake received',intake.status_code==200)
    intake_record=current(intake.json()['id'])
    accepted=action('intake.accept',{'id':intake_record['id'],'version':intake_record['version'],'consultation_id':cid})
    check('owner intake accepted into clinic',accepted['data']['status']=='accepted')
    action('share.revoke',{'token':token})
    check('revoked owner link rejected',client.get('/api/owner/'+token).status_code==404)
    invoice=action('invoice.create',{'patient_id':pid,'items':[{'name':'Synthetic test item','quantity':1,'price_cents':100}]})
    check('invoice PDF generated',request('GET','/invoices/'+invoice['id']+'/pdf').content.startswith(b'%PDF-'))
    state['invoice_id']=invoice['id']
    action('invoice.void',{'id':invoice['id'],'version':invoice['version'],'reason':'Synthetic deployment verification; no real sale'})
    if bootstrap['integrations']['ai']:
        consult=current(cid)
        ai=action('summary.generate',{'id':cid,'version':consult['version'],'mode':'ai'})
        result=wait_job(ai['id'])
        check('live Anthropic returned source-verified excerpts',result['result']['mode']=='source_verified_excerpts')
        state['ai_job_id']=ai['id']
    if args.audio:
        check('speech integration configured',bootstrap['integrations']['transcription'])
        recording=action('recording.create',{'patient_id':pid,'consultation_id':cid,'mime':'audio/wav','device':'synthetic-test'})
        rid=recording['id'];audio=args.audio.read_bytes()
        request('PUT',f'/recordings/{rid}/chunks/0',content=audio)
        action('recording.complete',{'id':rid,'expected_chunks':1,'duration':10})
        speech=action('recording.transcribe',{'id':rid,'language':'en'})
        transcript=wait_job(speech['id'])
        check('live Deepgram transcript persisted',bool(current(transcript['result']['source_id'])['data']['text']))
        state['speech_job_id']=speech['id']
    args.state.parent.mkdir(parents=True,exist_ok=True)
    args.state.write_text(json.dumps(state,indent=2)+'\n');args.state.chmod(0o600)
request('POST','/logout')
check('logout invalidates session',client.get('/api/bootstrap').status_code==401)
print(f'All {len(checks)} hosted checks passed.',flush=True)
