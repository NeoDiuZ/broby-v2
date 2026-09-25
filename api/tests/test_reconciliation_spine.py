"""Native PostgreSQL exclusion while preserving the entire forensic archive."""
import pytest
import db
from test_spine import client,result
from test_integrity import act
from test_transfers import TARGET, HEADERS
from test_clinical_reconciliation import fixture, preview, decision
from spine import database,service
from spine.models import Event


def test_native_timeline_measurements_receipts_owner_and_counts_follow_hold(client,monkeypatch,tmp_path):
    monkeypatch.setattr(db,'DATA',tmp_path)
    _,old,new,id=fixture()
    payload=result(patient_id=old['id'],dedupe_key='SYNTHETIC-native-before-reconciliation')
    response=client.post('/api/v2/ingest/lab',headers=HEADERS,json=payload);assert response.status_code==200,response.text
    eid=response.json()['id'];act('clinical.approve',{'id':eid,'approved':True},**TARGET)
    before=client.get('/api/v2/patients/'+old['id']+'/events/'+eid,headers=HEADERS).json()
    source=before['source']['receipt_id']
    assert client.get('/api/v2/patients/'+old['id']+'/concepts',headers=HEADERS).json()
    review=preview(client,id);act('clinical.reconcile',decision(review,old['id']),**TARGET)
    timeline=client.get('/api/v2/patients/'+old['id']+'/timeline',headers=HEADERS)
    assert timeline.status_code==200,timeline.text
    assert timeline.json()['items']==[]
    assert client.get('/api/v2/patients/'+old['id']+'/concepts',headers=HEADERS).json()==[]
    assert client.get('/api/v2/patients/'+old['id']+'/observations?concept=potassium',headers=HEADERS).json()['series']==[]
    assert client.get('/api/v2/patients/'+old['id']+'/events/'+eid,headers=HEADERS).status_code==409
    assert client.get('/api/v2/sources/'+source,headers=HEADERS).status_code==409
    patient=client.get('/api/v2/patients/'+old['id'],headers=HEADERS).json()
    assert patient['clinical_reconciliation']['status']=='current_use_restricted' and patient['stats']['observations']==0
    overview=client.get('/api/v2/overview',headers=HEADERS).json()
    assert not any(flag['patient_id']==old['id'] for flag in overview['flagged'])
    with database.session() as s:assert service.event_view(s,s.get(Event,eid))==before
    after=preview(client,id)
    assert any(r['id']==eid for identity in after['identities'] for r in identity['history']['existing_records'])
