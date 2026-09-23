#!/usr/bin/env python3
"""Synthetic same-origin release acceptance; no real payments, lab feed or messages."""
import argparse,json,uuid,time,hmac,hashlib
from pathlib import Path
from datetime import datetime,timezone
import httpx
p=argparse.ArgumentParser();p.add_argument('base_url');p.add_argument('--credentials',type=Path);p.add_argument('--state',required=True,type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args()
c=httpx.Client(base_url=a.base_url.rstrip('/')+'/api/',timeout=90,headers={'x-clinic-id':'clinic-east','x-actor-id':'clinic-east-admin'})
checks=[];state={};links=[];hook=None

def check(ok,label):
    if not ok:raise AssertionError(label)
    checks.append(label);print('PASS '+label,flush=True)
def req(method,path,expected=200,**kwargs):
    r=c.request(method,path,**kwargs)
    if r.status_code!=expected:raise AssertionError(f'{method} expected {expected}, received {r.status_code}: '+r.text[:200])
    return r.json()
def act(action,payload,key=None):return req('POST','actions',json={'action':action,'payload':payload,'key':key or str(uuid.uuid4())})
def record(id):return next(r for r in req('GET','bootstrap')['records'] if r['id']==id)
def save():a.state.parent.mkdir(parents=True,exist_ok=True);a.state.write_text(json.dumps(state,indent=2));a.state.chmod(0o600)
if a.credentials:
    credentials=json.loads(a.credentials.read_text());req('POST','login',json={'username':credentials['username'],'password':credentials['password']})
try:
    check(req('GET','ready')['status']=='ready','deployment storage ready')
    if a.verify_only:
        state=json.loads(a.state.read_text())
        ev=req('GET','v2/patients/'+state['patient']+'/events/'+state['event'])
        check([o['value_type'] for o in sorted(ev['observations'],key=lambda x:x['concept'])]==['boolean','text','number'],'typed facts survive restart')
        check(record(state['stock'])['data']['stock']==4,'lot balances survive restart')
        check(req('GET','dashboards/'+state['view'])['result']['count']==3,'saved query survives restart')
        check(record(state['payment'])['data']['refunded_cents']==100,'synthetic payment reconciliation survives restart')
        check(req('GET','operations/status')['sending_enabled'] is False,'outbound sending remains disabled')
        print(str(len(checks))+' persistence checks passed');raise SystemExit()
    suffix=uuid.uuid4().hex[:8]
    patient=act('patient.create',{'name':'SYNTHETIC Hard Workflows '+suffix,'species':'Dog','owner_name':'Synthetic Owner '+suffix,'date_of_birth':'2022-05-14'});pid=patient['id'];state['patient']=pid;save()
    payload={'patient_id':pid,'dedupe_key':'hard:'+suffix,'occurred_at':datetime.now(timezone.utc).isoformat(),'summary':'Synthetic typed laboratory report','source':{'kind':'document','id':'synthetic-'+suffix,'page':1,'text':'Synthetic report. Potassium 5.8 mmol/L, supplied range 3.5–5.1. Culture: no growth. Parasites seen: false.'},'observations':[{'concept':'potassium','name':'Potassium','value':5.8,'unit':'mmol/L','ref_low':3.5,'ref_high':5.1},{'concept':'culture_finding','name':'culture_finding','value':'No growth','value_type':'text','unit':''},{'concept':'parasites_seen','name':'parasites_seen','value':False,'value_type':'boolean','unit':''}]}
    # Codes sort boolean / text / number for persistence assertion.
    payload['observations'][1]['concept']='hard_culture';payload['observations'][1]['name']='Synthetic culture'
    payload['observations'][2]['concept']='hard_boolean';payload['observations'][2]['name']='Synthetic parasites seen'
    event=act('test.lab.receive',payload);state['event']=event['id'];save()
    check(act('test.lab.receive',payload)['duplicate'],'identical lab delivery deduplicated')
    req('POST','actions',expected=409,json={'action':'test.lab.receive','payload':{**payload,'summary':'Changed content'},'key':str(uuid.uuid4())})
    check(True,'conflicting lab replay rejected')
    values=event['event']['observations'];check(len(values)==3 and any(o['value'] is False for o in values),'numeric text and boolean facts persisted')
    check(any(o['flag']=='high' for o in values) and all(o['flag'] is None for o in values if o['value_type']!='number'),'only supplied numeric range causes a flag')
    answer=req('POST','assistant',json={'patient_id':pid,'message':'Show all recorded observations for this patient'})
    check(any(r['data'].get('native_spine') for r in answer.get('sources',[])),'factual assistant retrieves native PostgreSQL facts')
    view=act('dashboard.save',{'name':'SYNTHETIC live observations '+suffix,'query':{'kind':'observation','patient_id':pid}});state['view']=view['id']
    check(req('GET','dashboards/'+view['id'])['result']['count']==3,'saved view queries current facts')
    grant=act('share.create',{'patient_id':pid});links.append(grant['id'])
    check(not req('GET','owner/'+grant['id'])['events'],'unapproved lab is hidden from owner')
    act('clinical.approve',{'id':event['id'],'approved':True})
    shared=req('GET','owner/'+grant['id'])['events'];check(len(shared)==1 and len(shared[0]['data']['observations'])==3,'approved typed lab appears in owner vault')
    item=act('inventory.create',{'name':'SYNTHETIC lot stock '+suffix,'unit':'tablet','stock':0});state['stock']=item['id']
    for batch,q,expiry in [('Expired',4,'2000-01-01'),('Eligible',3,'2099-01-01')]:act('inventory.receive',{'id':item['id'],'version':record(item['id'])['version'],'quantity':q,'batch':batch,'supplier':'Synthetic','expiry':expiry})
    dispense={'patient_id':pid,'inventory_id':item['id'],'version':record(item['id'])['version'],'quantity':3,'dose':'Synthetic vet-supplied dose','frequency':'Synthetic vet-supplied frequency','instructions':'Synthetic acceptance test only'}
    med=act('medication.dispense',dispense);check(med['data']['lots'][0]['batch']=='Eligible','dispensing skips expired lot')
    req('POST','actions',expected=409,json={'action':'medication.dispense','payload':{**dispense,'version':record(item['id'])['version'],'quantity':1},'key':str(uuid.uuid4())})
    check(record(item['id'])['data']['stock']==4,'expired stock rejected without partial mutation')
    invoice=act('invoice.create',{'patient_id':pid,'items':[{'name':'Synthetic service','quantity':3,'price_cents':101}],'discount_cents':3,'tax_bps':900});state['invoice']=invoice['id']
    check(invoice['data']['total_cents']==327,'discount and explicit tax reconcile in cents')
    payment=act('test.payment.create',{'invoice_id':invoice['id'],'amount_cents':327});state['payment']=payment['id']
    hook=req('POST','integrations/test/key')
    body={'event_id':'payment-'+suffix,'action':'test.payment.callback','payload':{'id':payment['id'],'status':'succeeded'}};raw=json.dumps(body).encode();stamp=str(int(time.time()));sig=hmac.new(hook['secret'].encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest();headers={'x-broby-key':hook['id'],'x-broby-timestamp':stamp,'x-broby-signature':sig}
    first=req('POST','integrations/test/events',content=raw,headers=headers);second=req('POST','integrations/test/events',content=raw,headers=headers)
    check(first==second,'signed callback replay applies once')
    req('POST','integrations/test/events',expected=401,content=raw,headers={**headers,'x-broby-signature':'bad'})
    check(True,'tampered callback rejected')
    act('test.payment.refund',{'id':payment['id'],'amount_cents':100,'reason':'Synthetic rehearsal'})
    check(record(invoice['id'])['data']['paid_cents']==0,'simulation leaves real invoice balance unchanged')
    msg=act('test.message.create',{'patient_id':pid,'body':'SYNTHETIC no transmission '+suffix});state['message']=msg['id']
    for status in ('accepted','delivered','read'):act('test.message.callback',{'id':msg['id'],'status':status})
    check(record(msg['id'])['data']['sending_enabled'] is False,'simulated delivery never enables sending')
    check(req('GET','operations/status')['sending_enabled'] is False,'operations status confirms outbound disabled')
    save();print(str(len(checks))+' advanced acceptance checks passed',flush=True)
finally:
    for token in links:act('share.revoke',{'token':token})
    if hook:req('DELETE','integrations/test/key/'+hook['id'])
    c.close()
