"""Explicitly consented mapping correction preserves both patients and origin history."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import db, main, transfers
from test_integrity import isolated, act, get, err
from test_transfers import TARGET, HEADERS, request, preview, accept, media
from test_patient_links import existing, target_records


def setup(client, **scope):
    _, initial = request(client, **scope)
    old = get(accept(client, initial)['id'])
    target, owner, history = existing('SYNTHETIC corrected Luna')
    base, pending = request(client, allow_mapping_correction=True, **scope)
    return old, target, owner, history, base, pending


def review(client, pending, target):
    response = client.get('/api/transfers/'+pending['id']+'/preview',
                          params={'target_patient_id':target['id'], 'correct_mapping':'true'}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def payload(client, pending, target, **extra):
    current = review(client, pending, target)
    return {'id':pending['id'], 'target_patient_id':target['id'], 'correct_mapping':True,
            'previous_patient_id':current['mapping_correction']['previous_patient']['id'],
            'expected_digest':current['digest'], 'confirm_corrected_identity':True,
            'acknowledge_unresolved_history':True, 'correction_reason':'Synthetic identity evidence checked; earlier copies need separate clinical review.', **extra}


def mapping():
    with db.connection() as c:
        return c.execute('SELECT target_patient FROM transferred_patients').fetchone()[0]


def test_correction_preserves_every_old_record_and_binary_receipts_and_deduplicates_future_transfers():
    client=TestClient(main.app);media(client)
    old,target,owner,history,base,pending=setup(client,include_audio=True,include_medications=True)
    before=target_records()
    files={str(p):p.read_bytes() for p in db.DATA.rglob('*') if p.is_file() and ('files' in p.parts or 'audio' in p.parts)}
    with db.connection() as c: revisions=[dict(row) for row in c.execute('SELECT * FROM transfer_revisions ORDER BY kind,origin_id,revision')]
    proposal=payload(client,pending,target);current=review(client,pending,target)
    assert current['destination_mode']=='correction' and current['mapping_correction_required']
    assert current['counts']['new']==len(current['items']) and not current['counts']['unchanged']
    assert 'path' not in json.dumps(current) and 'grant_token' not in json.dumps(current)
    assert {x['data']['patient_id'] for x in current['mapping_correction']['previous_history']['existing_records']}=={old['id']}
    out=act('transfer.accept',proposal,**TARGET)
    assert out['id']==mapping()==target['id'] and out['reconciliation_status']=='unresolved'
    assert out['files_copied']==out['audio_copied']==out['medication_histories']==1
    assert all(get(record['id'])==record for record in before)
    assert all(Path(path).read_bytes()==content for path,content in files.items())
    after=target_records();receipt=get(out['mapping_correction_id'])
    assert receipt['version']==1 and receipt['data']['previous_patient_id']==old['id']
    assert receipt['data']['reviewed_by']==TARGET['actor'] and receipt['data']['reviewed_digest']==current['digest']
    assert receipt['data']['owner_consent_scope']['mapping_correction'] is True
    assert receipt['data']['clinical_equivalence_asserted'] is False and receipt['data']['reconciliation_status']=='unresolved'
    assert {old['id'],target['id'],owner['id'],history['id']} <= {x['id'] for x in receipt['data']['preserved_records']}
    notices=[x for x in after if x['kind']=='event' and x['data'].get('reconciliation_status')=='unresolved']
    assert {x['data']['patient_id'] for x in notices}=={old['id'],target['id']}
    assert all(not x['data']['approved'] and x['data']['source_ids'] for x in notices)
    assert all('must not be assumed to belong' in x['data']['body'] for x in notices)
    with db.connection() as c:
        current_revisions=[dict(row) for row in c.execute('SELECT * FROM transfer_revisions ORDER BY kind,origin_id,revision')]
    assert all(row in current_revisions for row in revisions) and len(current_revisions)==len(revisions)*2
    assert act('transfer.accept',proposal,**TARGET)==out
    _,again=request(client,include_audio=True,include_medications=True)
    next_review=preview(client,again)
    assert next_review['counts']['new']==next_review['counts']['changed']==0
    assert next_review['latest_mapping_correction']['id']==receipt['id']
    assert accept(client,again)['id']==target['id']
    assert get(receipt['id'])==receipt and target_records()==after
    act('share.revoke',{'token':base.rsplit('/',1)[-1]})
    for copied in [x for x in after if x['kind']=='attachment']:
        assert client.get('/api/files/'+copied['id'],headers=HEADERS).content==b'Approved file content'


@pytest.mark.parametrize('flag',['confirm_corrected_identity','acknowledge_unresolved_history'])
@pytest.mark.parametrize('value',[None,False,'true',1])
def test_correction_requires_strict_acknowledgements(flag,value):
    client=TestClient(main.app);old,target,_,_,_,pending=setup(client)
    p=payload(client,pending,target,**{flag:value});before=target_records()
    err(409,lambda:act('transfer.accept',p,**TARGET))
    assert mapping()==old['id'] and target_records()==before


@pytest.mark.parametrize('value',[None,'','short',' '*20,'x'*1001,123])
def test_correction_requires_a_review_reason(value):
    client=TestClient(main.app);_,target,_,_,_,pending=setup(client)
    err(422,lambda:act('transfer.accept',payload(client,pending,target,correction_reason=value),**TARGET))


def test_correction_needs_new_explicit_owner_scope_that_cannot_expand_while_pending():
    client=TestClient(main.app);_,initial=request(client);old=get(accept(client,initial)['id']);target,_,_=existing()
    base,pending=request(client)
    route='/api/transfers/'+pending['id']+'/preview'
    assert client.get(route,params={'target_patient_id':target['id'],'correct_mapping':'true'},headers=HEADERS).status_code==409
    err(409,lambda:act('transfer.accept',{'id':pending['id'],'target_patient_id':target['id'],'correct_mapping':True},**TARGET))
    assert client.post(base+'/transfers',json={'target_clinic':'clinic-river','consent':True,'allow_mapping_correction':True}).status_code==409
    assert client.post(base+'/transfers',json={'target_clinic':'clinic-river','consent':True,'allow_mapping_correction':'true'}).status_code==422
    assert client.delete(base+'/transfers/'+pending['id']).status_code==200
    replacement=client.post(base+'/transfers',json={'target_clinic':'clinic-river','consent':True,'allow_mapping_correction':True}).json()
    assert replacement['id']!=pending['id'] and replacement['scope']['mapping_correction'] is True
    assert act('transfer.accept',payload(client,replacement,target),**TARGET)['id']==target['id']


@pytest.mark.parametrize('change',['source','old_patient','old_owner','old_history','target_patient','target_owner','target_history','native_old','native_target','mapping'])
def test_both_reviewed_identities_and_histories_are_stale_guarded(change,monkeypatch):
    client=TestClient(main.app);old,target,owner,history,_,pending=setup(client)
    p=payload(client,pending,target)
    if change.startswith('native_'):
        patient=old if change=='native_old' else target
        monkeypatch.setattr('spine.reader.native_records',lambda clinic,id: [{'id':'native-changed','kind':'event','version':1,'data':{'patient_id':id,'title':'New native clinical fact'}}] if id==patient['id'] else [])
    else:
        with db.connection(True) as c:
            if change=='mapping':
                c.execute('UPDATE transferred_patients SET target_patient=?',(target['id'],))
            elif change=='old_history':db.event(c,'clinic-river',old['id'],'clinical','New old-patient fact','Arrived after review')
            else:
                rid={'source':'luna','old_patient':old['id'],'old_owner':old['data']['owner_id'],'target_patient':target['id'],'target_owner':owner['id'],'target_history':history['id']}[change]
                row=db.get(c,rid);db.update(c,row,{**row['data'],'name':'Changed after preview'})
    err(409,lambda:act('transfer.accept',p,**TARGET))
    with db.connection() as c:assert not db.all_records(c,'clinic-river','transfer_mapping_correction')


def test_correction_is_bounded_to_valid_different_patient_and_role():
    client=TestClient(main.app);old,target,_,history,base,pending=setup(client)
    route='/api/transfers/'+pending['id']+'/preview'
    for id,status in [(old['id'],409),('missing',404),('luna',404),(history['id'],404)]:
        assert client.get(route,params={'target_patient_id':id,'correct_mapping':'true'},headers=HEADERS).status_code==status
    assert client.get(route,params={'correct_mapping':'true'},headers=HEADERS).status_code==409
    p=payload(client,pending,target)
    err(403,lambda:act('transfer.accept',p,clinic='clinic-river',actor='clinic-river-nurse'))
    err(409,lambda:act('transfer.accept',{**p,'previous_patient_id':'other'},**TARGET))
    for value in ('true',1,None):err(422,lambda:act('transfer.accept',{**p,'correct_mapping':value},**TARGET))
    act('share.revoke',{'token':base.rsplit('/',1)[-1]})
    err(404,lambda:act('transfer.accept',p,**TARGET))


def test_conflicting_origin_and_species_are_blocked():
    client=TestClient(main.app);_,target,_,_,_,pending=setup(client)
    with db.connection(True) as c:db.update(c,target,{**target['data'],'species':'Dog'})
    route='/api/transfers/'+pending['id']+'/preview';params={'target_patient_id':target['id'],'correct_mapping':'true'}
    assert client.get(route,params=params,headers=HEADERS).status_code==409
    with db.connection(True) as c:
        row=db.get(c,target['id']);db.update(c,row,{**row['data'],'species':'Cat'})
        c.execute('INSERT INTO transferred_patients VALUES(?,?,?,?)',('clinic-east','milo','clinic-river',target['id']))
    assert client.get(route,params=params,headers=HEADERS).status_code==409


def test_competing_corrections_have_one_winner_and_stale_digest_cannot_retarget():
    client=TestClient(main.app);_,target,_,_,_,one=setup(client);other,_,_=existing('Another receiving cat')
    _,two=request(client,allow_mapping_correction=True)
    proposals=[payload(client,one,target),payload(client,two,other)];barrier=threading.Barrier(2)
    def attempt(p):
        barrier.wait()
        try:return act('transfer.accept',p,**TARGET)
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,proposals))
    assert sum(isinstance(x,dict) for x in results)==1 and 409 in results
    with db.connection() as c:assert len(db.all_records(c,'clinic-river','transfer_mapping_correction'))==1


def test_failed_copy_rolls_back_mapping_receipt_history_revisions_and_media():
    client=TestClient(main.app);media(client);old,target,_,_,_,pending=setup(client,include_audio=True)
    p=payload(client,pending,target);before=target_records();files={x for x in db.DATA.rglob('*') if x.is_file()}
    with db.connection() as c:revisions=[dict(x) for x in c.execute('SELECT * FROM transfer_revisions')]
    from db_faults import reject_transfer_audit
    with db.connection(True) as c:reject_transfer_audit(c,'correction_failure','correction injected failure')
    with pytest.raises(Exception,match='correction injected failure'):act('transfer.accept',p,**TARGET)
    assert target_records()==before and mapping()==old['id']
    assert {x for x in db.DATA.rglob('*') if x.is_file()}==files
    with db.connection() as c:
        assert [dict(x) for x in c.execute('SELECT * FROM transfer_revisions')]==revisions
        assert c.execute('SELECT status FROM transfer_requests WHERE id=?',(pending['id'],)).fetchone()[0]=='pending'


def test_return_to_previously_used_destination_preserves_origin_sequence_and_skips_its_copies():
    client=TestClient(main.app);old,target,_,_,_,pending=setup(client)
    first=act('transfer.accept',payload(client,pending,target),**TARGET)
    _,back=request(client,allow_mapping_correction=True)
    back_preview=review(client,back,old)
    assert back_preview['counts']['unchanged']==len(back_preview['items'])
    out=act('transfer.accept',payload(client,back,old),**TARGET)
    assert mapping()==old['id'] and out['mapping_correction_id']!=first['mapping_correction_id']
    _,again=request(client)
    assert preview(client,again)['counts']['unchanged']==len(back_preview['items'])


def test_unknown_legacy_revisions_are_not_reconstructed_during_correction():
    client=TestClient(main.app);_,target,_,_,_,pending=setup(client)
    with db.connection(True) as c:c.execute('DELETE FROM transfer_revisions')
    current=review(client,pending,target)
    assert not current['baseline_required'] and current['counts']['new']==len(current['items'])
    result=act('transfer.accept',payload(client,pending,target),**TARGET)
    assert get(result['mapping_correction_id'])['data']['clinical_equivalence_asserted'] is False


def test_changed_origin_after_correction_appends_only_to_current_patient():
    client=TestClient(main.app);old,target,_,_,_,pending=setup(client)
    act('transfer.accept',payload(client,pending,target),**TARGET)
    preserved_old=[x for x in target_records() if x['data'].get('patient_id')==old['id']]
    with db.connection(True) as c:
        original=next(x for x in db.all_records(c,'clinic-east','event') if x['data'].get('patient_id')=='luna' and x['data'].get('approved'))
        db.update(c,original,{**original['data'],'body':'Source veterinarian corrected this synthetic finding.'})
    _,again=request(client);current=preview(client,again)
    changed=next(x for x in current['items'] if x['origin_id']==original['id'])
    assert changed['state']=='changed' and changed['revision']==3
    assert changed['destination_copy']['data']['patient_id']==target['id']
    err(409,lambda:accept(client,again))
    assert accept(client,again,review_changes=True)['counts']['changed']==1
    assert all(get(x['id'])==x for x in preserved_old)


def test_old_mapping_preview_cannot_import_after_correction():
    client=TestClient(main.app);_,target,_,_,_,pending=setup(client)
    _,ordinary=request(client);outdated=preview(client,ordinary)
    act('transfer.accept',payload(client,pending,target),**TARGET)
    err(409,lambda:act('transfer.accept',{'id':ordinary['id'],'expected_digest':outdated['digest']},**TARGET))
    assert preview(client,ordinary)['destination_patient']['id']==target['id']


def test_combined_correction_history_is_bounded_and_preview_does_not_write(monkeypatch):
    client=TestClient(main.app);_,target,_,_,_,pending=setup(client)
    before=target_records();current=review(client,pending,target)
    assert target_records()==before
    context=current['mapping_correction']
    total=len(context['previous_history']['existing_records'])+len(context['receiving_history']['existing_records'])
    monkeypatch.setattr(transfers,'MAX_ITEMS',total-1)
    response=client.get('/api/transfers/'+pending['id']+'/preview',params={'target_patient_id':target['id'],'correct_mapping':'true'},headers=HEADERS)
    assert response.status_code==422 and target_records()==before
