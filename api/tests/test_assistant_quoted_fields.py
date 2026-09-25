"""Common quoted observation-filter spelling preserves patient scope."""
import pytest
import assistant,db
from test_integrity import isolated
from test_record_queries import ask


@pytest.mark.parametrize('field',['code','unit'])
@pytest.mark.parametrize('relation',['','equals ','is '])
def test_quoted_observation_values_cannot_widen_scope_or_add_dates(monkeypatch,field,relation):
    value='SYNTHETIC-clinic-wide-today-Milo-value'
    with db.connection(True) as c:
        wanted=db.record(c,'observation','clinic-east',{'patient_id':'luna','code':'synthetic','unit':'mg/L','value':1,field:value,'observed_at':'2098-07-10T01:00:00Z'})
        db.record(c,'observation','clinic-east',{**wanted['data'],'patient_id':'milo'})
    question=f'Show observations with {field} {relation}"{value}"'
    exact=ask(monkeypatch,question,{'read':{'kind':'observation',field:value}},'luna')
    assert exact['dashboard']['query']=={'kind':'observation','patient_id':'luna',field:value}
    assert exact['dashboard']['source_ids']==[wanted['id']]
    widened=ask(monkeypatch,question,{'read':{'kind':'observation','scope':'clinic',field:value}},'luna')
    assert not widened.get('dashboard') and not widened['sources']


@pytest.mark.parametrize('field',['code','unit'])
@pytest.mark.parametrize('value',[r'"abc\" whole clinic"','"abc whole clinic','"abc" whole clinic"'])
def test_malformed_short_quoted_observation_filter_clarifies_early(monkeypatch,field,value):
    monkeypatch.setattr(assistant,'all_records',lambda *_:pytest.fail('Malformed quoted field must not retrieve metadata'))
    answer=ask(monkeypatch,f'Show observations with {field} {value}',{'read':{'kind':'observation','scope':'clinic'}},'luna')
    assert not answer.get('dashboard') and not answer.get('action')
