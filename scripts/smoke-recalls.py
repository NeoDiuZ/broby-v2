"""Synthetic recall acceptance. No external delivery; existing records stay unchanged."""
import argparse,json,uuid
from pathlib import Path
import httpx
from verification_records import stable_record
p=argparse.ArgumentParser();p.add_argument('base_url');p.add_argument('--credentials',required=True,type=Path);p.add_argument('--state',required=True,type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args()
if a.state.exists() and not a.verify_only:raise SystemExit('Fixture already exists; use --verify-only, do not recreate it.')
s=json.loads(a.state.read_text()) if a.verify_only else {'tag':uuid.uuid4().hex[:8],'phase':'starting'}
checks=[]
def save():
 a.state.parent.mkdir(parents=True,exist_ok=True);a.state.write_text(json.dumps(s,indent=2));a.state.chmod(0o600)
def check(ok,label):
 if not ok:raise AssertionError(label)
 checks.append(label);print('PASS '+label,flush=True)
base=a.base_url.rstrip('/')
with httpx.Client(base_url=base+'/api/',headers={'Origin':base,'x-clinic-id':'clinic-east'},timeout=60) as c:
 def req(method,path,expected=200,**kw):
  r=c.request(method,path,**kw)
  if r.status_code!=expected:raise AssertionError(f'{method} {path} expected {expected}, received {r.status_code}')
  return r.json()
 def act(action,payload,expected=200,key=None):return req('POST','actions',expected,json={'action':action,'payload':payload,'key':key or str(uuid.uuid4())})
 def records():return req('GET','bootstrap')['records']
 def row(id):return next(r for r in records() if r['id']==id)
 credentials=json.loads(a.credentials.read_text());req('POST','login',json={k:credentials[k] for k in ('username','password')})
 try:
  check(req('GET','ready')['status']=='ready','both stores and file volume ready')
  if not a.verify_only:
   s['before']=records();save();s['patients']=[];s['reminders']=[]
   for label in ['A','B']:
    patient=act('patient.create',{'name':'SYNTHETIC Recall '+label+' '+s['tag'],'species':'Cat','owner_name':'SYNTHETIC Recall Owner '+label+' '+s['tag']});s['patients'].append(patient['id']);save()
    r=act('reminder.create',{'patient_id':patient['id'],'title':'SYNTHETIC recall '+s['tag'],'due':'2099-01-05'});s['reminders'].append(r['id']);save()
   s['filter']={'start':'2099-01-01','end':'2099-01-31','query':'SYNTHETIC recall '+s['tag']};save()
   review=req('POST','recalls/preview',json=s['filter']);check(len(review['items'])==2,'review finds exactly the two synthetic reminders')
   data={**s['filter'],'title':'SYNTHETIC recall acceptance '+s['tag'],'digest':review['digest'],'reminder_ids':s['reminders']};key='synthetic-recall-'+s['tag']
   camp=act('recall.prepare',data,key=key);s['campaign']=camp['id'];s['outbox']=[i['outbox_id'] for i in camp['data']['items']];save()
   check(act('recall.prepare',data,key=key)==camp,'same-key retry preserves exactly one campaign')
   act('recall.prepare',data,409);check(True,'stale review cannot duplicate drafts')
   first=s['outbox'][0];owner=row(row(first)['data']['owner_id'])
   delivery=req('GET','outbox/'+first+'/delivery-review');check(delivery['body']==row(first)['data']['body'],'manual review returns the exact saved message')
   act('owner.recall_preference',{'id':owner['id'],'version':owner['version'],'opt_out':True,'reason':'SYNTHETIC explicit opt-out'});s['opted_out_owner']=owner['id'];save()
   check(req('GET','recalls/'+camp['id'])['counts']=={'cancelled':1,'pending':1},'owner opt-out cancels only their pending recall')
   req('GET','outbox/'+first+'/delivery-review',409)
   act('message.complete',{'id':first,'version':row(first)['version']},409);check(True,'cancelled opt-out draft cannot be opened or marked delivered')
   act('recall.cancel',{'id':camp['id'],'version':camp['version'],'reason':'SYNTHETIC acceptance complete'})
   for id in s['reminders']:
    r=row(id);act('reminder.cancel',{'id':id,'version':r['version']})
   s['phase']='complete';save()
  check(s['phase']=='complete','acceptance fixture completed and cleaned up')
  campaign=req('GET','recalls/'+s['campaign']);check(campaign['data']['status']=='cancelled' and campaign['counts']=={'cancelled':2},'campaign and both cancellation receipts persist')
  check(all(row(id)['data']['status']=='cancelled' for id in s['reminders']),'synthetic reminders are closed')
  check(len([r for r in records() if r['kind']=='outbox' and r['data'].get('campaign_id')==s['campaign']])==2,'exactly two drafts remain, with no duplicate delivery')
  check(row(s['opted_out_owner'])['data']['recall_opt_out'] is True,'owner opt-out and reason persist')
  check(all(x['blocked_reason'] for x in req('POST','recalls/preview',json=s['filter'])['items']),'completed fixture remains excluded from future preparation')
  current={r['id']:r for r in records()};check(all(stable_record(r)==stable_record(current.get(r['id'])) for r in s['before']),'all unrelated original records retain their content')
  check(not req('GET','integrations/twilio/status')['sending_enabled'],'customer and trial sending remain disabled')
  s['checks']=checks;save()
 finally:c.post('logout')
print(f'{len(checks)} recall acceptance checks passed; no provider messages sent.')
