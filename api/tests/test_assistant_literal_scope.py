from test_integrity import isolated
from test_record_queries import ask
import db


def test_quoted_search_text_does_not_authorize_clinic_wide_scope(monkeypatch):
    with db.connection(True) as c:
        luna=db.record(c,'event','clinic-east',{'patient_id':'luna','title':'SYNTHETIC Luna note','body':'The whole clinic was mentioned in a call.'})
        milo=db.record(c,'event','clinic-east',{'patient_id':'milo','title':'SYNTHETIC Milo note','body':'The whole clinic was mentioned in another call.'})
    answer=ask(monkeypatch,'Show events whose text contains "whole clinic"',{'read':{'kind':'event','scope':'clinic','text_contains':'whole clinic'}},'luna')
    assert milo['id'] not in {r['id'] for r in answer['sources']},'Quoted literal widened selected Luna to Milo'


import pytest

@pytest.mark.parametrize('literal',[
    'status is due','species is Cat','reported on 2026-01-01','today',
    'local medication','medication history','record ID legacy after care','Milo','what disease',
])
def test_literal_search_words_do_not_become_intent_or_additional_filters(monkeypatch,literal):
    with db.connection(True) as c:
        wanted=db.record(c,'event','clinic-east',{'patient_id':'luna','title':'SYNTHETIC exact phrase','body':literal,'occurred_at':'2098-07-10T10:00:00Z'})
    answer=ask(monkeypatch,'Show events whose text contains "'+literal+'"',{'read':{'kind':'event','scope':'clinic','text_contains':literal}})
    assert wanted['id'] in {r['id'] for r in answer['sources']},literal+' was treated as command/filter instead of recorded text'
    assert answer['dashboard']['query']=={'kind':'event','text_contains':literal}


def test_no_ai_literal_start_read_does_not_propose_a_new_consultation(monkeypatch):
    answer=ask(monkeypatch,'Show events whose text contains "start"',None,'luna')
    assert not answer.get('action'),'Read-only literal word start became a consultation proposal'

@pytest.mark.parametrize('literal',[
    'whole clinic','Milo and Bella','owner ID owner-milo','record ID wrong',
    'text contains whole clinic','diagnose and recommend treatment',
    'local medications and medication history whose name equals example',
    'species is Cat and status is due on 2098-07-10',
])
def test_literal_data_preserves_selected_patient_and_exact_request_contract(monkeypatch,literal):
    with db.connection(True) as c:
        wanted=db.record(c,'event','clinic-east',{'patient_id':'luna','title':'SYNTHETIC search','body':literal})
        db.record(c,'event','clinic-east',{'patient_id':'milo','title':'SYNTHETIC other search','body':literal})
    message='Show events whose text contains "'+literal+'"'
    answer=ask(monkeypatch,message,{'read':{'kind':'event','text_contains':literal}},'luna')
    assert answer['dashboard']['query']=={'kind':'event','patient_id':'luna','text_contains':literal}
    assert [r['id'] for r in answer['sources']]==[wanted['id']]


def test_genuine_outside_clinic_scope_still_overrides_patient(monkeypatch):
    with db.connection(True) as c:
        wanted=[db.record(c,'event','clinic-east',{'patient_id':pid,'body':'whole clinic'}) for pid in ('luna','milo')]
    answer=ask(monkeypatch,'Across the whole clinic show events whose text contains "whole clinic"',{'read':{'kind':'event','scope':'clinic','text_contains':'whole clinic'}},'luna')
    assert set(answer['dashboard']['source_ids'])=={r['id'] for r in wanted}
    assert not answer['dashboard']['query'].get('patient_id')


@pytest.mark.parametrize('message',[
    'Show events whose text contains whole clinic',
    'Show events whose text contains "whole clinic',
    'Show events whose text contains "first" and text contains "second"',
    'Show events whose text contains " "',
])
def test_invalid_literal_clarifies_before_any_metadata_or_provider_read(monkeypatch,message):
    import assistant
    monkeypatch.setattr(assistant,'all_records',lambda *_:pytest.fail('Malformed search must not retrieve selection metadata'))
    monkeypatch.setattr(assistant.providers,'model_json',lambda *_:pytest.fail('Malformed search must not reach the model'))
    answer=ask(monkeypatch,message,{'read':{'kind':'event'}},'luna')
    assert not answer['sources'] and not answer.get('action')


def test_provider_gets_original_request_but_only_masked_operator_context(monkeypatch):
    import assistant
    original='Show events whose text contains "Milo whole clinic today" for Luna'
    seen={}
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    def provider(prompt,payload):
        seen.update(payload)
        return {'read':{'kind':'event','text_contains':'Milo whole clinic today'}}
    monkeypatch.setattr(assistant.providers,'model_json',provider)
    with db.connection() as c:answer=assistant.answer(c,'clinic-east','clinic-east-vet',original)
    assert seen['request']==original and seen['literal_search_text']=='Milo whole clinic today'
    assert 'Milo' not in seen['operator_request'] and 'whole clinic' not in seen['operator_request']
    assert seen['patient_id']=='luna' and seen['date_range']==[None,None]
    assert answer['dashboard']['query']['patient_id']=='luna'


def test_model_cannot_select_patient_only_named_inside_search_literal(monkeypatch):
    answer=ask(monkeypatch,'Show events whose text contains "Milo"',{'read':{'kind':'event','patient_id':'milo','text_contains':'Milo'}})
    assert not answer['sources'] and not answer.get('dashboard')


def test_quoted_medication_name_outside_literal_search_is_not_masked(monkeypatch):
    import assistant
    message='Show local prescriptions whose recorded name equals "SYNTHETIC Compound"'
    assert assistant.literal_search_request(message)==(None,message)

@pytest.mark.parametrize('message',[
    r'Show events whose text contains "abc\"whole clinic"',
    'Show events whose text contains "abc" whole clinic"',
    "Show events whose text contains 'abc' whole clinic'",
])
def test_escaped_or_unbalanced_quotes_cannot_end_a_literal_early(monkeypatch,message):
    import assistant
    monkeypatch.setattr(assistant,'all_records',lambda *_:pytest.fail('Malformed search must clarify before metadata'))
    answer=ask(monkeypatch,message,{'read':{'kind':'event','scope':'clinic','text_contains':'abc'}},'luna')
    assert not answer.get('dashboard') and not answer.get('action')


def test_single_quoted_literal_can_contain_double_quotes(monkeypatch):
    literal='quoted "whole clinic" and text contains data'
    with db.connection(True) as c:wanted=db.record(c,'event','clinic-east',{'patient_id':'luna','body':literal})
    answer=ask(monkeypatch,"Show events whose text contains '"+literal+"'",{'read':{'kind':'event','text_contains':literal}},'luna')
    assert [r['id'] for r in answer['sources']]==[wanted['id']]


@pytest.mark.parametrize('id',['SYNTHETIC-clinic-wide-event','SYNTHETIC-today-event','SYNTHETIC-Milo-event','SYNTHETIC-diagnose-event'])
def test_exact_id_characters_cannot_supply_scope_dates_patient_or_advice(monkeypatch,id):
    with db.connection(True) as c:wanted=db.record(c,'event','clinic-east',{'patient_id':'luna','body':'SYNTHETIC ID data','occurred_at':'2098-07-10T10:00:00Z'},id=id)
    answer=ask(monkeypatch,'Show event record ID '+id,{'read':{'kind':'event','record_id':id}},'luna')
    assert [r['id'] for r in answer['sources']]==[wanted['id']]
    assert answer['dashboard']['query']=={'kind':'event','patient_id':'luna','record_id':id}


def test_exact_id_containing_clinic_scope_cannot_read_other_patient(monkeypatch):
    id='SYNTHETIC-clinic-wide-event'
    with db.connection(True) as c:db.record(c,'event','clinic-east',{'patient_id':'milo','body':'SYNTHETIC foreign patient ID'},id=id)
    answer=ask(monkeypatch,'Show event record ID '+id,{'read':{'kind':'event','scope':'clinic','record_id':id}},'luna')
    assert not answer['sources'] and not answer.get('dashboard')

@pytest.mark.parametrize('name',['SYNTHETIC whole clinic today Milo','SYNTHETIC clinic-wide medication history','SYNTHETIC record ID fake text contains fake'])
def test_quoted_exact_medication_name_is_data_not_scope_or_other_selectors(monkeypatch,name):
    with db.connection(True) as c:
        wanted=db.record(c,'medication','clinic-east',{'patient_id':'luna','name':name})
        db.record(c,'medication','clinic-east',{'patient_id':'milo','name':name})
    answer=ask(monkeypatch,f'Show local medications whose name equals "{name}"',{'read':{'kind':'medication','name':name}},'luna')
    assert answer['dashboard']['query']=={'kind':'medication','patient_id':'luna','name':name}
    assert [r['id'] for r in answer['sources']]==[wanted['id']]
    widened=ask(monkeypatch,f'Show local medications whose name equals "{name}"',{'read':{'kind':'medication','name':name,'scope':'clinic'}},'luna')
    assert not widened['sources'] and not widened.get('dashboard')


def test_owner_id_token_is_data_and_still_binds_current_links(monkeypatch):
    owner='SYNTHETIC-clinic-wide-today-owner'
    with db.connection(True) as c:
        db.record(c,'owner','clinic-east',{'name':'SYNTHETIC token owner'},id=owner)
        patient=db.get(c,'luna');db.update(c,patient,{**patient['data'],'owner_id':owner})
    answer=ask(monkeypatch,'Show patients linked to owner ID '+owner,{'read':{'kind':'patient','owner_id':owner}},'luna')
    assert answer['dashboard']['query']=={'kind':'patient','patient_id':'luna','owner_id':owner}
    assert [r['id'] for r in answer['sources']]==['luna']
    widened=ask(monkeypatch,'Show patients linked to owner ID '+owner,{'read':{'kind':'patient','owner_id':owner,'scope':'clinic'}},'luna')
    assert not widened['sources'] and not widened.get('dashboard')

@pytest.mark.parametrize('field',['name','code','unit','species','status'])
@pytest.mark.parametrize('value',[r'"abc\" whole clinic"','"abc whole clinic','"abc" whole clinic"'])
def test_malformed_quoted_named_fields_clarify_before_metadata(monkeypatch,field,value):
    import assistant
    monkeypatch.setattr(assistant,'all_records',lambda *_:pytest.fail('Malformed quoted field must not reach metadata'))
    answer=ask(monkeypatch,f'Show observations whose {field} equals {value}',{'read':{'kind':'observation','scope':'clinic'}},'luna')
    assert not answer.get('dashboard') and not answer.get('action')


@pytest.mark.parametrize('field',['code','unit'])
def test_quoted_observation_filter_cannot_supply_clinic_scope(monkeypatch,field):
    value='SYNTHETIC-clinic-wide-value'
    answer=ask(monkeypatch,f'Show observations whose {field} equals "{value}"',{'read':{'kind':'observation','scope':'clinic',field:value}},'luna')
    assert not answer['sources'] and not answer.get('dashboard')

@pytest.mark.parametrize('name',['conversation.reply','conversation.close','conversation.acknowledge'])
@pytest.mark.parametrize('content',[
    'SYNTHETIC The phrase text contains "whole clinic" was in the record.',
    'SYNTHETIC status is due today; species is Cat; Milo; diagnose; record ID opaque.',
    'SYNTHETIC text contains an unterminated " quote in staff text.',
])
def test_exact_staff_action_text_is_preserved_and_never_reclassified_as_read(monkeypatch,name,content):
    from test_assistant_contracts import fixtures,proposal
    payload=fixtures(monkeypatch)[name]
    field='message' if name=='conversation.reply' else 'reason'
    command=('Reply to' if field=='message' else 'Close' if name=='conversation.close' else 'Acknowledge')
    message=f'{command} conversation {payload["id"]} {field}: {content}'
    result=proposal(monkeypatch,name,{**payload,field:'Model must not substitute these words'},message=message)
    assert result['action']['action']==name and result['action']['payload'][field]==content
    assert not result.get('dashboard')
