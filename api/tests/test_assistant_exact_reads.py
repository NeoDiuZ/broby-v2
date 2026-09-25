"""Exact references and literal timeline search through shared saved reads."""
import pytest
from fastapi.testclient import TestClient
import assistant, db, main
from test_integrity import isolated, act, get, err
from test_record_queries import ask, query


def events():
    with db.connection(True) as c:
        def make(patient='luna', clinic='clinic-east', **extra):
            return db.record(c, 'event', clinic, {'patient_id': patient, 'title': 'SYNTHETIC phone call', 'body': 'Owner quoted A%_B [literal].', 'category': 'message', 'occurred_at': '2098-07-10T10:00:00Z', **extra})
        wanted=make()
        other=make(body='Owner quoted AXZB literal.')
        make(patient='milo');make(clinic='clinic-river')
        make(occurred_at='2098-07-11T10:00:00Z')
    return wanted, other


def test_exact_id_and_literal_text_intersect_filters_and_saved_view_refresh(monkeypatch):
    wanted, other=events()
    planned={'kind':'event','record_id':wanted['id'],'text_contains':'a%_b [literal]','category':'message','start':'2098-07-10','end':'2098-07-10'}
    message=f'Show event record ID {wanted["id"]} whose text contains "A%_B [literal]" on 2098-07-10'
    answer=ask(monkeypatch,message,{'read':planned},'luna')
    assert [r['id'] for r in answer['sources']]==[wanted['id']]
    assert answer['sources'][0]['version']==1 and 'literal text' in answer['text']
    view=act('dashboard.save',{'name':'SYNTHETIC exact event','query':answer['dashboard']['query']})
    cli=TestClient(main.app)
    stored=cli.get('/api/dashboards/'+view['id']).json()['result']
    assert stored['query']==answer['dashboard']['query'] and stored['records']==answer['sources']
    with db.connection(True) as c:db.update(c,get(wanted['id']),{**wanted['data'],'body':'SYNTHETIC corrected wording'})
    refreshed=cli.get('/api/dashboards/'+view['id']).json()['result']
    assert refreshed['count']==0 and not refreshed['records']
    assert answer['sources'][0]==wanted  # Saved answer preserves its original version.
    assert query({'kind':'event','record_id':wanted['id']})['records'][0]['version']==2


def test_literal_title_or_body_search_does_not_treat_pattern_characters_as_wildcards():
    wanted, other=events()
    result=query({'kind':'event','patient_id':'luna','start':'2098-07-10','end':'2098-07-10','text_contains':'a%_b [literal]'})
    assert [r['id'] for r in result['records']]==[wanted['id']]
    assert query({'kind':'event','record_id':other['id'],'text_contains':'SYNTHETIC PHONE CALL'})['count']==1
    assert query({'kind':'event','text_contains':'.*'})['count']==0


@pytest.mark.parametrize('change',[{'record_id':'absent'}, {'kind':'invoice'}, {'patient_id':'milo'}, {'category':'consult'}, {'start':'2098-07-11'}])
def test_exact_record_never_widens_wrong_reference_or_other_filters(change):
    wanted,_=events()
    assert query({'kind':'event','record_id':wanted['id'],**change})['count']==0
    with db.connection(True) as c:foreign=db.record(c,'event','clinic-river',{'patient_id':'luna','body':'SYNTHETIC foreign'})
    assert query({'kind':'event','record_id':foreign['id']})['count']==0


@pytest.mark.parametrize('plan',[
    {'kind':'event'}, {'kind':'event','record_id':'substituted'},
    {'kind':'event','record_id':'same','text_contains':'different'},
    {'kind':'invoice','record_id':'same','text_contains':'literal'},
])
def test_model_cannot_drop_or_substitute_explicit_id_or_literal_phrase(monkeypatch,plan):
    answer=ask(monkeypatch,'Show event record ID same whose text contains "literal"',{'read':plan})
    assert not answer['sources'] and not answer.get('dashboard') and not answer.get('action')


@pytest.mark.parametrize('message',[
    'Show event record ID first and record ID second',
    'Show events whose text contains unquoted words',
    'Show events whose text contains "first" and text contains "second"',
    'Show events whose text contains " "',
])
def test_ambiguous_explicit_filter_completes_as_clarification(monkeypatch,message):
    answer=ask(monkeypatch,message,{'read':{'kind':'event','record_id':'first','text_contains':'first'}})
    assert not answer['sources'] and not answer.get('dashboard')


@pytest.mark.parametrize('payload',[
    {'kind':'invoice','text_contains':'x'}, {'kind':'event','text_contains':' '},
    {'kind':'event','record_id':True}, {'kind':'event','record_id':''},
    {'kind':'event','text_contains':'x'*501},
])
def test_invalid_exact_read_contracts_are_rejected(payload):
    err(422,lambda:query(payload))


def test_exact_saved_turn_and_view_remain_permission_gated(monkeypatch):
    from test_read_access import restrict
    wanted,_=events()
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(assistant.providers,'model_json',lambda *a:{'read':{'kind':'event','record_id':wanted['id']}})
    cli=TestClient(main.app)
    turn=cli.post('/api/assistant',json={'message':'Show event record ID '+wanted['id'],'key':'exact-read-turn'}).json()
    view=act('dashboard.save',{'name':'SYNTHETIC restricted view','query':turn['dashboard']['query']})
    restrict('read.clinical')
    assert cli.get('/api/assistant/conversations/'+turn['conversation_id']).status_code==403
    assert cli.get('/api/dashboards/'+view['id']).status_code==403
    assert cli.post('/api/assistant',json={'message':'Show event record ID '+wanted['id'],'key':'new-exact-read'}).status_code==403


def test_exact_and_literal_reads_cannot_reintroduce_reconciled_history(monkeypatch):
    from test_clinical_reconciliation import fixture,preview,decision
    from test_transfers import TARGET,HEADERS
    monkeypatch.setattr('spine.reconciliation.native_dependents',lambda *a,**k:{})
    cli,old,_,correction=fixture()
    with db.connection() as c:wanted=next(r for r in db.all_records(c,'clinic-river','event') if r['data'].get('patient_id')==old['id'] and r['data'].get('body'))
    payload={'kind':'event','record_id':wanted['id'],'text_contains':wanted['data']['body'][:20]}
    view=act('dashboard.save',{'name':'SYNTHETIC reconciliation view','query':payload},**TARGET)
    assert cli.get('/api/dashboards/'+view['id'],headers=HEADERS).json()['result']['count']==1
    act('clinical.reconcile',decision(preview(cli,correction),old['id']),**TARGET)
    result=cli.get('/api/dashboards/'+view['id'],headers=HEADERS).json()['result']
    assert result['count']==0 and not result['records']
    assert get(wanted['id'])==wanted
