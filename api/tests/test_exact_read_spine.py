"""Actual PostgreSQL native event reads use the same exact/literal query contract."""
from test_spine import client,result
from test_integrity import act
from test_record_queries import query


def test_native_event_id_and_literal_body_match_timeline_and_saved_view(client):
    payload=result(summary='SYNTHETIC exact source title',body={'text':'SYNTHETIC marker A%_B [literal]'},dedupe_key='exact-read-native')
    created=client.post('/api/v2/ingest/lab',json=payload)
    assert created.status_code==200,created.text
    id=created.json()['id']
    filters={'kind':'event','patient_id':'milo','record_id':id,'text_contains':'a%_b [literal]','category':'lab_result'}
    direct=query(filters)
    assert [r['id'] for r in direct['records']]==[id]
    timeline=client.get('/api/v2/patients/milo/timeline',params={'q':'a%_b [literal]'}).json()['items']
    assert [r['id'] for r in timeline]==[id]
    view=act('dashboard.save',{'name':'SYNTHETIC native exact view','query':filters})
    saved=client.get('/api/dashboards/'+view['id']).json()['result']
    assert saved['query']==filters and saved['records']==direct['records']
    assert query({**filters,'patient_id':'luna'})['count']==0
    assert query({**filters,'kind':'observation','text_contains':None})['count']==0
