"""Native PostgreSQL plot parity with the existing patient numeric chart."""
from datetime import datetime
from test_spine import client,result
from test_integrity import act
from test_record_queries import query,ask


def test_native_numeric_points_ranges_and_receipts_match_existing_patient_chart(client,monkeypatch):
    created=[]
    for i,value in enumerate([0,2,4]):
        payload=result(dedupe_key='native-trend-'+str(i),occurred_at=f'2098-07-{10+i:02}T01:00:00Z',observations=[{'concept':'synthetic_trend','name':'SYNTHETIC trend','value':value,'unit':'mmol/L','ref_low':1 if i!=1 else None,'ref_high':3 if i!=1 else None}],source={'kind':'document','id':'synthetic-trend-'+str(i),'page':i+1,'text':'SYNTHETIC source point '+str(i)})
        response=client.post('/api/v2/ingest/lab',json=payload)
        assert response.status_code==200,response.text
        created.append(client.get('/api/v2/patients/milo/events/'+response.json()['id']).json())
    for i,changes in enumerate([{'patient_id':'luna'},{'observations':[{'concept':'synthetic_trend','name':'SYNTHETIC trend','value':88,'unit':'mg/L'}]}]):
        response=client.post('/api/v2/ingest/lab',json={**payload,**changes,'dedupe_key':'trend-distractor-'+str(i)})
        assert response.status_code==200,response.text
    filters={'kind':'observation','presentation':'trend','patient_id':'milo','code':'synthetic_trend','unit':'mmol/L','start':'2098-07-10','end':'2098-07-12'}
    read=query(filters)
    assert read['count']==len(read['records'])==len(read['trend']['series'])==3 and not read['truncated']
    terms=client.get('/api/v2/patients/milo/concepts').json()
    concept=next(t for t in terms if t['code']=='synthetic_trend' and t['unit']=='mmol/L')
    existing=client.get('/api/v2/patients/milo/observations',params={'concept':concept['id']}).json()['series']
    for actual,original,event in zip(read['trend']['series'],existing,created):
        assert actual['record_id']==event['observations'][0]['id'] and actual['event_id']==event['id']
        assert datetime.fromisoformat(actual['observed_at'].replace('Z','+00:00'))==datetime.fromisoformat(original['observed_at'].replace('Z','+00:00'))
        assert all(actual[k]==original[k] for k in ('value','ref_low','ref_high','flag','source'))
        assert actual['time_basis']=='observed' and actual['source_id']==original['source']['receipt_id']
    answer=ask(monkeypatch,'Plot synthetic_trend in mmol/L from 2098-07-10 to 2098-07-12',{'read':filters},'milo')
    assert answer['dashboard']['trend']==read['trend'] and answer['sources']==read['records']
    view=act('dashboard.save',{'name':'SYNTHETIC native trend','query':answer['dashboard']['query']})
    saved=client.get('/api/dashboards/'+view['id']).json()['result']
    assert saved['query']==filters and saved['trend']==read['trend'] and saved['records']==read['records']
