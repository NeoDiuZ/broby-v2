"""Persistent portal conversation acceptance. Synthetic records; no external sends."""
import argparse,json,uuid
from pathlib import Path
import httpx
from verification_records import stable_record
p=argparse.ArgumentParser();p.add_argument('base_url');p.add_argument('--credentials',required=True,type=Path);p.add_argument('--state',required=True,type=Path);p.add_argument('--verify-only',action='store_true');p.add_argument('--require-ai',action='store_true');a=p.parse_args()
if a.state.exists() and not a.verify_only:raise SystemExit('Fixture exists; use --verify-only.')
s=json.loads(a.state.read_text()) if a.verify_only else {'phase':'starting','tag':uuid.uuid4().hex[:8]}
checks=[]
def save():a.state.parent.mkdir(parents=True,exist_ok=True);a.state.write_text(json.dumps(s,indent=2));a.state.chmod(0o600)
def check(value,label):
 if not value:raise AssertionError(label)
 checks.append(label);print('PASS '+label,flush=True)
base=a.base_url.rstrip('/')
with httpx.Client(base_url=base+'/api/',headers={'Origin':base,'x-clinic-id':'clinic-east'},timeout=220) as c:
 def req(method,path,expected=200,**kw):
  r=c.request(method,path,**kw)
  if r.status_code!=expected:raise AssertionError(f'{method} {path.split("/")[0]}: expected {expected}, received {r.status_code}')
  return r.json()
 def act(action,payload):return req('POST','actions',json={'action':action,'payload':payload,'key':str(uuid.uuid4())})
 def rs():return req('GET','bootstrap')['records']
 def row(id):return next(r for r in rs() if r['id']==id)
 credentials=json.loads(a.credentials.read_text());req('POST','login',json={k:credentials[k] for k in ('username','password')})
 try:
  check(req('GET','ready')['status']=='ready','databases and file volume ready')
  if not a.verify_only:
   s['before']=rs();save()
   patient=act('patient.create',{'name':'SYNTHETIC Conversation '+s['tag'],'species':'Cat','owner_name':'SYNTHETIC Conversation Owner '+s['tag']});s['patient']=patient['id'];save()
   consult=act('consultation.create',{'patient_id':patient['id'],'title':'SYNTHETIC shared care '+s['tag']})
   source=act('source.add',{'patient_id':patient['id'],'consultation_id':consult['id'],'text':'SYNTHETIC recorded care: follow the clinic instructions supplied at discharge.','section':'Plan'})
   consult=row(consult['id']);consult=act('summary.save',{'id':consult['id'],'version':consult['version'],'summary':[{'name':'Plan','text':source['data']['text'],'source_ids':[source['id']]}]})
   act('consultation.approve',{'id':consult['id'],'version':consult['version']})
   act('source.add',{'patient_id':patient['id'],'text':'PRIVATE_SYNTHETIC_CONVERSATION_'+s['tag']})
   share=act('share.create',{'patient_id':patient['id']});s['grant']=share['id'];save();owner='owner/'+s['grant']
   body={'message':'Show the approved discharge care instructions already recorded.','request_staff':True,'urgent':True,'key':'conversation-'+s['tag']}
   response=req('POST',owner+'/conversations',json=body);s['thread']=response['id'];save()
   check(response['status']=='needs_attention' and response['urgent'],'owner request persists in the staff attention queue')
   cards=response['turns'][0]['cards'];check(bool(cards) and any(source['data']['text'] in card['text'] for card in cards),'retrieval answer quotes the approved care record')
   check('PRIVATE_SYNTHETIC' not in json.dumps(response),'unapproved clinical source is not disclosed')
   check(req('POST',owner+'/conversations',json=body)==response,'duplicate submission returns one saved turn')
   req('POST',owner+'/conversations',409,json={**body,'message':'changed retry'});check(True,'changed retry payload is rejected')
   other=act('share.create',{'patient_id':patient['id']});s['other_grant']=other['id'];save()
   req('GET','owner/'+other['id']+'/conversations/'+s['thread'],404);check(True,'another link for the same pet cannot read private conversation history')
   stale=row(s['thread'])
   second=req('POST',owner+'/conversations',json={'thread_id':s['thread'],'message':'SYNTHETIC follow-up: please ask a staff member to review.','request_staff':True,'key':'conversation-followup-'+s['tag']})
   req('POST','actions',409,json={'action':'conversation.close','payload':{'id':stale['id'],'version':stale['version'],'last_owner_turn':stale['data']['last_owner_turn'],'reason':'stale review'},'key':'stale-close-'+s['tag']});check(True,'new owner message prevents stale staff closure')
   thread=row(s['thread']);act('conversation.reply',{'id':thread['id'],'version':thread['version'],'last_owner_turn':thread['data']['last_owner_turn'],'message':'SYNTHETIC clinic reply: this acceptance test is complete.'})
   owner_result=req('GET',owner+'/conversations/'+s['thread']);check(len(owner_result['turns'])==3 and owner_result['turns'][-1]['speaker']=='clinic','staff reply persists and is visible through the owner link')
   handover=req('GET','handover');h=next(x for x in handover['owner_conversations'] if x['id']==s['thread']);check(len(h['data']['turn_ids'])==3,'morning handover includes exact conversation receipts')
   thread=row(s['thread']);act('conversation.close',{'id':thread['id'],'version':thread['version'],'last_owner_turn':thread['data']['last_owner_turn'],'reason':'SYNTHETIC acceptance completed'})
   act('share.revoke',{'token':s['grant']});act('share.revoke',{'token':s['other_grant']});s['phase']='complete';save()
  check(s['phase']=='complete','synthetic conversation is closed and links revoked')
  thread=req('GET','owner-conversations/'+s['thread']);check(thread['data']['status']=='closed' and len(thread['turns'])==3,'both owner messages and staff reply survive readback')
  if a.require_ai:check(thread['turns'][0]['data'].get('retrieval')=='model_intent','real configured model selected retrieval without authoring the care facts')
  check(len({x['id'] for x in thread['turns']})==3,'no duplicate message records')
  req('GET','owner/'+s['grant']+'/conversations/'+s['thread'],404);check(True,'revoked owner link cannot reopen the history')
  alerts=[r for r in rs() if r['kind']=='escalation' and r['data'].get('owner_thread_id')==s['thread']]
  check(len(alerts)==1 and alerts[0]['data']['status']=='acknowledged' and alerts[0]['data']['delivery']=='disabled','one internal urgent alert is retained and acknowledged without external delivery')
  current={r['id']:r for r in rs()};check(all(stable_record(current.get(r['id']))==stable_record(r) for r in s['before']),'all original records remain unchanged')
  check(not req('GET','integrations/twilio/status')['sending_enabled'],'WhatsApp remains disabled')
  s['checks']=checks;save()
 finally:c.post('logout')
print(f'{len(checks)} owner-conversation checks passed; no provider message sent.')
