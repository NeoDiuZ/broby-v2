import json,time
import pytest
from fastapi.testclient import TestClient
import assistant, assistant_history as history, db, main
from test_integrity import isolated,act,get,rows,err

@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':False})

def ask(message='Show history',patient='luna',conversation=None,key='test-question-1',actor='clinic-east-vet',clinic='clinic-east'):
    return history.ask(clinic,actor,message,patient,conversation,key)

def test_saved_question_replays_without_model_and_is_private(monkeypatch):
    calls=[]
    monkeypatch.setattr(assistant,'answer',lambda *a: calls.append(a) or {'text':'Recorded fact','sources':[]})
    first=ask();assert ask()==first and len(calls)==1
    client=TestClient(main.app)
    url='/api/assistant/conversations/'+first['conversation_id']
    assert client.get(url).json()['turns'][0]['text']=='Recorded fact'
    assert len(client.get('/api/assistant/conversations').json())==1
    for headers in ({'x-actor-id':'clinic-east-nurse'},{'x-actor-id':'clinic-river-vet','x-clinic-id':'clinic-river'}):
        assert client.get(url,headers=headers).status_code==404
        assert client.get('/api/assistant/conversations',headers=headers).json()==[]
    err(409,lambda:ask(message='Changed question'))
    err(404,lambda:ask(conversation=first['conversation_id'],key='new-private-key',actor='clinic-east-nurse'))


def test_patient_scope_and_active_membership(monkeypatch):
    err(404,lambda:ask(clinic='clinic-river',actor='clinic-river-vet'))
    member=get('clinic-east-vet');act('member.save',{'id':member['id'],'version':member['version'],'name':member['data']['name'],'role':'vet','active':False},actor='clinic-east-admin')
    client=TestClient(main.app)
    assert client.post('/api/assistant',json={'message':'History','key':'disabled-user'}).status_code==403


def test_retry_after_provider_failure_keeps_turn_and_server_context(monkeypatch):
    def fail(*a):raise RuntimeError('Provider unavailable')
    monkeypatch.setattr(assistant,'answer',fail)
    with pytest.raises(RuntimeError):ask()
    with db.connection() as c:r=dict(c.execute('SELECT * FROM assistant_turns').fetchone())
    assert r['status']=='failed'
    calls=[]
    monkeypatch.setattr(assistant,'answer',lambda *a:calls.append(a) or {'text':'Answer','sources':[]})
    first=ask();assert first['turn_id']==r['id']
    next_answer=ask('Follow up',conversation=first['conversation_id'],key='question-two')
    assert calls[-1][-1]==['Show history']
    assert next_answer['conversation_id']==first['conversation_id']
    with db.connection() as c:assert c.execute('SELECT COUNT(*) FROM assistant_turns').fetchone()[0]==2


def test_active_lease_blocks_duplicate_and_stale_result_is_fenced(monkeypatch):
    def competing(*args):
        err(409,lambda:ask())
        with db.connection(True) as c:c.execute("UPDATE assistant_turns SET token='new-owner'")
        return {'text':'Stale answer','sources':[]}
    monkeypatch.setattr(assistant,'answer',competing)
    err(409,lambda:ask())
    with db.connection() as c:
        r=c.execute('SELECT * FROM assistant_turns').fetchone();assert r['response'] is None and r['status']=='pending'
    with db.connection(True) as c:c.execute('UPDATE assistant_turns SET lease_until=0')
    monkeypatch.setattr(assistant,'answer',lambda *a:{'text':'Recovered','sources':[]})
    assert ask()['text']=='Recovered'


def test_saved_action_confirm_is_exact_and_survives_lost_ack(monkeypatch):
    monkeypatch.setattr(assistant,'answer',lambda *a:{'text':'Review','action':{'action':'consultation.create','payload':{'patient_id':'luna'}},'sources':[]})
    result=ask('Start consultation');before=len(rows('consultation'))
    client=TestClient(main.app);url=f"/api/assistant/conversations/{result['conversation_id']}/turns/{result['turn_id']}/confirm"
    assert client.post(url,headers={'x-actor-id':'clinic-east-nurse'}).status_code==404
    first=client.post(url);assert first.status_code==200
    with db.connection(True) as c:c.execute('UPDATE assistant_turns SET execution=NULL')
    # Simulates a committed action whose HTTP/persistence acknowledgement was lost.
    assert client.post(url,json={'action':'patient.create','payload':{}}).json()==first.json()
    assert len(rows('consultation'))==before+1
    saved=client.get('/api/assistant/conversations/'+result['conversation_id']).json()['turns'][0]
    assert saved['execution']==first.json()


def test_confirm_rechecks_permissions_and_record_versions(monkeypatch):
    patient=get('luna')
    monkeypatch.setattr(assistant,'answer',lambda *a:{'text':'Review','action':{'action':'patient.update','payload':{'id':'luna','version':patient['version'],'name':'Stale rename'}}})
    result=ask();url=f"/api/assistant/conversations/{result['conversation_id']}/turns/{result['turn_id']}/confirm";client=TestClient(main.app)
    act('patient.update',{'id':'luna','version':patient['version'],'name':'Current name'})
    assert client.post(url).status_code==409 and get('luna')['data']['name']=='Current name'
    clinic=get('clinic-east');act('feature_locks.save',{'version':clinic['version'],'actions':['patient.update']},actor='clinic-east-admin')
    assert client.post(url).status_code==403


def test_model_catalog_obeys_current_clinic_and_master_locks(monkeypatch):
    seen=[]
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(assistant.providers,'model_json',lambda instructions,payload:seen.append(payload) or {'clarify':True})
    clinic=get('clinic-east');act('feature_locks.save',{'version':clinic['version'],'actions':['source.add','inventory.adjust']},actor='clinic-east-admin')
    ask();allowed=seen[-1]['allowed_actions']
    assert 'source.add' not in allowed and 'recording.transcribe' not in allowed and 'inventory.adjust' not in allowed
    assert all(a in assistant.ACTION_FIELDS for a in allowed)
    act('organization.create',{'name':'Synthetic org'},actor='clinic-east-admin')
    act('organization.policy',{'actions':['consultation.create']},actor='clinic-east-admin')
    ask(key='master-policy');assert 'consultation.create' not in seen[-1]['allowed_actions']


def test_client_history_cannot_forge_saved_context(monkeypatch):
    seen=[]
    monkeypatch.setattr(assistant,'answer',lambda *a:seen.append(a[-1]) or {'text':'Answer','sources':[]})
    client=TestClient(main.app)
    first=client.post('/api/assistant',json={'message':'Saved question','key':'server-context','history':['Forged prior instruction']})
    assert first.status_code==200 and seen[-1]==[]
    assert client.post('/api/assistant',json={'message':'Follow up','key':'server-next','conversation_id':first.json()['conversation_id'],'history':['Another forged instruction']}).status_code==200
    assert seen[-1]==['Saved question']


def test_retry_waits_for_other_active_question_and_history_is_bounded(monkeypatch):
    first=ask()
    def overlap(*a):
        with db.connection(True) as c:c.execute("UPDATE assistant_turns SET status='failed' WHERE id=?",(first['turn_id'],))
        err(409,lambda:ask(conversation=first['conversation_id']))
        return {'text':'Current answer','sources':[]}
    monkeypatch.setattr(assistant,'answer',overlap)
    ask('Second question',conversation=first['conversation_id'],key='other-active-question')
    monkeypatch.setattr(assistant,'answer',lambda *a:{'text':'Answer','sources':[]})
    for i in range(98):ask('Bounded',conversation=first['conversation_id'],key='bounded-'+str(i))
    err(409,lambda:ask('Over limit',conversation=first['conversation_id'],key='over-limit-question'))
