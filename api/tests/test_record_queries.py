"""Assistant-to-dashboard parity and explicit, typed clinical query boundaries."""
import uuid
import pytest
from fastapi.testclient import TestClient
import assistant, db, main
from record_queries import dashboard, select_records, validate_query
from test_integrity import isolated, act, get, rows, err


def query(payload):
    with db.connection() as c:return dashboard(c,'clinic-east',payload)


def ask(monkeypatch, message, plan=None, patient=None):
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':plan is not None})
    monkeypatch.setattr(assistant.providers,'model_json',lambda *args:plan)
    with db.connection() as c:return assistant.answer(c,'clinic-east','clinic-east-vet',message,patient)


def test_low_stock_answer_saved_view_and_live_refresh_match(monkeypatch):
    low=act('inventory.create',{'name':'Synthetic low','unit':'tablet','stock':2,'reorder':3},actor='clinic-east-admin')
    high=act('inventory.create',{'name':'Synthetic high','unit':'tablet','stock':8,'reorder':3},actor='clinic-east-admin')
    service=act('inventory.create',{'name':'Synthetic service','unit':'service','stock':0,'reorder':3},actor='clinic-east-admin')
    answer=ask(monkeypatch,'Which stock is low?')
    contract=answer['dashboard']['query'];assert contract['low_stock'] is True
    view=act('dashboard.save',{'name':'Low stock','query':contract})
    client=TestClient(main.app);result=client.get('/api/dashboards/'+view['id']).json()['result']
    assert result['count']==answer['dashboard']['count']
    assert {r['id'] for r in result['records']}=={r['id'] for r in answer['sources']}
    assert low['id'] in {r['id'] for r in result['records']}
    assert not {high['id'],service['id']} & {r['id'] for r in result['records']}
    act('inventory.adjust',{'id':low['id'],'version':low['version'],'stock':4,'reason':'Synthetic count'},actor='clinic-east-admin')
    refreshed=client.get('/api/dashboards/'+view['id']).json()['result']
    assert refreshed['count']==result['count']-1
    assert answer['dashboard']['count']==result['count'] # Saved answer is a snapshot.


def test_general_stock_does_not_silently_mean_low_stock(monkeypatch):
    answer=ask(monkeypatch,'List inventory stock')
    assert 'low_stock' not in answer['dashboard']['query']
    assert answer['dashboard']['count']==len(rows('inventory'))


def test_outstanding_saved_query_uses_actual_positive_balance(monkeypatch):
    invoice=act('invoice.create',{'patient_id':'luna','items':[{'name':'Synthetic','quantity':1,'price_cents':100}]})
    zero=act('invoice.create',{'patient_id':'luna','items':[{'name':'Synthetic free','quantity':1,'price_cents':0}]})
    void=act('invoice.create',{'patient_id':'luna','items':[{'name':'Synthetic void','quantity':1,'price_cents':100}]})
    act('invoice.void',{'id':void['id'],'version':void['version'],'reason':'Synthetic'})
    answer=ask(monkeypatch,'Show outstanding invoices',patient='luna')
    result=query(answer['dashboard']['query'])
    assert result['count']==answer['dashboard']['count']
    ids={r['id'] for r in result['records']};assert invoice['id'] in ids and not {zero['id'],void['id']} & ids
    act('payment.record',{'id':invoice['id'],'version':invoice['version'],'amount_cents':100,'method':'cash'})
    assert query(answer['dashboard']['query'])['count']==result['count']-1


def test_status_and_due_dates_are_persisted_in_model_query(monkeypatch):
    due=act('reminder.create',{'patient_id':'luna','title':'Future synthetic recall','due':'2098-07-10'})
    other=act('reminder.create',{'patient_id':'luna','title':'Other date','due':'2098-07-11'})
    answer=ask(monkeypatch,'Show due reminders on 2098-07-10 grouped by day',{'read':{'kind':'reminder','status':'due','start':'2098-07-10','end':'2098-07-10','group_by':'day'}},'luna')
    result=query(answer['dashboard']['query'])
    assert [r['id'] for r in result['records']]==[due['id']]
    assert result['groups']==[{'label':'2098-07-10','count':1}]
    assert 'status: due' in answer['text'] and other['id'] not in answer['dashboard']['source_ids']


def test_species_filter_is_exact_and_saved_view_matches_assistant(monkeypatch):
    with db.connection(True) as c:
        cat=db.record(c,'patient','clinic-east',{'name':'SYNTHETIC Cat','species':'Cat'})
        dog=db.record(c,'patient','clinic-east',{'name':'SYNTHETIC Dog','species':'Dog'})
    answer=ask(monkeypatch,'Show clinic cats',{'read':{'kind':'patient','scope':'clinic','species':'cat','group_by':'species'}})
    assert cat['id'] in {r['id'] for r in answer['sources']}
    assert dog['id'] not in {r['id'] for r in answer['sources']}
    assert answer['dashboard']['query']['species']=='cat'
    view=act('dashboard.save',{'name':'SYNTHETIC cats','query':answer['dashboard']['query']})
    saved=TestClient(main.app).get('/api/dashboards/'+view['id']).json()['result']
    assert saved['count']==answer['dashboard']['count']
    assert saved['groups']==answer['dashboard']['groups']


def test_exact_clinician_filter_and_grouping_survive_saved_view(monkeypatch):
    with db.connection(True) as c:
        first=db.record(c,'appointment','clinic-east',{'patient_id':'luna','date':'2098-07-10','time':'09:00','reason':'SYNTHETIC check','clinician':'clinic-east-vet','status':'scheduled'})
        other=db.record(c,'appointment','clinic-east',{'patient_id':'luna','date':'2098-07-10','time':'10:00','reason':'SYNTHETIC check','clinician':'clinic-east-nurse','status':'scheduled'})
    plan={'read':{'kind':'appointment','scope':'clinic','clinician':'clinic-east-vet',
                  'start':'2098-07-10','end':'2098-07-10','group_by':'clinician'}}
    answer=ask(monkeypatch,'Show this clinician appointments',plan)
    assert [r['id'] for r in answer['sources']]==[first['id']]
    assert other['id'] not in answer['dashboard']['source_ids']
    assert answer['dashboard']['groups']==[{'label':'clinic-east-vet','count':1}]
    view=act('dashboard.save',{'name':'SYNTHETIC clinician','query':answer['dashboard']['query']})
    saved=TestClient(main.app).get('/api/dashboards/'+view['id']).json()['result']
    assert [r['id'] for r in saved['records']]==[first['id']]


def test_appointment_species_joins_only_clinic_patients_and_survives_saved_view(monkeypatch):
    with db.connection(True) as c:
        cat=db.record(c,'appointment','clinic-east',{'patient_id':'luna','date':'2098-08-10','time':'09:00','reason':'SYNTHETIC species check','clinician':'clinic-east-vet','status':'scheduled'})
        dog=db.record(c,'appointment','clinic-east',{'patient_id':'milo','date':'2098-08-10','time':'10:00','reason':'SYNTHETIC species check','clinician':'clinic-east-vet','status':'scheduled'})
        foreign=db.record(c,'patient','clinic-river',{'name':'SYNTHETIC Foreign Cat','species':'Cat'})
        db.record(c,'appointment','clinic-east',{'patient_id':foreign['id'],'date':'2098-08-10','time':'11:00','reason':'SYNTHETIC bad link','clinician':'clinic-east-vet','status':'scheduled'})
        db.record(c,'appointment','clinic-east',{'patient_id':['malformed'],'date':'2098-08-10','time':'12:00','reason':'SYNTHETIC malformed link','clinician':'clinic-east-vet','status':'scheduled'})
    plan={'read':{'kind':'appointment','scope':'clinic','species':'cat','clinician':'clinic-east-vet',
                  'start':'2098-08-10','end':'2098-08-10','group_by':'species'}}
    answer=ask(monkeypatch,'Show Cat appointments for this clinician, grouped by species',plan)
    assert [r['id'] for r in answer['sources']]==[cat['id']]
    assert answer['dashboard']['groups']==[{'label':'Cat','count':1}]
    assert 'species: cat' in answer['text']
    view=act('dashboard.save',{'name':'SYNTHETIC Cat appointments','query':answer['dashboard']['query']})
    saved=TestClient(main.app).get('/api/dashboards/'+view['id']).json()['result']
    assert saved['query']==answer['dashboard']['query']
    assert [r['id'] for r in saved['records']]==[cat['id']]
    grouped=query({'kind':'appointment','start':'2098-08-10','end':'2098-08-10','group_by':'species'})
    assert {'label':'Cat','count':1} in grouped['groups']
    assert {'label':'Dog','count':1} in grouped['groups']
    assert {'label':'Not recorded','count':2} in grouped['groups']
    assert dog['id'] not in {r['id'] for r in answer['sources']}


def test_primary_and_additional_owner_patients_match_live_saved_view(monkeypatch):
    owner=act('owner.create',{'name':'SYNTHETIC Shared Household'})
    primary=act('patient.create',{'name':'SYNTHETIC Primary Pet','species':'Cat','owner_id':owner['id']})
    additional=act('patient.create',{'name':'SYNTHETIC Additional Pet','species':'Dog','owner_name':'Another Synthetic Owner'})
    additional=act('patient.owners',{'id':additional['id'],'version':additional['version'],
                                     'owner_id':additional['data']['owner_id'],'additional_owner_ids':[owner['id']]})
    plan={'read':{'kind':'patient','scope':'clinic','owner_id':owner['id'],'group_by':'species'}}
    answer=ask(monkeypatch,'Show all pets linked to SYNTHETIC Shared Household, grouped by species',plan)
    assert {r['id'] for r in answer['sources']}=={primary['id'],additional['id']}
    assert answer['dashboard']['groups']==[{'label':'Cat','count':1},{'label':'Dog','count':1}]
    assert 'owner: SYNTHETIC Shared Household' in answer['text']
    view=act('dashboard.save',{'name':'SYNTHETIC owner pets','query':answer['dashboard']['query']})
    client=TestClient(main.app)
    saved=client.get('/api/dashboards/'+view['id']).json()['result']
    assert {r['id'] for r in saved['records']}=={primary['id'],additional['id']}
    act('patient.owners',{'id':additional['id'],'version':additional['version'],
                          'owner_id':additional['data']['owner_id'],'additional_owner_ids':[]})
    refreshed=client.get('/api/dashboards/'+view['id']).json()['result']
    assert [r['id'] for r in refreshed['records']]==[primary['id']]
    with db.connection(True) as c:
        foreign=db.record(c,'owner','clinic-river',{'name':'SYNTHETIC Other Clinic'})
        db.record(c,'patient','clinic-east',{'name':'SYNTHETIC malformed links','species':'Cat','owner_id':'owner-luna','additional_owner_ids':None})
    assert [r['id'] for r in query({'kind':'patient','owner_id':owner['id']})['records']]==[primary['id']]
    err(404,lambda:query({'kind':'patient','owner_id':foreign['id']}))
    err(422,lambda:query({'kind':'invoice','owner_id':owner['id']}))


def test_owner_appointments_follow_current_clinic_patient_links(monkeypatch):
    owner=act('owner.create',{'name':'SYNTHETIC Appointment Household'})
    primary=act('patient.create',{'name':'SYNTHETIC Appointment Cat','species':'Cat','owner_id':owner['id']})
    additional=act('patient.create',{'name':'SYNTHETIC Appointment Dog','species':'Dog','owner_name':'Another Synthetic Household'})
    additional=act('patient.owners',{'id':additional['id'],'version':additional['version'],
                                     'owner_id':additional['data']['owner_id'],'additional_owner_ids':[owner['id']]})
    with db.connection(True) as c:
        cat=db.record(c,'appointment','clinic-east',{'patient_id':primary['id'],'date':'2098-08-04','time':'09:00','reason':'SYNTHETIC owner check','clinician':'clinic-east-vet','status':'scheduled'})
        dog=db.record(c,'appointment','clinic-east',{'patient_id':additional['id'],'date':'2098-08-04','time':'10:00','reason':'SYNTHETIC owner check','clinician':'clinic-east-vet','status':'scheduled'})
        db.record(c,'appointment','clinic-east',{'patient_id':'luna','date':'2098-08-04','time':'11:00','reason':'SYNTHETIC unrelated','clinician':'clinic-east-vet','status':'scheduled'})
        foreign=db.record(c,'patient','clinic-river',{'name':'SYNTHETIC foreign link','species':'Cat','owner_id':owner['id']})
        db.record(c,'appointment','clinic-east',{'patient_id':foreign['id'],'date':'2098-08-04','time':'12:00','reason':'SYNTHETIC foreign link','clinician':'clinic-east-vet','status':'scheduled'})
        db.record(c,'appointment','clinic-east',{'patient_id':['malformed'],'date':'2098-08-04','time':'13:00','reason':'SYNTHETIC bad link','clinician':'clinic-east-vet','status':'scheduled'})
    plan={'read':{'kind':'appointment','scope':'clinic','owner_id':owner['id'],'clinician':'clinic-east-vet',
                  'start':'2098-08-04','end':'2098-08-04','group_by':'species'}}
    answer=ask(monkeypatch,'Show appointments linked to SYNTHETIC Appointment Household',plan)
    assert {r['id'] for r in answer['sources']}=={cat['id'],dog['id']}
    assert answer['dashboard']['groups']==[{'label':'Cat','count':1},{'label':'Dog','count':1}]
    assert 'owner: SYNTHETIC Appointment Household' in answer['text']
    view=act('dashboard.save',{'name':'SYNTHETIC household appointments','query':answer['dashboard']['query']})
    client=TestClient(main.app)
    saved=client.get('/api/dashboards/'+view['id']).json()['result']
    assert saved['query']==answer['dashboard']['query']
    assert {r['id'] for r in saved['records']}=={cat['id'],dog['id']}
    act('patient.owners',{'id':additional['id'],'version':additional['version'],
                          'owner_id':additional['data']['owner_id'],'additional_owner_ids':[]})
    refreshed=client.get('/api/dashboards/'+view['id']).json()['result']
    assert [r['id'] for r in refreshed['records']]==[cat['id']]
    with db.connection(True) as c:foreign_owner=db.record(c,'owner','clinic-river',{'name':'SYNTHETIC foreign owner'})
    err(404,lambda:query({'kind':'appointment','owner_id':foreign_owner['id']}))


def test_duplicate_owner_names_require_exact_identity_before_model_query(monkeypatch):
    first=act('owner.create',{'name':'SYNTHETIC Same Client'})
    act('owner.create',{'name':'SYNTHETIC Same Client'})
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(assistant.providers,'model_json',lambda *args:pytest.fail('Ambiguous owner reached the model'))
    with db.connection() as c:
        result=assistant.answer(c,'clinic-east','clinic-east-vet','Show pets linked to SYNTHETIC Same Client')
    assert 'exact owner ID' in result['text'] and 'dashboard' not in result
    selected=ask(monkeypatch,'Show pets linked to SYNTHETIC Same Client, owner ID '+first['id'],
                 {'read':{'kind':'patient','scope':'clinic','owner_id':first['id']}})
    assert selected['dashboard']['query']['owner_id']==first['id']
    assert selected['dashboard']['count']==0


def test_owner_specific_questions_never_drop_or_replace_the_owner_filter(monkeypatch):
    requested=act('owner.create',{'name':'SYNTHETIC Scope Requested'})
    other=act('owner.create',{'name':'SYNTHETIC Scope Other'})
    act('patient.create',{'name':'SYNTHETIC Scope Pet','species':'Cat','owner_id':requested['id']})
    message='Show all pets linked to SYNTHETIC Scope Requested in the whole clinic'
    for read in ({'kind':'patient','scope':'clinic'},
                 {'kind':'patient','scope':'clinic','owner_id':other['id']},
                 {'kind':'invoice','scope':'clinic','outstanding':True}):
        answer=ask(monkeypatch,message,{'read':read})
        assert 'cannot safely answer' in answer['text']
        assert answer['sources']==[] and 'dashboard' not in answer
    unknown=ask(monkeypatch,'Show pets linked to owner ID not-a-clinic-owner',{'read':{'kind':'patient','scope':'clinic'}})
    assert 'cannot safely answer' in unknown['text'] and 'dashboard' not in unknown
    valid=ask(monkeypatch,message,{'read':{'kind':'patient','scope':'clinic','owner_id':requested['id']}})
    assert valid['dashboard']['count']==1
    assert valid['dashboard']['query']['owner_id']==requested['id']


def test_clinic_timezone_uses_occurrence_instead_of_utc_date():
    with db.connection(True) as c:
        first=db.record(c,'event','clinic-east',{'patient_id':'luna','title':'Midnight clinic time','occurred_at':'2026-09-23T16:30:00Z'})
        db.record(c,'event','clinic-east',{'patient_id':'luna','title':'Before midnight','occurred_at':'2026-09-23T15:30:00Z'})
    r=query({'kind':'event','patient_id':'luna','start':'2026-09-24','end':'2026-09-24','group_by':'day'})
    assert first['id'] in {x['id'] for x in r['records']}
    assert all(x['data'].get('title')!='Before midnight' for x in r['records'])
    assert r['timezone']=='Asia/Singapore'


def test_malformed_legacy_date_falls_back_to_record_date_and_invalid_timezone_fails():
    with db.connection(True) as c:
        row=db.record(c,'event','clinic-east',{'patient_id':'luna','date':7,'title':'SYNTHETIC malformed date'})
        invalid=db.record(c,'event','clinic-east',{'patient_id':'luna','date':'2098-99-99','title':'SYNTHETIC invalid calendar date'})
    result=query({'kind':'event','patient_id':'luna','group_by':'day'})
    assert {row['id'],invalid['id']} <= {item['id'] for item in result['records']}
    assert '2098-99-99' not in {item['label'] for item in result['groups']}
    with db.connection(True) as c:
        clinic=db.get(c,'clinic-east')
        db.update(c,clinic,{**clinic['data'],'timezone':None})
    err(409,lambda:query({'kind':'event'}))


def test_typed_equality_false_is_not_zero_and_exact_unit_comparisons():
    with db.connection(True) as c:
        facts=[]
        for v,u in [(False,''),(0,''),(True,''),('false',''),(6.2,'mmol/L'),(7.2,'mg/dL'),(4.2,'mmol/L')]:
            facts.append(db.record(c,'observation','clinic-east',{'patient_id':'luna','name':'Synthetic fact','code':'synthetic','value':v,'unit':u}))
    assert [r['id'] for r in query({'kind':'observation','code':'synthetic','value_equals':False})['records']]==[facts[0]['id']]
    assert [r['id'] for r in query({'kind':'observation','code':'synthetic','unit':'mmol/L','value_min':5,'value_max':7})['records']]==[facts[4]['id']]
    assert [r['id'] for r in query({'kind':'observation','code':'synthetic','value_equals':'false'})['records']]==[facts[3]['id']]


@pytest.mark.parametrize('payload',[
    {'kind':'invoice','low_stock':True}, {'kind':'inventory','outstanding':True},
    {'kind':'observation','value_min':2}, {'kind':'observation','code':'potassium','value_min':2},
    {'kind':'observation','code':'potassium','unit':'mmol/L','value_min':7,'value_max':2},
    {'kind':'observation','code':'x','value_equals':False,'value_min':2,'unit':'x'},
    {'kind':'observation','code':'x','unit':'x','value_min':True},
    {'kind':'observation','code':'x','value_equals':float('inf')},
    {'kind':'invoice','low_stock':'false'}, {'kind':'patient','status':'due'},
    {'kind':'invoice','species':'Cat'}, {'kind':'patient','clinician':'clinic-east-vet'},
    {'kind':'patient','owner_id':''}, {'kind':'patient','owner_id':False},
    {'kind':'patient','group_by':'clinician'}, {'kind':'inventory','group_by':'species'},
    {'kind':'invoice','start':'20260924'}, {'kind':'invoice','start':'2099-02-30'},
    {'kind':'event','start':'2099-02-01','end':'2099-01-01'},
    {'kind':'event','arbitrary_sql':'SELECT secret'}, {'kind':'event','group_by':'secret'},
    {'kind':'event','name':'silently ignored field'}, {'kind':'settings'},
])
def test_unsupported_or_malformed_filters_fail_closed(payload):
    err(422,lambda:query(payload))
    err(422,lambda:act('dashboard.save',{'name':'Invalid','query':payload}))


def test_cross_clinic_and_explicit_patient_scope(monkeypatch):
    source=act('source.add',{'patient_id':'milo','text':'Other patient fact'})
    answer=ask(monkeypatch,'Show events',{'read':{'kind':'event'}},'luna')
    assert all(r['data']['patient_id']=='luna' for r in answer['sources'])
    assert source['id'] not in answer['text']
    with db.connection() as c:
        err(404,lambda:validate_query(c,{'kind':'event','patient_id':'luna'},'clinic-river'))
        foreign={'id':'foreign','clinic_id':'clinic-river','kind':'patient','created_at':'2026-01-01','data':{'name':'Foreign'}}
        assert select_records(c,'clinic-east',{'kind':'patient'},[foreign])['count']==0


def test_model_filters_and_query_catalog_are_explicit(monkeypatch):
    seen=[]
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    def provider(_,payload):
        seen.append(payload)
        return {'read':{'kind':'observation','code':'weight','unit':'kg','value_min':2}}
    monkeypatch.setattr(assistant.providers,'model_json',provider)
    with db.connection() as c:r=assistant.answer(c,'clinic-east','clinic-east-vet','Show recorded weights at least 2 kg','luna')
    assert r['dashboard']['query']['value_min']==2
    assert 'value_equals' in seen[0]['read_contract']['properties']
    assert 'additionalProperties' in seen[0]['read_contract'] and seen[0]['read_contract']['additionalProperties'] is False


def test_invalid_model_filter_is_not_ignored(monkeypatch):
    for plan in ({'read':{'kind':'observation','secret_filter':'nonsense'}},
                 {'read':{'kind':'event','scope':'all_accounts'}}):
        answer=ask(monkeypatch,'Show facts',plan)
        assert 'cannot safely answer' in answer['text']
        assert answer['sources']==[] and 'dashboard' not in answer


def test_unsupported_model_read_is_completed_and_replays_without_query_leak(monkeypatch):
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    calls=[]
    monkeypatch.setattr(assistant.providers,'model_json',lambda *args:calls.append(args) or {'read':{'kind':'invoice','owner_id':'owner-luna'}})
    client=TestClient(main.app)
    payload={'message':'Show invoices linked to this owner','key':'synthetic-unsupported-owner-invoice'}
    first=client.post('/api/assistant',json=payload)
    assert first.status_code==200
    body=first.json()
    assert 'cannot safely answer' in body['text'] and body['sources']==[] and 'dashboard' not in body
    assert client.post('/api/assistant',json=payload).json()==body
    assert len(calls)==1
    saved=client.get('/api/assistant/conversations/'+body['conversation_id']).json()
    assert saved['turns'][0]['status']=='completed' and saved['turns'][0]['text']==body['text']
    assert client.post(f"/api/assistant/conversations/{body['conversation_id']}/turns/{body['turn_id']}/confirm").status_code==409


def test_clinic_wide_override_includes_native_facts_outside_original_patient(monkeypatch):
    native={'id':'native-other','kind':'event','clinic_id':'clinic-east','created_at':'2026-09-24T00:00:00Z','data':{'patient_id':'milo','title':'Native other patient'}}
    monkeypatch.setattr('spine.reader.native_records',lambda clinic,pid=None: [native] if pid in (None,'milo') else [])
    answer=ask(monkeypatch,'Show clinic-wide events',{'read':{'kind':'event','scope':'clinic'}},'luna')
    assert any(r['id']==native['id'] for r in answer['sources'])


def test_bounded_receipts_do_not_truncate_totals_or_change_order(monkeypatch):
    with db.connection(True) as c:
        for i in range(105):db.record(c,'event','clinic-east',{'patient_id':'luna','title':f'Synthetic {i}','category':'test_only'})
    answer=ask(monkeypatch,'Show synthetic events',{'read':{'kind':'event','category':'test_only'}},'luna')
    result=query(answer['dashboard']['query'])
    assert result['count']==105 and len(result['records'])==100 and result['truncated'] is True
    assert answer['dashboard']['count']==105 and len(answer['sources'])==30
    assert answer['dashboard']['source_ids']==[r['id'] for r in result['records']]
    assert 'Showing 12 of 105' in answer['text']


def test_transferred_history_is_distinct_from_local_prescription(monkeypatch):
    with db.connection(True) as c:
        history=db.record(c,'medication_history','clinic-east',{'patient_id':'luna','dose':'Original synthetic dose','frequency':'Source frequency','instructions':'Historical only'})
    answer=ask(monkeypatch,'Show medication history',{'read':{'kind':'medication_history'}},'luna')
    assert [r['id'] for r in answer['sources']]==[history['id']]
    assert 'Original synthetic dose' in answer['text'] and not rows('medication')


def test_legacy_saved_queries_still_read_without_new_fields():
    view=act('dashboard.save',{'name':'Legacy shape','query':{'kind':'invoice','patient_id':None,'start':None,'end':None,'category':''}})
    result=TestClient(main.app).get('/api/dashboards/'+view['id'])
    assert result.status_code==200 and result.json()['result']['count']==len(rows('invoice'))
