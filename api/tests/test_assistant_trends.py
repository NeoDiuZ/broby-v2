"""Numeric trend receipts, selection integrity, limits and live saved views."""
import copy
import pytest
from fastapi.testclient import TestClient
import assistant,db,main
from test_integrity import isolated,act,get,err
from test_record_queries import ask,query

BASE={'kind':'observation','presentation':'trend','patient_id':'luna','code':'synthetic_marker','unit':'mmol/L'}
MESSAGE='Plot synthetic_marker in mmol/L from 2098-07-10 to 2098-07-12'


def measurements(n=3):
    with db.connection(True) as c:
        source=db.record(c,'source','clinic-east',{'patient_id':'luna','title':'SYNTHETIC report','text':'SYNTHETIC original values 0, 2, 4 mmol/L'})
        def make(i,**extra):
            data={'patient_id':'luna','code':'synthetic_marker','name':'SYNTHETIC marker','unit':'mmol/L','value_type':'number','value':i*2,'low':1 if i!=1 else None,'high':3 if i!=1 else None,'source_id':source['id'],'observed_at':f'2098-07-{10+i%3:02}T01:00:00Z',**extra}
            return db.record(c,'observation','clinic-east',data)
        points=[make(i) for i in range(n)]
        make(9,patient_id='milo');make(9,unit='mg/L');make(9,code='other_marker',name='SYNTHETIC other marker');make(9,observed_at='2098-07-13T01:00:00Z')
    return points,source


def test_answer_saved_query_chart_and_sources_are_identical_and_refresh_live(monkeypatch):
    points,source=measurements()
    answer=ask(monkeypatch,MESSAGE,{'read':{**BASE,'start':'2098-07-10','end':'2098-07-12'}},'luna')
    chart=answer['dashboard'];series=chart['trend']['series']
    assert chart['count']==len(answer['sources'])==len(series)==3
    assert chart['query']=={**BASE,'start':'2098-07-10','end':'2098-07-12'}
    assert [p['record_id'] for p in series]==[r['id'] for r in points]
    assert [(p['value'],p['ref_low'],p['ref_high'],p['flag']) for p in series]==[(0,1,3,'low'),(2,None,None,None),(4,1,3,'high')]
    assert all(p['version']==1 and p['source_id']==source['id'] and p['time_basis']=='observed' for p in series)
    view=act('dashboard.save',{'name':'SYNTHETIC numeric chart','query':chart['query']})
    client=TestClient(main.app);saved=client.get('/api/dashboards/'+view['id']).json()['result']
    assert saved['trend']==chart['trend'] and saved['records']==answer['sources'] and not saved['truncated']
    with db.connection(True) as c:db.update(c,points[0],{**points[0]['data'],'value':1.5})
    refreshed=client.get('/api/dashboards/'+view['id']).json()['result']
    assert refreshed['trend']['series'][0]['value']==1.5 and refreshed['trend']['series'][0]['version']==2
    assert series[0]['value']==0 and series[0]['version']==1


@pytest.mark.parametrize('change',[{'presentation':'count'},{'unit':'mg/L'},{'code':'other_marker'},{'patient_id':'milo'},{'scope':'clinic'},{'start':'2098-07-11'},{'end':'2098-07-13'}])
def test_model_cannot_substitute_chart_identity_unit_or_dates(monkeypatch,change):
    measurements()
    answer=ask(monkeypatch,MESSAGE,{'read':{**BASE,**change}},'luna')
    assert not answer['sources'] and not answer.get('dashboard') and not answer.get('action')


@pytest.mark.parametrize('message,patient',[
    ('Plot synthetic_marker','luna'),('Plot synthetic_marker in an inferred unit','luna'),
    ('Plot synthetic_marker in mmol/L or mg/L','luna'),
    ('Plot synthetic_marker and other_marker in mmol/L','luna'),
    ('Plot synthetic_marker in mmol/L from 2098-07-12 to 2098-07-10','luna'),
    ('Plot synthetic_marker in mmol/L from 2098-02-31 to 2098-07-10','luna'),
    ('Plot synthetic_marker in mmol/L since 2098-07-10','luna'),
    ('Plot synthetic_marker in mmol/L',None),
])
def test_missing_or_ambiguous_plot_scope_clarifies_before_provider(monkeypatch,message,patient):
    measurements()
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(assistant.providers,'model_json',lambda *_:pytest.fail('Ambiguous trend must clarify before invoking the model'))
    with db.connection() as c:answer=assistant.answer(c,'clinic-east','clinic-east-vet',message,patient)
    assert not answer['sources'] and not answer.get('dashboard')


def test_implicit_name_resolves_only_one_recorded_code_unit_and_no_unsolicited_plot(monkeypatch):
    measurements()
    answer=ask(monkeypatch,'Show a trend for SYNTHETIC marker in mmol/L',{'read':BASE},'luna')
    assert answer['dashboard']['trend']['concept']['code']=='synthetic_marker'
    wrong=ask(monkeypatch,'Count observations',{'read':BASE},'luna')
    assert not wrong.get('dashboard')
    with db.connection(True) as c:db.record(c,'observation','clinic-east',{'patient_id':'luna','name':'SYNTHETIC marker','code':'different_meaning','unit':'mmol/L','value':3})
    ambiguous=ask(monkeypatch,'Plot SYNTHETIC marker in mmol/L',{'read':BASE},'luna')
    assert not ambiguous.get('dashboard')


def test_two_hundred_points_have_complete_sources_and_over_limit_never_truncates(monkeypatch):
    points,_=measurements(200)
    filters={**BASE,'start':'2098-07-10','end':'2098-07-12'}
    answer=ask(monkeypatch,MESSAGE,{'read':filters},'luna')
    assert len(answer['sources'])==len(answer['dashboard']['source_ids'])==len(answer['dashboard']['trend']['series'])==200
    saved=query(filters);assert len(saved['records'])==200 and not saved['truncated'] and saved['record_limit']==200
    with db.connection(True) as c:db.record(c,'observation','clinic-east',points[0]['data'])
    blocked=ask(monkeypatch,MESSAGE,{'read':filters},'luna')
    assert not blocked.get('dashboard') and not blocked['sources'] and '201 records' in blocked['text'] and '200 points' in blocked['text']
    err(422,lambda:query(filters))


@pytest.mark.parametrize('change',[{'value':True},{'value':'2.5'},{'value_type':'text'},{'value':float('inf')},{'low':4,'high':1},{'low':'1'},{'observed_at':'invalid'}])
def test_invalid_values_ranges_and_timestamps_are_not_silently_omitted(change):
    points,_=measurements()
    # Pass injected legacy shapes directly; nonfinite JSON cannot be stored in PostgreSQL.
    from record_queries import select_records
    row=copy.deepcopy(points[0]);row['data'].update(change)
    with db.connection() as c:err(422,lambda:select_records(c,'clinic-east',BASE,[row]))


def test_dates_use_observed_time_in_clinic_timezone_and_label_record_time_fallback():
    points,_=measurements()
    with db.connection(True) as c:
        db.update(c,points[0],{**points[0]['data'],'observed_at':'2098-07-09T16:00:00Z','low':None,'high':3})
        db.update(c,points[1],{**points[1]['data'],'observed_at':None})
    first=query({**BASE,'start':'2098-07-10','end':'2098-07-10'})['trend']['series']
    assert len(first)==1 and first[0]['record_id']==points[0]['id'] and first[0]['ref_low'] is None and first[0]['ref_high']==3
    fallback=next(p for p in query(BASE)['trend']['series'] if p['record_id']==points[1]['id'])
    assert fallback['time_basis']=='recorded' and fallback['observed_at']==points[1]['created_at']
    assert query({**BASE,'start':'2100-01-01'})['trend']['series']==[]


@pytest.mark.parametrize('change',[{'kind':'event'},{'patient_id':None},{'code':''},{'unit':''},{'group_by':'day'}])
def test_direct_trend_contract_requires_one_patient_code_unit(change):
    err(422,lambda:query({**BASE,**change}))


def test_legacy_count_contract_stays_byte_for_byte_compatible():
    result=query({'kind':'event','presentation':'count'})
    assert result['query']=={'kind':'event'} and 'trend' not in result and result['record_limit']==100


def test_saved_plot_and_answer_stay_permission_gated(monkeypatch):
    from test_read_access import restrict
    measurements();monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(assistant.providers,'model_json',lambda *_:{'read':BASE})
    cli=TestClient(main.app)
    answer=cli.post('/api/assistant',json={'message':MESSAGE,'patient_id':'luna','key':'saved-trend'}).json()
    view=act('dashboard.save',{'name':'SYNTHETIC restricted trend','query':answer['dashboard']['query']})
    restrict('read.clinical')
    assert cli.get('/api/dashboards/'+view['id']).status_code==403
    assert cli.get('/api/assistant/conversations/'+answer['conversation_id']).status_code==403


def test_reconciliation_removes_chart_and_sources_from_live_view_and_prior_answer(monkeypatch):
    from test_clinical_reconciliation import fixture,preview,decision
    from test_transfers import TARGET,HEADERS
    monkeypatch.setattr('spine.reconciliation.native_dependents',lambda *a,**k:{})
    cli,old,_,correction=fixture()
    source=act('source.add',{'patient_id':old['id'],'text':'SYNTHETIC supplied weight 12 kg'},**TARGET)
    row=act('observation.record',{'patient_id':old['id'],'source_id':source['id'],'code':'weight','value':12},**TARGET)
    filters={'kind':'observation','presentation':'trend','patient_id':old['id'],'code':row['data']['code'],'unit':row['data']['unit']}
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(assistant.providers,'model_json',lambda *_:{'read':filters})
    answer=cli.post('/api/assistant',headers=HEADERS,json={'message':f'Plot {filters["code"]} in {filters["unit"]}','patient_id':old['id'],'key':'held-trend'}).json()
    assert answer['dashboard']['trend']['series']
    view=act('dashboard.save',{'name':'SYNTHETIC held trend','query':filters},**TARGET)
    act('clinical.reconcile',decision(preview(cli,correction),old['id']),**TARGET)
    refreshed=cli.get('/api/dashboards/'+view['id'],headers=HEADERS).json()['result']
    assert refreshed['count']==0 and not refreshed['records'] and not refreshed['trend']['series']
    stale=cli.get('/api/assistant/conversations/'+answer['conversation_id'],headers=HEADERS).json()['turns'][0]
    assert not stale.get('dashboard') and not stale['sources'] and stale['clinical_reconciliation']['status']=='historical_unverified'


def test_case_distinct_concept_codes_are_never_merged(monkeypatch):
    points,_=measurements()
    with db.connection(True) as c:other=db.record(c,'observation','clinic-east',{**points[0]['data'],'code':'SYNTHETIC_MARKER','name':'SYNTHETIC uppercase marker','value':99})
    filters={**BASE,'start':'2098-07-10','end':'2098-07-12'}
    assert query(filters)['count']==3 and other['id'] not in {r['id'] for r in query(filters)['records']}
    message='Plot observations whose code equals "synthetic_marker" and unit equals "mmol/L" from 2098-07-10 to 2098-07-12'
    answer=ask(monkeypatch,message,{'read':filters},'luna')
    assert answer['dashboard']['count']==3
    wrong=ask(monkeypatch,message,{'read':{**filters,'code':'SYNTHETIC_MARKER'}},'luna')
    assert not wrong.get('dashboard')


def test_quoted_trend_code_and_unit_are_data_not_clinic_scope_dates_or_patient(monkeypatch):
    with db.connection(True) as c:
        data={'code':'SYNTHETIC-clinic-wide-today-Milo','name':'SYNTHETIC exact marker','unit':'SYNTHETIC-whole clinic','value':0,'observed_at':'2098-07-10T01:00:00Z'}
        wanted=db.record(c,'observation','clinic-east',{**data,'patient_id':'luna'})
        db.record(c,'observation','clinic-east',{**data,'patient_id':'milo'})
    message=f'Plot observations whose code equals "{data["code"]}" and unit equals "{data["unit"]}"'
    filters={**BASE,'code':data['code'],'unit':data['unit']}
    answer=ask(monkeypatch,message,{'read':filters},'luna')
    assert answer['dashboard']['query']==filters and answer['dashboard']['source_ids']==[wanted['id']]
    assert not ask(monkeypatch,message,{'read':{**filters,'scope':'clinic'}},'luna').get('dashboard')


@pytest.mark.parametrize('extra',[{'value_min':1},{'value_max':1},{'value_equals':2},{'category':'lab'},{'name':'SYNTHETIC marker'},{'start':'2098-07-11'},{'end':'2098-07-11'},{'record_id':'first'}])
def test_model_cannot_invent_subset_filters_or_unsupplied_dates(monkeypatch,extra):
    points,_=measurements()
    if extra.get('record_id')=='first':extra={'record_id':points[0]['id']}
    answer=ask(monkeypatch,'Plot observations with code "synthetic_marker" and unit "mmol/L"',{'read':{**BASE,**extra}},'luna')
    assert not answer.get('dashboard') and not answer['sources']


@pytest.mark.parametrize('extra',[{'value_min':1},{'value_max':1},{'value_equals':2},{'category':'lab'},{'name':'SYNTHETIC marker'},{'record_id':'first'}])
def test_direct_saved_trend_contract_rejects_additional_subsets(extra):
    measurements();err(422,lambda:query({**BASE,**extra}))


def test_model_cannot_hide_over_limit_points_with_unasked_numeric_filter(monkeypatch):
    measurements(201)
    answer=ask(monkeypatch,MESSAGE,{'read':{**BASE,'value_min':399}},'luna')
    assert not answer.get('dashboard') and not answer['sources']


def test_relative_trend_dates_are_pinned_and_missing_model_bounds_are_completed(monkeypatch):
    from datetime import date
    measurements()
    monkeypatch.setattr(assistant,'period',lambda query,timezone:(date(2098,7,10),date(2098,7,12)))
    answer=ask(monkeypatch,'Plot synthetic_marker in mmol/L this week',{'read':BASE},'luna')
    assert answer['dashboard']['query']=={**BASE,'start':'2098-07-10','end':'2098-07-12'}
    wrong=ask(monkeypatch,'Plot synthetic_marker in mmol/L this week',{'read':{**BASE,'start':'2098-07-11'}},'luna')
    assert not wrong.get('dashboard')


def test_explicit_unsupported_trend_filter_clarifies_instead_of_dropping_condition(monkeypatch):
    measurements()
    answer=ask(monkeypatch,'Plot synthetic_marker in mmol/L with value at least 2',{'read':{**BASE,'value_min':2}},'luna')
    assert not answer.get('dashboard') and not answer['sources']


@pytest.mark.parametrize('condition',['with value at least 2','where value equals 0','above 2','where value > 2','with category "lab"','grouped by day','with code "synthetic_marker" and name "SYNTHETIC marker"'])
def test_model_cannot_drop_explicit_unsupported_trend_condition(monkeypatch,condition):
    measurements()
    answer=ask(monkeypatch,'Plot synthetic_marker in mmol/L '+condition,{'read':BASE},'luna')
    assert not answer.get('dashboard') and not answer['sources']
