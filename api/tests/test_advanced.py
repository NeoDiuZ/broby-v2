"""Hard workflow boundaries: atomic stock, receipts, durable jobs and simulated adapters."""
import uuid,time,json,hmac,hashlib,threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
import db,actions,jobs,main,providers,auth,accounts
from test_integrity import isolated,act,get,rows,err,note,generate


def stock(quantity=0):return act('inventory.create',{'name':'Synthetic stock','unit':'tablet','stock':quantity},actor='clinic-east-admin')
def receive(item,q,batch,expiry=''):
    return act('inventory.receive',{'id':item['id'],'version':get(item['id'])['version'],'quantity':q,'batch':batch,'supplier':'Synthetic','expiry':expiry},actor='clinic-east-admin')
def dispense(item,q):return act('medication.dispense',{'patient_id':'luna','inventory_id':item['id'],'version':get(item['id'])['version'],'quantity':q,'dose':'Vet supplied dose','frequency':'Vet supplied frequency','instructions':'Synthetic test'})

def test_lots_expiry_fefo_and_atomic_failure():
    item=stock();expired=receive(item,4,'expired','2000-01-01');late=receive(item,3,'late','2099-01-01');early=receive(item,2,'early','2098-01-01')
    med=dispense(item,4)
    assert [(x['batch'],x['quantity']) for x in med['data']['lots']]==[('early',2),('late',2)]
    assert get(expired['data']['lot_id'])['data']['remaining']==4
    err(409,lambda:dispense(item,2))
    assert get(item['id'])['data']['stock']==5
    assert get(late['data']['lot_id'])['data']['remaining']==1

def test_concurrent_dispensing_cannot_oversell():
    item=stock(1)
    def attempt(_):
        try:return dispense(item,1)['id']
        except Exception:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
    assert sum(x is not None for x in results)==1
    assert get(item['id'])['data']['stock']==0

def test_lot_stocktake_and_purchase_order_reconciliation():
    item=stock();po=act('purchase_order.create',{'inventory_id':item['id'],'quantity':3,'supplier':'Synthetic'},actor='clinic-east-admin')
    p={'id':item['id'],'version':1,'quantity':2,'batch':'A','supplier':'Synthetic','purchase_order_id':po['id']}
    delivery=act('inventory.receive',p,actor='clinic-east-admin');assert get(po['id'])['data']['received']==2
    err(422,lambda:act('inventory.receive',{**p,'version':get(item['id'])['version']},actor='clinic-east-admin'))
    receive(item,1,'B')
    err(422,lambda:act('inventory.adjust',{'id':item['id'],'version':get(item['id'])['version'],'stock':8,'reason':'Count'},actor='clinic-east-admin'))
    act('inventory.adjust',{'id':item['id'],'version':get(item['id'])['version'],'lot_id':delivery['data']['lot_id'],'lot_count':1,'reason':'Count'},actor='clinic-east-admin')
    assert get(item['id'])['data']['stock']==2

def test_configured_rooms_and_availability():
    clinician=act('member.save',{'name':'Synthetic rota clinician','role':'vet'},actor='clinic-east-admin')['id']
    config=act('schedule.configure',{'rooms':['Room A'],'availability':{clinician:{'0':[{'start':'9:00','end':'12:00'}]}}},actor='clinic-east-admin')
    assert config['data']['availability'][clinician]['0'][0]['start']=='09:00'
    p={'patient_id':'luna','date':'2099-01-05','time':'09:00','duration':30,'clinician':clinician,'room':'Room A','reason':'Synthetic'} # Monday
    app=act('appointment.create',p)
    err(409,lambda:act('appointment.create',{**p,'clinician':'clinic-east-nurse'}))
    err(409,lambda:act('appointment.create',{**p,'time':'13:00'}))
    err(422,lambda:act('appointment.create',{**p,'time':'10:00','room':'Unknown'}))
    # Reschedule reuses the same availability and room validation.
    err(409,lambda:act('appointment.reschedule',{**p,'id':app['id'],'version':app['version'],'time':'13:00'}))
    assert get(app['id'])['data']['status']=='scheduled'

def test_invoice_tax_rounding_discount_and_simulation_separation():
    inv=act('invoice.create',{'patient_id':'luna','items':[{'name':'Synthetic','quantity':3,'price_cents':101}],'discount_cents':3,'tax_bps':900})
    assert inv['data']['total_cents']==327 and inv['data']['tax_cents']==27
    p=act('test.payment.create',{'invoice_id':inv['id'],'amount_cents':327},actor='clinic-east-admin')
    paid=act('test.payment.callback',{'id':p['id'],'status':'succeeded'},actor='clinic-east-admin')
    assert act('test.payment.callback',{'id':p['id'],'status':'succeeded'},actor='clinic-east-admin')==paid
    act('test.payment.refund',{'id':p['id'],'amount_cents':100,'reason':'Rehearsal'},actor='clinic-east-admin')
    err(422,lambda:act('test.payment.refund',{'id':p['id'],'amount_cents':228,'reason':'Too much'},actor='clinic-east-admin'))
    assert get(inv['id'])['data']['paid_cents']==0 and not rows('payment')

def test_signed_callbacks_replay_tamper_expiry_revocation_and_clinic_scope():
    client=TestClient(main.app);admin={'x-actor-id':'clinic-east-admin'}
    key=client.post('/api/integrations/test/key',headers=admin).json()
    msg=act('test.message.create',{'patient_id':'luna','body':'No actual sending'},actor='clinic-east-admin')
    body={'event_id':'callback1','action':'test.message.callback','payload':{'id':msg['id'],'status':'accepted'}}
    def send(payload,stamp=None,signature=None):
        raw=json.dumps(payload).encode();stamp=stamp or str(int(time.time()))
        sig=signature or hmac.new(key['secret'].encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return client.post('/api/integrations/test/events',content=raw,headers={'x-broby-key':key['id'],'x-broby-timestamp':stamp,'x-broby-signature':sig})
    assert send(body).status_code==200 and send(body).json()['version']==2
    assert send({**body,'payload':{**body['payload'],'status':'delivered'}}).status_code==409
    assert send(body,signature='bad').status_code==401
    assert send(body,stamp=str(int(time.time())-600)).status_code==401
    assert send({**body,'event_id':'cross','payload':{'id':'nonexistent','status':'accepted'}}).status_code==404
    client.delete('/api/integrations/test/key/'+key['id'],headers=admin)
    assert send(body).status_code==401
    assert not rows('outbox')

def test_message_state_machine_does_not_claim_real_delivery():
    msg=act('test.message.create',{'patient_id':'luna','body':'Synthetic'},actor='clinic-east-admin')
    err(409,lambda:act('test.message.callback',{'id':msg['id'],'status':'read'},actor='clinic-east-admin'))
    for state in ('accepted','delivered','read'):act('test.message.callback',{'id':msg['id'],'status':state},actor='clinic-east-admin')
    assert get(msg['id'])['data']['sending_enabled'] is False

def test_job_claims_prevent_double_execution_and_recover_expired_lease(monkeypatch):
    note();j=generate();claim=jobs.claim_job(j['id']);assert claim
    assert jobs.claim_job(j['id']) is None
    jobs.run_job(j['id']);assert get('consult-luna')['data']['summary']==[]
    with db.connection(True) as c:c.execute("UPDATE job_claims SET lease_until='' WHERE job_id=?",(j['id'],))
    jobs.run_job(j['id']);assert get('consult-luna')['data']['summary']

def test_provider_failure_uses_backoff_and_stops_after_three_attempts(monkeypatch):
    note();monkeypatch.setattr(providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(providers,'assemble',lambda *args:(_ for _ in ()).throw(providers.ProviderError('sensitive raw body')))
    j=act('summary.generate',{'id':'consult-luna','version':get('consult-luna')['version'],'mode':'ai'})
    for attempt in range(3):
        with pytest.raises(providers.ProviderError):jobs.run_job(j['id'])
        with db.connection() as c:
            job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(j['id'],)).fetchone())
            claim=dict(c.execute('SELECT * FROM job_claims WHERE job_id=?',(j['id'],)).fetchone())
        assert 'sensitive' not in job['error'] and claim['attempts']==attempt+1
        if attempt<2:
            assert job['status']=='queued' and jobs.claim_job(j['id']) is None
            with db.connection(True) as c:c.execute("UPDATE job_claims SET next_attempt='' WHERE job_id=?",(j['id'],))
        else:assert job['status']=='failed'

@pytest.mark.parametrize('status,retries,reason',[
    (400,False,'request'),(401,False,'credentials'),(402,False,'billing or credits'),
    (403,False,'access'),(404,False,'model or endpoint'),(429,True,'rate limit'),
    (500,True,'temporary availability')])
def test_provider_http_failure_persists_only_safe_status_and_retry_decision(monkeypatch,status,retries,reason):
    note()
    monkeypatch.setattr(providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(providers,'assemble',lambda *args:(_ for _ in ()).throw(
        providers.ProviderError('private provider body and key',service='ai',status_code=status)))
    j=act('summary.generate',{'id':'consult-luna','version':get('consult-luna')['version'],'mode':'ai'})
    with pytest.raises(providers.ProviderError):jobs.run_job(j['id'])
    with db.connection() as c:
        job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(j['id'],)).fetchone())
        claim=dict(c.execute('SELECT * FROM job_claims WHERE job_id=?',(j['id'],)).fetchone())
    assert job['status']==('queued' if retries else 'failed')
    assert claim['attempts']==1
    assert f'HTTP {status}' in job['error'] and reason in job['error']
    assert 'private' not in job['error'] and claim['last_error']==job['error']

@pytest.mark.parametrize('status',[401,402,404,429,500])
def test_ai_adapter_classifies_http_failure_without_provider_body(monkeypatch,status):
    import httpx
    monkeypatch.setenv('BROBY_ENABLE_AI','1')
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-key')
    monkeypatch.setenv('ANTHROPIC_MODEL','synthetic-model')
    original=httpx.Client
    def respond(request):return httpx.Response(status,text='private provider response and key')
    monkeypatch.setattr(providers.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(respond)))
    with pytest.raises(providers.ProviderError) as caught:providers.model_json('test',{})
    assert caught.value.service=='ai' and caught.value.status_code==status
    assert 'private' not in str(caught.value) and 'private' not in caught.value.safe_job_error(False)

def test_invitation_single_use_and_mfa_replay(monkeypatch):
    auth.setup_tables();client=TestClient(main.app);admin={'x-actor-id':'clinic-east-admin'}
    member=act('member.save',{'name':'Synthetic user','role':'nurse'},actor='clinic-east-admin')
    invite=client.post('/api/account/invitations',headers=admin,json={'member_id':member['id']}).json()
    body={'token':invite['token'],'username':'synthetic.account','password':'synthetic-password-123'}
    assert client.post('/api/account/invitations/accept',json=body).status_code==200
    assert client.post('/api/account/invitations/accept',json=body).status_code==404
    monkeypatch.setenv('BROBY_AUTH_MODE','password')
    assert client.post('/api/login',json={'username':body['username'],'password':body['password']}).status_code==200
    setup=client.post('/api/account/mfa/setup',json={'password':body['password']}).json()
    step=int(time.time()//30);code=accounts.totp(setup['secret'],step)
    assert client.post('/api/account/mfa/confirm',json={'code':code}).status_code==200
    client.post('/api/logout')
    assert client.post('/api/login',json={'username':body['username'],'password':body['password'],'code':code}).status_code==401
    monkeypatch.setattr(accounts.time,'time',lambda:(step+1)*30)
    code=accounts.totp(setup['secret'],step+1)
    assert client.post('/api/login',json={'username':body['username'],'password':body['password'],'code':code}).status_code==200


def test_disallowed_roles_cannot_create_test_credentials():
    client=TestClient(main.app)
    assert client.post('/api/integrations/test/key').status_code==403
    assert client.post('/api/account/invitations',json={'member_id':'clinic-east-vet'}).status_code==403


def test_master_policy_applies_to_clinic_admin_and_native_ingest():
    org=act('organization.create',{'name':'Synthetic organization'},actor='clinic-east-admin')
    act('organization.policy',{'actions':['source.add']},actor='clinic-east-admin')
    member=act('member.save',{'name':'Other admin','role':'admin'},actor='clinic-east-admin')
    err(403,lambda:act('source.add',{'patient_id':'luna','text':'blocked'},actor=member['id']))
    err(403,lambda:act('clinical.ingest',{},actor=member['id']))
    err(403,lambda:act('organization.policy',{'actions':[]},actor=member['id']))
    assert act('source.add',{'patient_id':'luna','text':'Master capture'},actor='clinic-east-admin')
    new=act('organization.clinic_create',{'name':'Synthetic child clinic'},actor='clinic-east-admin')
    with db.connection() as c:
        assert get(new['id'])['data']['name']=='Synthetic child clinic'
        assert db.get(c,'settings-'+new['id'])['data']['auto_reminders'] is False


def test_ontology_proposals_are_clinic_scoped_and_reject_alias_conflicts():
    p={'description':'Recorded condition flag','definition':{'code':'test_condition','name':'Recorded flag','value_type':'boolean','unit':'','category':'Clinical','aliases':['test_flag']}}
    proposal=act('ontology.propose',p)
    err(403,lambda:act('ontology.review',{'id':proposal['id'],'version':1,'status':'accepted'},actor='clinic-east-nurse'))
    act('ontology.review',{'id':proposal['id'],'version':1,'status':'accepted'},actor='clinic-east-admin')
    from ontology_workflow import lookup
    with db.connection() as c:
        assert lookup(c,'clinic-east','test_flag')['code']=='test_condition'
        assert lookup(c,'clinic-river','test_flag') is None
    conflict=act('ontology.propose',{**p,'definition':{**p['definition'],'code':'other_code','aliases':['weight']}})
    err(409,lambda:act('ontology.review',{'id':conflict['id'],'version':1,'status':'accepted'},actor='clinic-east-admin'))


def test_owner_consented_transfer_checks_clinic_revocation_and_replay():
    client=TestClient(main.app)
    note();j=generate();jobs.run_job(j['id']);consult=get('consult-luna')
    act('consultation.approve',{'id':consult['id'],'version':consult['version']})
    grant=act('share.create',{'patient_id':'luna'})
    base='/api/owner/'+grant['id']
    assert client.post(base+'/transfers',json={'target_clinic':'clinic-river','consent':False}).status_code==422
    request=client.post(base+'/transfers',json={'target_clinic':'clinic-river','consent':True}).json()
    err(404,lambda:act('transfer.accept',{'id':request['id']}))
    incoming=client.get('/api/transfers/incoming',headers={'x-clinic-id':'clinic-river'}).json()
    assert incoming[0]['patient_name']=='Luna'
    preview=client.get('/api/transfers/'+request['id']+'/preview',headers={'x-clinic-id':'clinic-river'}).json()
    result=act('transfer.accept',{'id':request['id'],'expected_digest':preview['digest']},clinic='clinic-river',actor='clinic-river-vet')
    assert result['transferred_events']>=1
    assert act('transfer.accept',{'id':request['id']},clinic='clinic-river',actor='clinic-river-vet')==result
    assert client.delete(base+'/transfers/'+request['id']).status_code==409
    with db.connection() as c:
        patient=db.get(c,result['id'],'clinic-river');events=db.all_records(c,'clinic-river','event')
        assert patient['data']['name']=='Luna' and events[0]['data']['source_ids']
        assert not events[0]['data']['approved']
    second=act('share.create',{'patient_id':'luna'})
    pending=client.post('/api/owner/'+second['id']+'/transfers',json={'target_clinic':'clinic-river','consent':True}).json()
    act('share.revoke',{'token':second['id']})
    err(404,lambda:act('transfer.accept',{'id':pending['id']},clinic='clinic-river',actor='clinic-river-vet'))


def test_migration_preview_stable_mapping_replay_and_conflict():
    records=[{'id':'owner-1','kind':'owner','data':{'name':'Synthetic migrated owner'}},{'id':'patient-1','kind':'patient','data':{'name':'Synthetic migrated pet','species':'Dog','owner_id':'owner-1'}}]
    payload={'source_system':'synthetic-legacy','records':records}
    preview=act('migration.preview',payload,actor='clinic-east-admin')
    assert preview['new_count']==2 and not get(preview['mapping']['patient-1'])
    applied=act('migration.apply',{**payload,'expected_digest':preview['digest']},actor='clinic-east-admin')
    assert get(applied['mapping']['patient-1'])['data']['owner_id']==applied['mapping']['owner-1']
    again=act('migration.preview',payload,actor='clinic-east-admin');assert again['new_count']==0 and again['unchanged_count']==2
    assert act('migration.apply',{**payload,'expected_digest':again['digest']},actor='clinic-east-admin')['new_count']==0
    records[1]['data']['name']='Changed silently'
    err(409,lambda:act('migration.preview',payload,actor='clinic-east-admin'))


def test_totp_rfc_test_vector():
    # RFC 6238 Appendix B SHA-1 vector, reduced to six decimal digits.
    import base64
    secret=base64.b32encode(b'12345678901234567890').decode()
    assert accounts.totp(secret,59//30)=='287082'
    assert accounts.totp(secret,1111111109//30)=='081804'


def test_mfa_recovery_codes_are_single_use(monkeypatch):
    auth.setup_tables();auth.provision('recover','clinic-east-admin','clinic-east','synthetic-password-123')
    monkeypatch.setenv('BROBY_AUTH_MODE','password');client=TestClient(main.app)
    credentials={'username':'recover','password':'synthetic-password-123'}
    assert client.post('/api/login',json=credentials).status_code==200
    setup=client.post('/api/account/mfa/setup',json={'password':credentials['password']}).json()
    code=accounts.totp(setup['secret'],int(time.time()//30))
    recovery=client.post('/api/account/mfa/confirm',json={'code':code}).json()['recovery_codes']
    assert len(recovery)==10 and len(set(recovery))==10
    client.post('/api/logout')
    assert client.post('/api/login',json={**credentials,'code':recovery[0]}).status_code==200
    client.post('/api/logout')
    assert client.post('/api/login',json={**credentials,'code':recovery[0]}).status_code==401
    with db.connection() as c:assert not c.execute('SELECT 1 FROM mfa_recovery WHERE code_hash=?',(recovery[0],)).fetchone()
