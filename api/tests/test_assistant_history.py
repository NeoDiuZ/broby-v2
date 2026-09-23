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


def test_provider_failure_is_safe_retryable_http_response_without_proposal(monkeypatch):
    from providers import ProviderError
    def unavailable(*a):raise ProviderError('Untrusted provider diagnostic')
    monkeypatch.setattr(assistant,'answer',unavailable)
    client=TestClient(main.app);payload={'message':'Issue credit; tax unknown','patient_id':'luna','key':'credit-provider-failure'}
    response=client.post('/api/assistant',json=payload)
    assert response.status_code==503 and 'Retry this question' in response.json()['detail']
    assert 'Untrusted provider diagnostic' not in response.text
    with db.connection() as c:
        turn=dict(c.execute('SELECT * FROM assistant_turns').fetchone())
        assert turn['status']=='failed' and turn['response'] is None and turn['execution'] is None and turn['lease_until']==0
    assert client.post(f"/api/assistant/conversations/{turn['conversation_id']}/turns/{turn['id']}/confirm").status_code==404
    assert not rows('credit_note')
    monkeypatch.setattr(assistant,'answer',lambda *a:{'text':'Please specify net and tax credit amounts.','sources':[]})
    retried=client.post('/api/assistant',json=payload)
    assert retried.status_code==200 and retried.json()['turn_id']==turn['id'] and not retried.json().get('action')
    with db.connection() as c:assert c.execute('SELECT COUNT(*) FROM assistant_turns').fetchone()[0]==1


@pytest.mark.parametrize('model_text', ['not JSON', '[]', 'null', 'true', '"answer"'])
def test_invalid_provider_json_reaches_retry_boundary(monkeypatch, model_text):
    import httpx,providers
    monkeypatch.setattr(providers,'available',lambda:{'ai':True})
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic')
    monkeypatch.setenv('ANTHROPIC_MODEL','synthetic')
    original=httpx.Client
    def respond(request):return httpx.Response(200,json={'content':[{'type':'text','text':model_text}]})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(respond)))
    client=TestClient(main.app)
    response=client.post('/api/assistant',json={'message':'Issue a credit without supplied tax','patient_id':'luna','key':'malformed-provider'})
    assert response.status_code==503 and not rows('credit_note')
    with db.connection() as c:assert c.execute('SELECT status FROM assistant_turns').fetchone()[0]=='failed'


@pytest.mark.parametrize('result', [{'clarify':True},{'read':{'kind':'invoice','scope':'patient'}},{'action':{'action':'credit_note.create','payload':{'id':'invoice-test'}}}])
def test_planner_uses_structured_collector_without_executing(monkeypatch,result):
    import httpx,providers
    monkeypatch.setattr(providers,'available',lambda:{'ai':True})
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic');monkeypatch.setenv('ANTHROPIC_MODEL','synthetic')
    original=httpx.Client
    def respond(request):
        body=json.loads(request.content)
        assert body['tool_choice']=={'type':'tool','name':'submit_clinic_intent','disable_parallel_tool_use':True}
        schema=body['tools'][0]['input_schema']
        assert schema['properties']['action']['properties']['action']['enum']==['credit_note.create']
        return httpx.Response(200,json={'stop_reason':'tool_use','content':[{'type':'tool_use','name':'submit_clinic_intent','input':result}]})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(respond)))
    assert providers.model_json('system',{'allowed_actions':{'credit_note.create':{}},'read_contract':{}})==result
    assert not rows('credit_note')


@pytest.mark.parametrize('blocks', [[],[{'type':'tool_use','name':'other','input':{'clarify':True}}],
    [{'type':'tool_use','name':'submit_clinic_intent','input':{'clarify':False}}],
    [{'type':'tool_use','name':'submit_clinic_intent','input':{'clarify':True,'action':{}}}],
    [{'type':'tool_use','name':'submit_clinic_intent','input':{'clarify':True}}]*2])
def test_collector_rejects_missing_wrong_multiple_and_ambiguous_results(monkeypatch,blocks):
    import httpx,providers
    monkeypatch.setattr(providers,'available',lambda:{'ai':True})
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic');monkeypatch.setenv('ANTHROPIC_MODEL','synthetic')
    original=httpx.Client
    def respond(request):
        body=json.loads(request.content)
        assert 'action' not in body['tools'][0]['input_schema']['properties']
        return httpx.Response(200,json={'stop_reason':'tool_use','content':blocks})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(respond)))
    with pytest.raises(providers.ProviderError):providers.model_json('system',{'allowed_actions':{},'read_contract':{}})


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
