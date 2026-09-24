"""Synthetic credentialed read-boundary acceptance; unrelated rows remain exact."""
import argparse,json,secrets,uuid
from pathlib import Path
import httpx
from verification_records import stable_record
p=argparse.ArgumentParser();p.add_argument('base_url');p.add_argument('--credentials',required=True,type=Path);p.add_argument('--state',required=True,type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args()
if a.state.exists() and not a.verify_only:raise SystemExit('Fixture exists. Use --verify-only; do not create it twice.')
s=json.loads(a.state.read_text()) if a.verify_only else {'tag':uuid.uuid4().hex[:8],'phase':'starting'}
checks=[]
def save():
 a.state.parent.mkdir(parents=True,exist_ok=True);a.state.write_text(json.dumps(s,indent=2));a.state.chmod(0o600)
def check(value,label):
 if not value:raise AssertionError(label)
 checks.append(label);print('PASS '+label,flush=True)
base=a.base_url.rstrip('/')
with httpx.Client(base_url=base+'/api/',headers={'Origin':base,'x-clinic-id':'clinic-east'},timeout=60) as admin, httpx.Client(base_url=base+'/api/',headers={'Origin':base,'x-clinic-id':'clinic-east'},timeout=60) as staff:
 def req(c,method,path,expected=200,**kw):
  r=c.request(method,path,**kw)
  if r.status_code!=expected:raise AssertionError(f'{method} {path}: expected {expected}, received {r.status_code}')
  return r.json()
 def act(action,payload,key=None):return req(admin,'POST','actions',json={'action':action,'payload':payload,'key':key or str(uuid.uuid4())})
 def records():return req(admin,'GET','bootstrap')['records']
 def member():return next(r for r in records() if r['id']==s['member'])
 def change(values):
  r=member();return act('access.member',{'id':r['id'],'version':r['version'],'restrictions':values,'reason':'SYNTHETIC access acceptance '+s['tag']})
 creds=json.loads(a.credentials.read_text());req(admin,'POST','login',json={k:creds[k] for k in ('username','password')})
 try:
  check(req(admin,'GET','ready')['status']=='ready','database and storage ready')
  if not a.verify_only:
   s['before']=records();save()
   m=act('member.save',{'name':'SYNTHETIC read access '+s['tag'],'role':'admin'});s['member']=m['id'];save()
   invitation=req(admin,'POST','account/invitations',json={'member_id':m['id']})
   credentials={'username':'synthetic_access_'+s['tag'],'password':secrets.token_urlsafe(30)}
   req(staff,'POST','account/invitations/accept',json={**credentials,'token':invitation['token']})
   req(staff,'POST','login',json=credentials)
   full=req(staff,'GET','bootstrap');check(len(full['read_permissions'])==8,'synthetic account initially sees eight permitted areas')
   question={'message':'outstanding invoices','key':'read-access-question-'+s['tag']}
   # This acceptance deliberately avoids a provider/model call. Legacy saved
   # conversation bypass is covered by regression tests with a stubbed provider.
   change(['read.billing']);restricted=req(staff,'GET','bootstrap')
   check('read.billing' not in restricted['read_permissions'],'administrator restriction reaches the existing session')
   check(not any(r['kind'] in ['invoice','payment','refund','credit_note','event','source','recording','attachment','dashboard'] for r in restricted['records']),'bootstrap omits billing and composite record bodies')
   check(not any(x.startswith(('invoice.','payment.','stripe.','credit_note.')) for x in restricted['permissions']),'dependent financial writes are unavailable')
   for path in ['export','backup','audit','assistant/conversations','files/not-present','recordings/not-present/audio','records/not-present/history','v2/patients/not-present/timeline','invoices/not-present/pdf','reports/financial','dashboards/not-present']:
    req(staff,'GET',path,403)
   req(staff,'POST','assistant',403,json=question);check(True,'twelve direct and composite bypass paths return 403')
   req(staff,'GET','patients');check(True,'permitted patient directory remains available')
   req(staff,'POST','actions',403,json={'action':'invoice.create','payload':{},'key':'blocked-write-'+s['tag']});check(True,'forged financial write is denied before payload execution')
   change([]);check(len(req(staff,'GET','bootstrap')['read_permissions'])==8,'restoring synthetic access takes effect without signing in again')
   change(['read.billing']);req(staff,'POST','logout');req(staff,'POST','login',json=credentials)
   check('read.billing' not in req(staff,'GET','bootstrap')['read_permissions'],'restriction survives a fresh password session')
   r=member();act('member.save',{'id':r['id'],'version':r['version'],'name':r['data']['name'],'role':'admin','active':False})
   req(staff,'GET','bootstrap',403);check(True,'cleanup deactivates the synthetic membership and invalidates its session')
   s['phase']='complete';save()
  check(s['phase']=='complete','acceptance fixture completed')
  m=member();check(not m['data']['active'] and m['data']['read_restrictions']==['read.billing'],'deactivated fixture retains its restriction and reason')
  history=req(admin,'GET','records/'+m['id']+'/history');check(len(history['versions'])>=4,'access transition history is durable')
  current={r['id']:r for r in records()};check(all(stable_record(current.get(r['id']))==stable_record(r) for r in s['before']),'all pre-existing records retain their exact content')
  check(not req(admin,'GET','integrations/twilio/status')['sending_enabled'],'external messaging remains disabled')
  s['checks']=checks;save()
 finally:
  staff.post('logout');admin.post('logout')
print(f'{len(checks)} access acceptance checks passed; no payment or message sent.')
