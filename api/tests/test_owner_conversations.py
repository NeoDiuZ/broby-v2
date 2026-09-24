import uuid
from datetime import datetime,timezone,timedelta
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
import db,main,owner_conversations as chat
from test_integrity import isolated,act,get,rows,err

@pytest.fixture(autouse=True)
def no_provider(monkeypatch):monkeypatch.setattr('providers.available',lambda:{'ai':False,'transcription':False})

def grant(patient='luna'):return act('share.create',{'patient_id':patient})['id']
def question(token,**kw):return chat.send(token,chat.Message(message=kw.pop('message','What care instructions were shared?'),key=kw.pop('key',str(uuid.uuid4())),**kw))
def approved(text='SYNTHETIC approved care',approved=True):
    with db.connection(True) as c:return db.event(c,'clinic-east','luna','consultation','Shared care',text,[],approved)
def transition(result,action='conversation.acknowledge',**kw):
    thread=get(result['id']);return act(action,{'id':thread['id'],'version':thread['version'],'last_owner_turn':thread['data'].get('last_owner_turn'),'reason':'SYNTHETIC reviewed',**kw})

def test_saved_question_quotes_only_approved_records_and_retry_is_exact():
    approved();approved('PRIVATE hidden note',False);token=grant();key='same-message-key'
    result=question(token,key=key)
    assert len(result['turns'])==1 and result['turns'][0]['cards'][0]['text']=='SYNTHETIC approved care'
    assert 'PRIVATE' not in str(result)
    assert question(token,key=key)==result
    assert len(rows('owner_thread'))==1 and len(rows('owner_turn'))==1
    err(409,lambda:question(token,key=key,message='Changed question'))

def test_separate_grants_same_patient_cannot_read_each_others_messages():
    first=grant();other=grant();result=question(first)
    assert chat.listing(other)==[]
    err(404,lambda:chat.owner_read(other,result['id']))
    err(404,lambda:question(other,thread_id=result['id']))
    assert len(rows('owner_turn'))==1

def test_different_patient_and_revoked_grants_are_denied():
    token=grant();result=question(token)
    err(404,lambda:chat.owner_read(grant('milo'),result['id']))
    act('share.revoke',{'token':token})
    err(404,lambda:chat.owner_read(token,result['id']))
    err(404,lambda:question(token))

def test_withdrawn_or_edited_shared_facts_disappear_from_old_answers():
    approved();token=grant();result=question(token)
    event=next(r for r in rows('event') if r['data'].get('title')=='Shared care')
    with db.connection(True) as c:db.update(c,event,{**event['data'],'approved':False})
    changed=chat.owner_read(token,result['id'])['turns'][0]
    assert changed['changed_sources'] and not any(r['id']==event['id'] for r in changed['cards'])
    assert 'SYNTHETIC approved care' not in str(changed)
    assert rows('owner_turn')[0]['data']['cards'][0]['text']=='SYNTHETIC approved care'

@pytest.mark.parametrize('action',['conversation.acknowledge','conversation.close','conversation.reply'])
def test_new_owner_message_invalidates_staff_review(action):
    token=grant();first=question(token);old=get(first['id'])
    question(token,thread_id=first['id'],message='An additional question')
    err(409,lambda:act(action,{'id':old['id'],'version':old['version'],'last_owner_turn':old['data']['last_owner_turn'],'reason':'old review','message':'stale reply'}))

def test_staff_reply_acknowledgement_close_and_fresh_conversation():
    token=grant();first=question(token,urgent=True)
    assert first['status']=='needs_attention' and len(rows('escalation'))==1
    transition(first,'conversation.reply',message='SYNTHETIC staff reply')
    read=chat.owner_read(token,first['id']);assert read['turns'][-1]['speaker']=='clinic' and read['turns'][-1]['message']=='SYNTHETIC staff reply'
    transition(read);assert rows('escalation')[0]['data']['status']=='acknowledged'
    question(token,thread_id=first['id'],message='SYNTHETIC new urgent question',urgent=True)
    assert len(rows('escalation'))==1 and rows('escalation')[0]['data']['status']=='needs_attention'
    transition(first,'conversation.close')
    err(409,lambda:question(token,thread_id=first['id']))
    assert question(token)['id']!=first['id']

def test_replies_do_not_send_external_messages_or_mark_queue_acknowledged():
    token=grant();r=question(token,request_staff=True)
    transition(r,'conversation.reply',message='Saved portal reply')
    assert get(r['id'])['data']['status']=='needs_attention'
    assert rows('outbox')==[] and rows('twilio_attempt')==[]

def test_timeout_creates_one_internal_alert_and_acknowledgement_stops_it():
    act('conversation.policy',{'ack_minutes':1,'reason':'SYNTHETIC target'},actor='clinic-east-admin')
    token=grant();r=question(token,request_staff=True);due=get(r['id'])['data']['ack_due_at']
    question(token,thread_id=r['id'],request_staff=True,message='Follow-up')
    assert get(r['id'])['data']['ack_due_at']==due
    instant=datetime.fromisoformat(due)+timedelta(seconds=1)
    with db.connection(True) as c:chat.tick(c,'clinic-east',instant);chat.tick(c,'clinic-east',instant)
    assert len(rows('escalation'))==1 and rows('escalation')[0]['data']['delivery']=='disabled'
    transition(r)
    with db.connection(True) as c:chat.tick(c,'clinic-east',instant)
    assert rows('escalation')[0]['data']['status']=='acknowledged'

def test_disabled_timeout_never_invents_a_deadline():
    r=question(grant(),request_staff=True)
    assert get(r['id'])['data']['ack_due_at'] is None
    with db.connection(True) as c:chat.tick(c,'clinic-east',datetime.now(timezone.utc)+timedelta(days=100))
    assert not rows('escalation')

def test_provider_outage_falls_back_to_saved_staff_queue(monkeypatch):
    from providers import ProviderError
    monkeypatch.setattr('providers.available',lambda:{'ai':True})
    def unavailable(*a,**kw):raise ProviderError('synthetic')
    monkeypatch.setattr('providers.model_json',unavailable)
    r=question(grant());assert r['status']=='needs_attention'
    assert 'unavailable' in r['turns'][0]['answer'] and not r['turns'][0]['cards']

@pytest.mark.parametrize('plan',[{'topic':'care','answer':'invented advice'},{'topic':'diagnose'},[],None])
def test_model_cannot_author_an_answer_or_expand_retrieval(monkeypatch,plan):
    approved();monkeypatch.setattr('providers.available',lambda:{'ai':True});monkeypatch.setattr('providers.model_json',lambda *a,**kw:plan)
    r=question(grant());assert r['status']=='needs_attention' and not r['turns'][0]['cards']
    assert 'invented advice' not in str(r)

def test_model_only_selects_category_and_does_not_receive_private_records(monkeypatch):
    approved();approved('PRIVATE clinical source',False);monkeypatch.setattr('providers.available',lambda:{'ai':True})
    def model(prompt,payload):
        assert set(payload)=={'question'} and 'PRIVATE' not in str(payload)
        return {'topic':'care'}
    monkeypatch.setattr('providers.model_json',model)
    r=question(grant());assert r['turns'][0]['cards'][0]['text']=='SYNTHETIC approved care'

def test_concurrent_duplicate_and_pending_staff_close_are_rejected(monkeypatch):
    token=grant();seen=[]
    def intent(message):
        thread=rows('owner_thread')[0]
        err(409,lambda:question(token,key='same-pending-key'))
        err(409,lambda:question(token,thread_id=thread['id'],message='next'))
        err(409,lambda:transition(thread,'conversation.close'))
        seen.append(True);return 'staff','rules'
    monkeypatch.setattr(chat,'topic',intent)
    r=question(token,key='same-pending-key');assert seen and len(r['turns'])==1

def test_grant_revoked_during_intent_processing_cannot_return_shared_data(monkeypatch):
    token=grant();approved()
    def intent(message):act('share.revoke',{'token':token});return 'care','rules'
    monkeypatch.setattr(chat,'topic',intent)
    err(404,lambda:question(token))
    assert rows('owner_turn')[0]['data']['state']=='failed'
    assert rows('owner_thread')[0]['data']['status']=='needs_attention'

def test_new_question_cannot_strand_an_expired_pending_claim(monkeypatch):
    token=grant()
    def interrupted(message):
        thread=rows('owner_thread')[0]
        with db.connection(True) as c:
            turn=rows('owner_turn')[0]
            db.update(c,turn,{**turn['data'],'lease_until':0})
        err(409,lambda:question(token,thread_id=thread['id'],message='New question after timeout'))
        assert len(rows('owner_turn'))==1
        with db.connection(True) as c:chat.tick(c,'clinic-east')
        return 'staff','rules'
    monkeypatch.setattr(chat,'topic',interrupted)
    err(409,lambda:question(token,key='expired-pending-question'))
    thread=rows('owner_thread')[0]
    monkeypatch.setattr(chat,'topic',lambda message:('staff','rules'))
    result=question(token,thread_id=thread['id'],message='New question after recovery')
    assert len(result['turns'])==2
    transition(result,'conversation.close')
    assert get(thread['id'])['data']['status']=='closed'

def test_policy_reason_is_bounded():
    err(422,lambda:act('conversation.policy',{'ack_minutes':1,'reason':'x'*1001},actor='clinic-east-admin'))
    assert not rows('owner_policy')

def test_interrupted_claim_is_recovered_and_old_worker_cannot_publish(monkeypatch):
    token=grant()
    def intent(message):
        with db.connection(True) as c:chat.tick(c,'clinic-east',datetime.now(timezone.utc)+timedelta(minutes=6))
        return 'care','rules'
    monkeypatch.setattr(chat,'topic',intent)
    err(409,lambda:question(token,key='recover-one-message'))
    assert rows('owner_turn')[0]['data']['state']=='failed'
    assert len(rows('escalation'))==1
    monkeypatch.setattr(chat,'topic',lambda message:('staff','rules'))
    r=question(token,key='recover-one-message');assert len(r['turns'])==1 and r['turns'][0]['state']=='completed'

def test_handover_has_verbatim_conversation_receipts_and_resolved_history():
    token=grant();r=question(token,message='Exact owner question',request_staff=True)
    transition(r,'conversation.reply',message='Exact clinic reply')
    handover=act('handover.prepare',{})
    value=handover['data']['snapshot']['owner_conversations'][0]['data']
    assert value['text']=='Owner: Exact owner question\n\nClinic: Exact clinic reply'
    assert len(value['turn_ids'])==2
    transition(r,'conversation.close')
    assert get(handover['id'])['data']['snapshot']['owner_conversations'][0]['data']==value
    with db.connection() as c:assert chat.handover_rows(c,'clinic-east')==[]

def test_http_saved_pet_cookie_preserves_conversation_scope():
    token=grant();client=TestClient(main.app)
    result=client.post('/api/owner/'+token+'/conversations',json={'message':'A saved question','key':'cookie-conversation'}).json()
    assert client.post('/api/owner-account/claim/'+token).status_code==200
    assert client.get('/api/owner-account/pets/luna/conversations/'+result['id']).status_code==200
    assert client.get('/api/owner-account/pets/milo/conversations/'+result['id']).status_code==404
    assert client.get('/api/owner-conversations/'+result['id'],headers={'x-clinic-id':'clinic-river','x-actor-id':'clinic-river-vet'}).status_code==404
    act('access.member',{'id':'clinic-east-vet','version':1,'restrictions':['read.messages'],'reason':'test'},actor='clinic-east-admin')
    assert client.get('/api/owner-conversations/'+result['id']).status_code==403

@pytest.mark.parametrize('minutes',[0,-1,1441,'no',1.5])
def test_policy_rejects_invalid_intervals(minutes):err(422,lambda:act('conversation.policy',{'ack_minutes':minutes,'reason':'invalid'},actor='clinic-east-admin'))

def test_policy_requires_admin_and_current_version():
    err(403,lambda:act('conversation.policy',{'ack_minutes':1,'reason':'not admin'}))
    r=act('conversation.policy',{'ack_minutes':1,'reason':'first'},actor='clinic-east-admin')
    err(409,lambda:act('conversation.policy',{'ack_minutes':2,'reason':'stale','version':0},actor='clinic-east-admin'))
    act('conversation.policy',{'ack_minutes':None,'reason':'disable','version':r['version']},actor='clinic-east-admin')
    assert get(r['id'])['data']['ack_minutes'] is None

def test_rate_limit_does_not_create_unbounded_failed_messages(monkeypatch):
    token=grant()
    monkeypatch.setattr('accounts.rate_limit',lambda *a:(_ for _ in ()).throw(HTTPException(429,'slow down')))
    err(429,lambda:question(token))
    assert not rows('owner_turn') and not rows('owner_thread')
