from types import SimpleNamespace
import time
import pytest
from fastapi.testclient import TestClient
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
import db,main,twilio_trial as trial
from test_integrity import isolated,act,get,rows,err

ACCOUNT='AC'+'1'*32;CONTENT='HX'+'2'*32;SID='SM'+'3'*32
FROM='whatsapp:+15555550100';TO='whatsapp:+15555550101';ORIGIN='https://broby.example.test'
@pytest.fixture(autouse=True)
def configure(monkeypatch):
    for k,v in {'TWILIO_ACCOUNT_SID':ACCOUNT,'TWILIO_AUTH_TOKEN':'synthetic-token','BROBY_TWILIO_MODE':'trial','BROBY_TWILIO_SEND_ENABLED':'true','BROBY_TWILIO_CLINIC_ID':'clinic-east','BROBY_TWILIO_FROM':FROM,'BROBY_TWILIO_RECIPIENT':TO,'BROBY_TWILIO_CONTENT_SID':CONTENT,'BROBY_TWILIO_TEMPLATE_TEXT':'Synthetic provider template','BROBY_PUBLIC_URL':ORIGIN}.items():monkeypatch.setenv(k,v)

@pytest.fixture
def provider(monkeypatch):
    obj=SimpleNamespace(sid=SID,account_sid=ACCOUNT,from_=FROM,to=TO,direction='outbound-api',status='queued',error_code=None)
    calls=[]
    class Messages:
        def create(self,**kwargs):calls.append(kwargs);return obj
        def __call__(self,sid):return self
        def fetch(self):return obj
    messages=Messages();monkeypatch.setattr(trial,'client',lambda cfg:SimpleNamespace(messages=messages))
    return SimpleNamespace(obj=obj,calls=calls,messages=messages)

def send(key=None,**p):return act('twilio.trial_send',{'recipient':TO,'content_sid':CONTENT,'template_text':'Synthetic provider template',**p},actor='clinic-east-admin',key=key)
def attempt(r):
    with db.connection() as c:return dict(c.execute('SELECT * FROM twilio_attempts WHERE resource_id=?',(r['id'],)).fetchone())
def callback(r,status='delivered',**extra):
    path='/api/integrations/twilio/status/'+attempt(r)['id']
    fields={'AccountSid':ACCOUNT,'MessageSid':SID,'From':FROM,'To':TO,'MessageStatus':status,**extra}
    sig=RequestValidator('synthetic-token').compute_signature(ORIGIN+path,fields)
    return TestClient(main.app).post(path,data=fields,headers={'x-twilio-signature':sig})

def test_scoped_explicit_trial_disabled_and_capped(monkeypatch):
    for p in ({'recipient':'whatsapp:+6511111111'},{'content_sid':'HX'+'4'*32},{'template_text':'Different'}):err(409,lambda:send(**p))
    err(403,lambda:act('twilio.trial_send',{},actor='clinic-east-nurse'))
    err(503,lambda:act('twilio.trial_send',{},clinic='clinic-river',actor='clinic-river-admin'))
    monkeypatch.setenv('BROBY_TWILIO_SEND_ENABLED','false');err(409,send)
    monkeypatch.setenv('BROBY_TWILIO_SEND_ENABLED','true')
    first=send('trial-once');assert send('trial-once')['id']==first['id']
    for i in range(9):send()
    err(429,send)

def test_canonical_delivery_and_signed_callback_duplicate(provider):
    r=send();trial.tick();assert len(provider.calls)==1
    assert provider.calls[0]['content_sid']==CONTENT and 'body' not in provider.calls[0]
    assert get(r['id'])['data']['status']=='queued'
    response=callback(r,FutureTwilioParameter='supported');assert response.status_code==200
    assert get(r['id'])['data']['status']=='queued' # callback alone is not canonical verification
    assert callback(r,FutureTwilioParameter='supported').json()['duplicate']
    provider.obj.status='delivered';trial.tick()
    assert get(r['id'])['data']['status']=='delivered'
    callback(r,'sent');provider.obj.status='sent';trial.tick()
    assert get(r['id'])['data']['status']=='delivered' and len(provider.calls)==1

def test_lost_creation_ack_never_resends_and_callback_recovers(provider,monkeypatch):
    def lost(**kw):provider.calls.append(kw);raise TimeoutError()
    monkeypatch.setattr(provider.messages,'create',lost)
    r=send();trial.tick();assert get(r['id'])['data']['status']=='uncertain'
    trial.tick();trial.tick();assert len(provider.calls)==1
    assert callback(r).status_code==200
    provider.obj.status='delivered';trial.tick()
    assert get(r['id'])['data']['provider_sid']==SID and get(r['id'])['data']['status']=='delivered'
    assert len(provider.calls)==1

def test_stale_claim_does_not_retry_send(provider):
    r=send();assert trial.claim() is not None
    with db.connection(True) as c:c.execute('UPDATE twilio_attempts SET lease_until=0')
    trial.tick();trial.tick();assert provider.calls==[] and get(r['id'])['data']['status']=='uncertain'

def test_credential_scope_and_permissions_rechecked_before_send(provider,monkeypatch):
    r=send();member=get('clinic-east-admin')
    other=act('member.save',{'name':'Other admin','role':'admin'},actor='clinic-east-admin')
    act('member.save',{'id':member['id'],'version':member['version'],'name':member['data']['name'],'role':'admin','active':False},actor=other['id'])
    trial.tick();assert get(r['id'])['data']['status']=='blocked' and provider.calls==[]

def test_changed_configuration_does_not_redirect_queued_messages(provider,monkeypatch):
    r=send();monkeypatch.setenv('BROBY_TWILIO_RECIPIENT','whatsapp:+6512345678');trial.tick()
    assert get(r['id'])['data']['status']=='blocked' and provider.calls==[]

def test_callback_signature_account_recipient_and_sid_checks(provider):
    r=send();trial.tick();path='/api/integrations/twilio/status/'+attempt(r)['id'];c=TestClient(main.app)
    assert c.post(path,data={'MessageSid':SID}).status_code==403
    assert callback(r,AccountSid='AC'+'4'*32).status_code==403
    assert callback(r,To='whatsapp:+6512345678').status_code==403
    assert callback(r,MessageSid='SM'+'4'*32).status_code==409
    fields={'AccountSid':ACCOUNT,'MessageSid':SID,'From':FROM,'To':TO,'MessageStatus':'delivered'}
    sig=RequestValidator('synthetic-token').compute_signature('https://wrong.example.test'+path,fields)
    assert c.post(path,data=fields,headers={'x-twilio-signature':sig}).status_code==403
    assert c.post(path,content=b'x'*(1024*1024+1),headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413

def test_rejection_is_final_and_provider_identity_mismatch_never_verified(provider,monkeypatch):
    def rejected(**kw):raise TwilioRestException(400,'https://api.twilio.com',msg='private provider message',code=21608)
    monkeypatch.setattr(provider.messages,'create',rejected)
    r=send();trial.tick();d=get(r['id'])['data'];assert d['status']=='failed' and 'private' not in d['error']
    monkeypatch.setattr(provider.messages,'create',lambda **kw:provider.obj)
    provider.obj.to='whatsapp:+6512345678'
    other=send();trial.tick();assert get(other['id'])['data']['status']=='uncertain' and get(other['id'])['data']['provider_sid'] is None

def test_inbound_deduplication_optout_and_no_patient_assignment(provider):
    r=send();path='/api/integrations/twilio/inbound';c=TestClient(main.app)
    fields={'AccountSid':ACCOUNT,'MessageSid':SID,'From':TO,'To':FROM,'Body':'STOP','OptOutType':'STOP'}
    sig=RequestValidator('synthetic-token').compute_signature(ORIGIN+path,fields)
    for i in range(2):assert c.post(path,data=fields,headers={'x-twilio-signature':sig}).status_code==204
    assert len(rows('whatsapp_trial_inbound'))==1 and 'patient_id' not in rows('whatsapp_trial_inbound')[0]['data']
    err(409,send);trial.tick();assert get(r['id'])['data']['status']=='blocked' and provider.calls==[]
    fields['From']='whatsapp:+6512345678';sig=RequestValidator('synthetic-token').compute_signature(ORIGIN+path,fields)
    assert c.post(path,data=fields,headers={'x-twilio-signature':sig}).status_code==403

def test_status_does_not_disclose_credentials_and_sdk_configuration(monkeypatch):
    c=TestClient(main.app)
    assert c.get('/api/integrations/twilio/status').status_code==403
    response=c.get('/api/integrations/twilio/status',headers={'x-actor-id':'clinic-east-admin'})
    assert response.json()['customer_sending'] is False and 'synthetic-token' not in response.text
    sdk=trial.client(trial.config());assert sdk.account_sid==ACCOUNT
    monkeypatch.delenv('TWILIO_AUTH_TOKEN')
    assert c.get('/api/integrations/twilio/status',headers={'x-actor-id':'clinic-east-admin'}).json()['configured'] is False


def test_read_receipt_is_terminal_and_manual_check_can_resume(provider):
    r=send();trial.tick();provider.obj.status='read';callback(r,'read');trial.tick()
    assert get(r['id'])['data']['status']=='read'
    assert trial.claim() is None
    act('twilio.reconcile',{'id':r['id']},actor='clinic-east-admin')
    provider.obj.status='sent';trial.tick();assert get(r['id'])['data']['status']=='read'


def test_provider_poll_failures_are_bounded(provider,monkeypatch):
    r=send();trial.tick()
    def broken():raise TimeoutError('private transport details')
    monkeypatch.setattr(provider.messages,'fetch',broken)
    for i in range(10):
        act('twilio.reconcile',{'id':r['id']},actor='clinic-east-admin');trial.tick()
    d=get(r['id'])['data'];assert d['status']=='needs_review' and 'private' not in d['error']
    with db.connection(True) as c:c.execute('UPDATE twilio_attempts SET next_poll=?',(time.time()-1,))
    assert trial.claim() is None and len(provider.calls)==1
