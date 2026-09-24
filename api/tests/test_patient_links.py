"""Explicit identity reconciliation without merging owners or overwriting clinic history."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import db, main, transfers
from test_integrity import isolated, act, get, err
from test_transfers import TARGET, HEADERS, request, preview, accept, media


def existing(name='Locally known Luna', species='Cat'):
    patient=act('patient.create', {'name':name,'species':species,'owner_name':'Receiving primary owner','owner_phone':'Local reviewed contact','external_id':'local-'+db.uid()}, **TARGET)
    extra=act('owner.create', {'name':'Receiving additional owner'}, **TARGET)
    patient=act('patient.owners', {'id':patient['id'],'version':patient['version'],'owner_id':patient['data']['owner_id'],'additional_owner_ids':[extra['id']]}, **TARGET)
    local=act('source.add', {'patient_id':patient['id'],'text':'Independent receiving clinical history'}, **TARGET)
    return patient, extra, local


def selected_review(client,r,patient):
    response=client.get('/api/transfers/'+r['id']+'/preview',params={'target_patient_id':patient['id']},headers=HEADERS)
    assert response.status_code==200,response.text
    return response.json()


def payload(client,r,patient,**extra):
    review=selected_review(client,r,patient)
    return {'id':r['id'],'target_patient_id':patient['id'],'expected_digest':review['digest'],
            'link_existing_patient':True,'acknowledge_existing_history':True,
            'patient_match_reason':'Synthetic reviewer checked the patient and all owner details.',**extra}


def target_records():
    with db.connection() as c:return db.all_records(c,'clinic-river')


def test_link_preserves_patient_owners_clinical_history_bytes_stock_and_deduplicates():
    client=TestClient(main.app);f,a,m=media(client);patient,extra,local=existing()
    stock=next(x for x in target_records() if x['kind']=='inventory' and x['data']['unit']=='tablet')
    local_med=act('medication.dispense',{'patient_id':patient['id'],'inventory_id':stock['id'],'version':stock['version'],'quantity':1,'dose':'Recorded locally','frequency':'Recorded locally','instructions':'Synthetic receiving instructions'},**TARGET)
    old_file=client.post('/api/uploads',data={'patient_id':patient['id']},files={'file':('local.txt',b'Original receiving bytes','text/plain')},headers=HEADERS).json()
    base,r=request(client,include_audio=True,include_medications=True)
    before=target_records();review=selected_review(client,r,patient)
    assert review['existing_patient_review_required'] and review['destination_mode']=='existing'
    assert review['baseline_required'] is False and review['baseline'] is None
    assert review['destination_patient']==patient
    assert {x['id'] for x in review['destination_owners']}=={patient['data']['owner_id'],extra['id']}
    assert 'path' not in json.dumps(review) and 'grant_token' not in json.dumps(review)
    assert local['id'] in [x['id'] for x in review['existing_patient_review']['existing_records']]
    out=act('transfer.accept',payload(client,r,patient),**TARGET)
    assert out['id']==patient['id'] and out['patient_link_id'] and not out['baseline_id']
    assert out['files_copied']==out['audio_copied']==out['medication_histories']==1
    after=target_records()
    assert all(get(x['id'])==x for x in before)
    assert len([x for x in after if x['kind']=='patient'])==1
    assert len([x for x in after if x['kind']=='owner'])==2
    assert [x for x in after if x['kind']=='medication']==[local_med]
    assert any(x['id']==local_med['id'] for x in review['existing_patient_review']['existing_records'])
    link=get(out['patient_link_id'])['data']
    assert link['reviewed_by']==TARGET['actor'] and link['reviewed_digest']==review['digest']
    assert link['source_identity']['owner']['name']=='Marcus Lee'
    assert {patient['id'],extra['id'],local['id'],old_file['id']} <= {x['id'] for x in link['preserved_records']}
    assert all(x['fingerprint'] and x['version'] for x in link['preserved_records'])
    originals=[x for x in after if x['data'].get('transfer_patient_link_id')==out['patient_link_id']]
    assert originals and all(x['data']['patient_id']==patient['id'] for x in originals)
    assert all(not x['data'].get('approved') for x in originals if x['kind'] in ('event','attachment','recording'))
    notice=next(x for x in after if x['kind']=='event' and x['data']['title']=='Reviewed existing-patient link')
    assert notice['data']['source_ids'] and not notice['data']['approved'] and 'may duplicate' in notice['data']['body']
    assert client.get('/api/files/'+old_file['id'],headers=HEADERS).content==b'Original receiving bytes'
    act('share.revoke',{'token':base.rsplit('/',1)[-1]})
    copied=next(x for x in originals if x['kind']=='recording')
    assert client.get('/api/recordings/'+copied['id']+'/audio',headers=HEADERS).content==b'original audio startoriginal audio end'
    assert act('transfer.accept',{'id':r['id'],'target_patient_id':patient['id']},**TARGET)==out
    _,again=request(client,include_audio=True,include_medications=True)
    next_review=preview(client,again)
    assert next_review['destination_mode']=='linked' and not next_review['existing_patient_review_required']
    assert next_review['patient_link']['id']==out['patient_link_id']
    repeat=accept(client,again)
    assert repeat['id']==patient['id'] and repeat['counts']['new']==repeat['counts']['changed']==0
    assert target_records()==after


@pytest.mark.parametrize('flag',['link_existing_patient','acknowledge_existing_history'])
@pytest.mark.parametrize('value',[None,False,'true',1])
def test_link_requires_strict_match_and_history_acknowledgements(flag,value):
    client=TestClient(main.app);patient,_,_=existing();_,r=request(client)
    p=payload(client,r,patient,**{flag:value});before=target_records()
    err(409,lambda:act('transfer.accept',p,**TARGET))
    assert target_records()==before
    with db.connection() as c:assert not c.execute('SELECT * FROM transferred_patients').fetchall()


@pytest.mark.parametrize('reason',[None,'','too short',' '*20,'x'*1001,123])
def test_match_reason_is_required(reason):
    client=TestClient(main.app);patient,_,_=existing();_,r=request(client)
    err(422,lambda:act('transfer.accept',payload(client,r,patient,patient_match_reason=reason),**TARGET))


@pytest.mark.parametrize('change',['source_patient','target_patient','primary_owner','additional_owner','owner_links','new_record','old_record','native_record'])
def test_every_reviewed_identity_and_history_change_invalidates_digest(change,monkeypatch):
    client=TestClient(main.app);patient,extra,local=existing();_,r=request(client)
    p=payload(client,r,patient)
    if change=='native_record':
        monkeypatch.setattr('spine.reader.native_records',lambda *a,**k:[{'id':'native-new','kind':'event','version':1,'data':{'patient_id':patient['id'],'title':'New native fact'}}])
    else:
        with db.connection(True) as c:
            if change=='new_record':db.event(c,'clinic-river',patient['id'],'clinical','New local fact','Reviewed after preview')
            else:
                rid={'source_patient':'luna','target_patient':patient['id'],'primary_owner':patient['data']['owner_id'],'additional_owner':extra['id'],'owner_links':patient['id'],'old_record':local['id']}[change]
                row=db.get(c,rid)
                changed={**row['data'],**({'additional_owner_ids':[]} if change=='owner_links' else {'name':'Updated after preview'})}
                db.update(c,row,changed)
    err(409,lambda:act('transfer.accept',p,**TARGET))
    with db.connection() as c:
        assert not c.execute('SELECT * FROM transferred_patients').fetchall()
        assert not db.all_records(c,'clinic-river','transfer_patient_link')


def test_preview_does_not_write_and_unrelated_patients_do_not_invalidate_it():
    client=TestClient(main.app);patient,_,_=existing();other,_,local=existing('Other receiving patient')
    _,r=request(client);before=target_records();p=payload(client,r,patient)
    assert target_records()==before
    with db.connection(True) as c:db.update(c,local,{**local['data'],'text':'Unrelated update'})
    assert act('transfer.accept',p,**TARGET)['id']==patient['id']


def test_never_matches_names_automatically_or_accepts_an_unselected_digest():
    client=TestClient(main.app);patient,_,_=existing('Luna');_,r=request(client)
    new=preview(client,r)
    assert new['destination_mode']=='new' and new['destination_patient'] is None
    p=payload(client,r,patient,expected_digest=new['digest'])
    err(409,lambda:act('transfer.accept',p,**TARGET))
    err(409,lambda:act('transfer.accept',{**p,'target_patient_id':None},**TARGET))
    result=accept(client,r)
    assert result['id']!=patient['id'] and get(patient['id'])==patient


def test_species_mismatch_and_a_different_existing_origin_are_blocked():
    client=TestClient(main.app);patient,_,_=existing(species='Dog');_,r=request(client)
    assert client.get('/api/transfers/'+r['id']+'/preview',params={'target_patient_id':patient['id']},headers=HEADERS).status_code==409
    with db.connection(True) as c:
        db.update(c,patient,{**patient['data'],'species':'Cat'})
        c.execute('INSERT INTO transferred_patients VALUES(?,?,?,?)',('clinic-east','milo','clinic-river',patient['id']))
    assert client.get('/api/transfers/'+r['id']+'/preview',params={'target_patient_id':patient['id']},headers=HEADERS).status_code==409


def test_selection_is_bound_to_clinic_kind_permissions_and_request_consent():
    client=TestClient(main.app);patient,_,local=existing();base,r=request(client)
    route='/api/transfers/'+r['id']+'/preview'
    for target in ('luna',local['id'],'missing'):
        assert client.get(route,params={'target_patient_id':target},headers=HEADERS).status_code==404
    assert client.get(route,params={'target_patient_id':patient['id']},headers={**HEADERS,'x-actor-id':'clinic-river-nurse'}).status_code==403
    p=payload(client,r,patient)
    for value in ([],{},1,'','x'*201):
        err(422,lambda:act('transfer.accept',{**p,'target_patient_id':value},**TARGET))
    act('share.revoke',{'token':base.rsplit('/',1)[-1]})
    err(404,lambda:act('transfer.accept',p,**TARGET))


def test_established_links_and_accepted_requests_cannot_be_retargeted():
    client=TestClient(main.app);patient,_,_=existing();other,_,_=existing('Another cat');_,r=request(client)
    result=act('transfer.accept',payload(client,r,patient),**TARGET)
    err(409,lambda:act('transfer.accept',{'id':r['id'],'target_patient_id':other['id']},**TARGET))
    _,again=request(client)
    assert client.get('/api/transfers/'+again['id']+'/preview',params={'target_patient_id':other['id']},headers=HEADERS).status_code==409
    assert preview(client,again)['destination_patient']['id']==result['id']


def test_concurrent_choices_cannot_link_one_origin_to_two_patients():
    client=TestClient(main.app);one,_,_=existing();two,_,_=existing('Another cat');_,a=request(client);_,b=request(client)
    proposals=[payload(client,a,one),payload(client,b,two)];barrier=threading.Barrier(2)
    def attempt(p):
        barrier.wait()
        try:return act('transfer.accept',p,**TARGET)
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,proposals))
    assert sum(isinstance(x,dict) for x in results)==1 and 409 in results
    with db.connection() as c:
        assert len(c.execute('SELECT * FROM transferred_patients').fetchall())==1
        assert len(db.all_records(c,'clinic-river','transfer_patient_link'))==1


def test_failed_copy_rolls_back_mapping_receipt_records_and_new_files():
    client=TestClient(main.app);media(client);patient,_,_=existing();_,r=request(client,include_audio=True)
    p=payload(client,r,patient);before=target_records();files={x for x in db.DATA.rglob('*') if x.is_file()}
    from db_faults import reject_transfer_audit
    with db.connection(True) as c:reject_transfer_audit(c,'link_failure','link injected failure')
    with pytest.raises(Exception,match='link injected failure'):act('transfer.accept',p,**TARGET)
    assert target_records()==before
    assert {x for x in db.DATA.rglob('*') if x.is_file()}==files
    with db.connection() as c:
        assert not c.execute('SELECT * FROM transferred_patients').fetchall()
        assert not c.execute('SELECT * FROM transfer_revisions').fetchall()
        assert c.execute('SELECT status FROM transfer_requests WHERE id=?',(r['id'],)).fetchone()[0]=='pending'


def test_link_review_has_the_receiving_history_bound(monkeypatch):
    client=TestClient(main.app);patient,_,_=existing();_,r=request(client)
    with db.connection(True) as c:
        for i in range(5):db.record(c,'source','clinic-river',{'patient_id':patient['id'],'text':'Reviewed local '+str(i)})
    monkeypatch.setattr(transfers,'MAX_ITEMS',4)
    assert client.get('/api/transfers/'+r['id']+'/preview',params={'target_patient_id':patient['id']},headers=HEADERS).status_code==422
