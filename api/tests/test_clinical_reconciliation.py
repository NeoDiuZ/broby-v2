"""Synthetic current-use exclusions with preserved immutable origin evidence."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import db, main, clinical_reconciliation as reconciliation
from test_integrity import isolated, act, get, err
from test_transfers import TARGET, HEADERS, media
from test_transfer_corrections import setup, payload

@pytest.fixture(autouse=True)
def sqlite_native(monkeypatch):
    monkeypatch.setattr('spine.reconciliation.native_dependents',lambda *a,**k:{})


def fixture():
    client=TestClient(main.app);media(client)
    old,new,_,_,_,pending=setup(client,include_audio=True,include_medications=True)
    result=act('transfer.accept',payload(client,pending,new),**TARGET)
    return client,old,new,result['mapping_correction_id']


def preview(client,id):
    response=client.get('/api/clinical-reconciliation/'+id,headers=HEADERS)
    assert response.status_code==200,response.text
    return response.json()


def decision(review,patient_id,kind='file',status='wrong_patient'):
    group=next(g for g in review['groups'] if g['patient_id']==patient_id and g['origin']['kind']==kind)
    reason='SYNTHETIC explicit clinician identity evidence reviewed.'
    return {'correction_id':review['correction']['id'],'expected_digest':review['digest'],'confirm_review':True,'acknowledge_patient_hold':True,
            'decisions':[{'group_key':group['group_key'],'disposition':status,'reason':reason,
                          'record_decisions':[{'id':r['id'],'disposition':status,'reason':reason+' Record '+r['id']} for r in group['records']]}]}


def test_per_record_review_preserves_originals_and_holds_ambiguous_patient_history():
    client,old,new,id=fixture();current=preview(client,id)
    with db.connection() as c:before=db.all_records(c,'clinic-river')
    binaries={str(p):p.read_bytes() for p in db.DATA.rglob('*') if p.is_file() and ('files' in p.parts or 'audio' in p.parts)}
    request=decision(current,old['id']);receipt=act('clinical.reconcile',request,**TARGET)
    assert receipt['data']['clinical_equivalence_asserted'] is False
    assert all(get(row['id'])==row for row in before)
    assert all(Path(path).read_bytes()==value for path,value in binaries.items())
    with db.connection() as c:
        state=reconciliation.eligibility(c,'clinic-river')
        assert old['id'] in state['patients'] and new['id'] not in state['patients']
        clinical=[r for r in before if r['data'].get('patient_id')==old['id'] and r['kind'] in reconciliation.KINDS]
        assert all(r['id'] in state['excluded'] for r in clinical)
    visible=client.get('/api/bootstrap',headers=HEADERS).json()
    assert not {r['id'] for r in clinical}&{r['id'] for r in visible['records']}
    assert next(r for r in visible['records'] if r['id']==old['id'])['data']['clinical_reconciliation']['status']=='current_use_restricted'
    assert client.get('/api/patients/'+old['id']+'/timeline',headers=HEADERS).json()['items']==[]
    assert client.get('/api/patients/'+old['id']+'/observations',headers=HEADERS).json()==[]


@pytest.mark.parametrize('change',['missing_record','mixed_disposition','missing_reason','missing_hold_ack','stale_source','stale_owner'])
def test_review_requires_every_record_reason_and_fresh_complete_history(change):
    client,old,new,id=fixture();review=preview(client,id);p=decision(review,old['id'])
    record=p['decisions'][0]['record_decisions'][0]
    if change=='missing_record':p['decisions'][0]['record_decisions'].pop()
    elif change=='mixed_disposition':record['disposition']='retain'
    elif change=='missing_reason':record['reason']=''
    elif change=='missing_hold_ack':p['acknowledge_patient_hold']=False
    else:
        rid=old['data']['owner_id'] if change=='stale_owner' else record['id']
        with db.connection(True) as c:
            row=db.get(c,rid);db.update(c,row,{**row['data'],'name':'Synthetic concurrent correction'})
    err(422 if change=='missing_reason' else 409,lambda:act('clinical.reconcile',p,**TARGET))
    with db.connection() as c:assert not db.all_records(c,'clinic-river','clinical_reconciliation_review')


def test_owner_direct_media_and_pdf_are_held_but_forensic_original_remains():
    client,old,new,id=fixture()
    with db.connection() as c:rows=db.all_records(c,'clinic-river')
    media_rows=[r for r in rows if r['data'].get('patient_id')==old['id'] and r['kind'] in ('attachment','recording')]
    for row in media_rows:act(row['kind']+'.approve',{'id':row['id'],'version':row['version'],'approved':True},**TARGET)
    grant=act('share.create',{'patient_id':old['id']},**TARGET)
    base='/api/owner/'+grant['id']
    wrong_owner='/api/owner/'+act('share.create',{'patient_id':new['id']},**TARGET)['id']
    assert client.get(base).json()['files'] and client.get(base).json()['audio']
    review=preview(client,id);act('clinical.reconcile',decision(review,old['id']),**TARGET)
    owner=client.get(base).json();assert not owner['files'] and not owner['audio'] and owner['clinical_review_notice']
    assert client.get(base+'/discharge.pdf').status_code==409
    for row in media_rows:
        path='/files/' if row['kind']=='attachment' else '/audio/'
        assert client.get(base+path+row['id']).status_code==409
        assert client.get(wrong_owner+path+row['id']).status_code==404
        direct='/api/files/'+row['id'] if row['kind']=='attachment' else '/api/recordings/'+row['id']+'/audio'
        assert client.get(direct,headers=HEADERS).status_code==409
        historical=client.get('/api/clinical-reconciliation/'+id+'/media/'+row['id']+'?acknowledge_historical=true',headers=HEADERS)
        assert historical.status_code==200 and historical.headers['x-broby-clinical-status']=='historical-unverified'
    export=client.get('/api/export',headers={**HEADERS,'x-actor-id':'clinic-river-admin'}).json()
    assert export['purpose']=='forensic_archive' and export['current_clinical_use'] is False
    assert {r['id'] for r in media_rows}<={r['id'] for r in export['records']}
    assert all(r['id'] in export['clinical_reconciliation']['excluded'] for r in media_rows)


def test_saved_assistant_results_and_confirmation_require_refreshed_review():
    client,old,new,id=fixture()
    response=client.post('/api/assistant',headers=HEADERS,json={'message':'start consultation','patient_id':old['id'],'key':'before-reconciliation'});assert response.status_code==200,response.text
    saved=response.json();assert saved.get('action')
    review=preview(client,id);act('clinical.reconcile',decision(review,old['id']),**TARGET)
    shown=client.get('/api/assistant/conversations/'+saved['conversation_id'],headers=HEADERS).json()['turns'][0]
    assert shown['clinical_reconciliation']['status']=='historical_unverified' and not shown.get('action') and not shown['sources']
    retry=client.post('/api/assistant',headers=HEADERS,json={'message':'start consultation','patient_id':old['id'],'key':'before-reconciliation'}).json()
    assert retry['clinical_reconciliation']['status']=='historical_unverified'
    assert client.post('/api/assistant/conversations/'+saved['conversation_id']+'/turns/'+saved['turn_id']+'/confirm',headers=HEADERS).status_code==409
    assert client.post('/api/assistant',headers=HEADERS,json={'message':'history','patient_id':old['id']}).status_code==409
    with db.connection() as c:
        original=json.loads(c.execute('SELECT response FROM assistant_turns WHERE id=?',(saved['turn_id'],)).fetchone()[0])
        assert original['action']==saved['action']


def test_queued_job_cannot_publish_from_held_patient(monkeypatch):
    import jobs
    client,old,new,id=fixture()
    consultation=act('consultation.create',{'patient_id':old['id']},**TARGET)
    act('source.add',{'patient_id':old['id'],'consultation_id':consultation['id'],'text':'Untraceable synthetic copied text'},**TARGET)
    consult=get(consultation['id']);job=act('summary.generate',{'id':consult['id'],'version':consult['version']},**TARGET)
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    err(409,lambda:jobs.run_job(job['id']))
    assert get(consult['id'])==consult
    result=client.get('/api/jobs/'+job['id'],headers=HEADERS).json();assert result['status']=='failed' and result['result'] is None and result['clinical_reconciliation']


def test_retained_group_never_infers_equivalence_and_edit_reopens_hold():
    client,old,new,id=fixture();review=preview(client,id);p=decision(review,new['id'],status='retain')
    receipt=act('clinical.reconcile',p,**TARGET)
    with db.connection() as c:assert not reconciliation.eligibility(c,'clinic-river')['patients']
    changed=p['decisions'][0]['record_decisions'][0]['id']
    with db.connection(True) as c:
        row=db.get(c,changed);db.update(c,row,{**row['data'],'title':'Changed after explicit review'})
    with db.connection() as c:
        state=reconciliation.eligibility(c,'clinic-river');assert new['id'] in state['patients'] and state['excluded'][changed]['status']=='review_changed'
    assert get(receipt['id'])==receipt


def test_accepted_onward_copy_is_preserved_but_current_use_is_qualified():
    client,old,new,id=fixture()
    with db.connection() as c:
        file=next(r for r in db.all_records(c,'clinic-river','attachment') if r['data']['patient_id']==old['id'])
    act('attachment.approve',{'id':file['id'],'version':file['version'],'approved':True},**TARGET)
    grant=act('share.create',{'patient_id':old['id']},**TARGET)
    request=client.post('/api/owner/'+grant['id']+'/transfers',json={'target_clinic':'clinic-east','consent':True}).json()
    onward_review=client.get('/api/transfers/'+request['id']+'/preview').json()
    onward=act('transfer.accept',{'id':request['id'],'expected_digest':onward_review['digest']})
    with db.connection() as c:
        originals=[r for r in db.all_records(c,'clinic-east') if r['data'].get('patient_id')==onward['id']]
    review=preview(client,id)
    assert any(copy['target_patient_id']==onward['id'] and copy['origin_id']==file['id'] for copy in review['known_onward_copies'])
    receipt=act('clinical.reconcile',decision(review,old['id']),**TARGET)
    assert all(get(row['id'])==row for row in originals)
    with db.connection() as c:
        state=reconciliation.eligibility(c,'clinic-east')
        assert onward['id'] in state['patients']
        assert any(value['status']=='source_dispute' for value in state['excluded'].values())
    assert receipt['data']['known_onward_copies'] and all(copy['status']=='separate_receiving_clinic_review_required_if_source_patient_held' for copy in receipt['data']['known_onward_copies'])


def test_reconciliation_does_not_invalidate_unrelated_patient_or_other_clinic_jobs_and_answers():
    import jobs
    client,old,new,id=fixture()
    same=act('consultation.create',{'patient_id':new['id']},**TARGET)
    act('source.add',{'patient_id':new['id'],'consultation_id':same['id'],'text':'SYNTHETIC unaffected corrected patient fact'},**TARGET)
    same=get(same['id']);same_job=act('summary.generate',{'id':same['id'],'version':same['version']},**TARGET)
    other=act('consultation.create',{'patient_id':'milo'})
    act('source.add',{'patient_id':'milo','consultation_id':other['id'],'text':'SYNTHETIC unaffected other-clinic fact'})
    other=get(other['id']);other_job=act('summary.generate',{'id':other['id'],'version':other['version']})
    same_answer=client.post('/api/assistant',headers=HEADERS,json={'message':'history','patient_id':new['id'],'key':'unrelated-patient-answer'}).json()
    other_answer=client.post('/api/assistant',json={'message':'history','patient_id':'milo','key':'unrelated-clinic-answer'}).json()
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    with db.connection() as c:
        local=reconciliation.eligibility(c,'clinic-river');foreign=reconciliation.eligibility(c,'clinic-east')
        assert reconciliation.scope_epoch(local,new['id'])==reconciliation.fingerprint([])
        assert foreign['epoch']==reconciliation.fingerprint([]) and not foreign['patients']
    for row,headers in ((same_job,HEADERS),(other_job,{})):
        jobs.run_job(row['id']);shown=client.get('/api/jobs/'+row['id'],headers=headers).json()
        assert shown['status']=='completed' and shown['result']['summary'] and not shown.get('clinical_reconciliation')
    for answer,headers in ((same_answer,HEADERS),(other_answer,{})):
        shown=client.get('/api/assistant/conversations/'+answer['conversation_id'],headers=headers).json()['turns'][0]
        assert shown['text']==answer['text'] and shown['sources']==answer['sources'] and not shown.get('clinical_reconciliation')


def test_saved_owner_reply_and_old_cards_are_withheld_during_hold(monkeypatch):
    import owner_conversations as chat
    client,old,new,id=fixture();monkeypatch.setattr(chat,'topic',lambda message:('staff','rules'))
    grant=act('share.create',{'patient_id':old['id']},**TARGET)
    answer=chat.send(grant['id'],chat.Message(message='SYNTHETIC care question',key='before-hold-question'))
    thread=get(answer['id'])
    reply='SYNTHETIC older staff instruction with untraceable source lineage'
    act('conversation.reply',{'id':thread['id'],'version':thread['version'],'last_owner_turn':thread['data']['last_owner_turn'],'message':reply},**TARGET)
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    output=client.get('/api/owner/'+grant['id']+'/conversations/'+thread['id']).json()
    assert reply not in json.dumps(output) and all(t['historical_unverified'] and not t['cards'] for t in output['turns'])
    staff=client.get('/api/owner-conversations/'+thread['id'],headers=HEADERS).json()
    assert reply in json.dumps(staff['turns']) and staff['clinical_reconciliation']['status']=='historical_unverified'
    monkeypatch.setattr(chat,'topic',lambda *_:pytest.fail('Held patient must not call an AI provider'))
    assert chat.send(grant['id'],chat.Message(message='SYNTHETIC follow-up for clinic review',thread_id=thread['id'],key='after-hold-question'))['turns']


def test_provider_result_is_rejected_if_identity_changes_during_generation(monkeypatch):
    import jobs,providers
    client,old,new,id=fixture()
    consult=act('consultation.create',{'patient_id':old['id']},**TARGET)
    source=act('source.add',{'patient_id':old['id'],'consultation_id':consult['id'],'text':'SYNTHETIC provider input'},**TARGET)
    consult=get(consult['id']);monkeypatch.setattr(providers,'available',lambda:{'ai':True})
    job=act('summary.generate',{'id':consult['id'],'version':consult['version'],'mode':'ai'},**TARGET)
    p=decision(preview(client,id),old['id'])
    def complete(*args):
        act('clinical.reconcile',p,**TARGET)
        return [{'name':'Objective','text':'SYNTHETIC should never publish','source_ids':[source['id']]}],[]
    monkeypatch.setattr(providers,'assemble',complete)
    err(409,lambda:jobs.run_job(job['id']))
    assert get(consult['id'])==consult
    shown=client.get('/api/jobs/'+job['id'],headers=HEADERS).json()
    assert shown['status']=='failed' and shown['result'] is None


def test_old_approval_replay_and_new_outward_transfer_fail_closed_after_hold():
    client,old,new,id=fixture()
    with db.connection() as c:file=next(row for row in db.all_records(c,'clinic-river','attachment') if row['data']['patient_id']==old['id'])
    p={'id':file['id'],'version':file['version'],'approved':True}
    act('attachment.approve',p,key='prior-approved-file',**TARGET)
    grant=act('share.create',{'patient_id':old['id']},**TARGET)
    pending=client.post('/api/owner/'+grant['id']+'/transfers',json={'target_clinic':'clinic-east','consent':True}).json()
    review=client.get('/api/transfers/'+pending['id']+'/preview').json()
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    err(409,lambda:act('attachment.approve',p,key='prior-approved-file',**TARGET))
    assert client.get('/api/transfers/'+pending['id']+'/preview').status_code==409
    err(409,lambda:act('transfer.accept',{'id':pending['id'],'expected_digest':review['digest']}))
    assert client.post('/api/owner/'+grant['id']+'/transfers',json={'target_clinic':'clinic-east','consent':True}).status_code==409


def test_plain_text_clipboard_export_and_historical_revisions_are_qualified():
    client,old,new,id=fixture()
    consult=act('consultation.create',{'patient_id':old['id']},**TARGET)
    consult=act('summary.save',{'id':consult['id'],'version':consult['version'],'summary':[{'name':'Plan','text':'SYNTHETIC untraceable derived instruction','source_ids':[]}]},**TARGET)
    base='/api/consultations/'+consult['id']
    exported=client.get(base+'/text?version='+str(consult['version']),headers=HEADERS)
    assert exported.status_code==200 and exported.json()['text']=='Plan\nSYNTHETIC untraceable derived instruction'
    assert client.get(base+'/text?version=999',headers=HEADERS).status_code==409
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    assert client.get(base+'/text?version='+str(consult['version']),headers=HEADERS).status_code==409
    assert client.get(base+'/pdf',headers=HEADERS).status_code==409
    historical=client.get('/api/records/'+consult['id']+'/history',headers=HEADERS).json()
    assert historical['current_clinical_use'] is False and historical['current']==consult and historical['clinical_reconciliation']
    history=client.get('/api/clinical-reconciliation/patients/'+old['id']+'/history',headers=HEADERS).json()
    assert history['current_clinical_use'] is False and consult in history['records']


def test_original_binary_change_invalidates_preview_and_retained_disposition():
    client,old,new,id=fixture();review=preview(client,id);p=decision(review,new['id'],status='retain')
    file_id=next(item['id'] for item in p['decisions'][0]['record_decisions'] if get(item['id'])['kind']=='attachment')
    path=Path(get(file_id)['data']['path']);original=path.read_bytes();path.write_bytes(b'SYNTHETIC changed bytes before confirmation')
    err(409,lambda:act('clinical.reconcile',p,**TARGET))
    changed=decision(preview(client,id),new['id'],status='retain');err(409,lambda:act('clinical.reconcile',changed,**TARGET))
    path.write_bytes(original);receipt=act('clinical.reconcile',decision(preview(client,id),new['id'],status='retain'),**TARGET)
    with db.connection() as c:assert new['id'] not in reconciliation.eligibility(c,'clinic-river')['patients']
    path.write_bytes(b'SYNTHETIC changed after retained review')
    with db.connection() as c:assert new['id'] in reconciliation.eligibility(c,'clinic-river')['patients']
    assert get(receipt['id'])==receipt


def test_recall_delivery_campaigns_and_handover_do_not_reuse_held_text():
    import recalls,clinic_workflows,owner_conversations
    client,old,new,id=fixture()
    reminder=act('reminder.create',{'patient_id':old['id'],'title':'SYNTHETIC disputed care recall','due':'2099-01-05'},**TARGET)
    filters={'start':'2099-01-01','end':'2099-01-31'}
    review=client.post('/api/recalls/preview',headers=HEADERS,json=filters).json()
    campaign=act('recall.prepare',{**filters,'title':'SYNTHETIC recall campaign','digest':review['digest'],'reminder_ids':[reminder['id']]},**TARGET)
    out=campaign['data']['items'][0]['outbox_id']
    with db.connection(True) as c:
        thread=db.record(c,'owner_thread','clinic-river',{'patient_id':old['id'],'title':'SYNTHETIC prior owner question','status':'needs_attention'})
        db.record(c,'owner_turn','clinic-river',{'patient_id':old['id'],'thread_id':thread['id'],'speaker':'clinic','message':'SYNTHETIC prior clinical answer'})
        handover=clinic_workflows.prepare_handover(c,'clinic-river')
    assert client.get('/api/outbox/'+out+'/delivery-review',headers=HEADERS).status_code==200
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    assert client.get('/api/outbox/'+out+'/delivery-review',headers=HEADERS).status_code==409
    assert client.get('/api/recalls/'+campaign['id'],headers=HEADERS).status_code==409
    assert not client.post('/api/recalls/preview',headers=HEADERS,json=filters).json()['items']
    attention=client.get('/api/handover',headers=HEADERS).json()['owner_conversations']
    assert len(attention)==1 and attention[0]['clinical_reconciliation']['status']=='administrative_attention_only'
    assert 'SYNTHETIC prior clinical answer' not in json.dumps(attention)
    with db.connection() as c:
        assert get(campaign['id'])==campaign and get(handover['id'])==handover
        assert owner_conversations.handover_rows(c,'clinic-river')[0]['clinical_reconciliation']
        err(409,lambda:clinic_workflows.prepare_handover(c,'clinic-river'))
    assert campaign['id'] not in {r['id'] for r in client.get('/api/bootstrap',headers=HEADERS).json()['records']}


def test_administrative_receipts_keep_amounts_but_cannot_supply_current_clinical_facts(monkeypatch):
    from record_queries import select_records
    from assistant_context import candidates
    import exports
    rendered=[];original_render=exports.render
    def capture(*args):
        rendered.extend(item.getPlainText() for item in args[3] if hasattr(item,'getPlainText'))
        return original_render(*args)
    monkeypatch.setattr(exports,'render',capture)
    client,old,new,id=fixture()
    invoice=act('invoice.create',{'patient_id':old['id'],'items':[{'name':'SYNTHETIC historical medication wording','quantity':1,'price_cents':300}]},**TARGET)
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    bootstrap=client.get('/api/bootstrap',headers=HEADERS).json()
    shown=next(r for r in bootstrap['records'] if r['id']==invoice['id'])
    assert shown['data']==invoice['data'] and shown['clinical_reconciliation']['current_clinical_use'] is False
    with db.connection() as c:
        assert get(invoice['id'])==invoice
        assert not select_records(c,'clinic-river',{'kind':'invoice','patient_id':old['id']})['records']
        assert invoice['id'] not in {r['id'] for r in candidates(c,'clinic-river',invoice['id'])[0]}
    response=client.get('/api/invoices/'+invoice['id']+'/pdf',headers=HEADERS);assert response.status_code==200
    assert 'Clinical identity is unresolved' in ' '.join(rendered) and response.content.startswith(b'%PDF')
    patient=next(r for r in client.get('/api/patients',headers=HEADERS).json()['items'] if r['id']==old['id'])
    assert patient['data']['weight'] is None and patient['data']['clinical_reconciliation']


def test_later_retained_group_cannot_release_untraceable_patient_history():
    client,old,new,id=fixture()
    first=act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    second=act('clinical.reconcile',decision(preview(client,id),old['id'],status='retain'),**TARGET)
    assert second['data']['decisions'][0]['disposition']=='retain'
    assert get(first['id'])==first
    with db.connection() as c:
        state=reconciliation.eligibility(c,'clinic-river')
        assert old['id'] in state['patients'] and any(v['status']=='patient_identity_hold' for v in state['patients'][old['id']])
    assert client.get('/api/files/'+first['data']['decisions'][0]['origin']['target_id'],headers=HEADERS).status_code==409
    assert 'cannot release the patient hold' in preview(client,id)['patient_hold_preview']['policy']


def test_new_urgent_owner_question_stays_in_qualified_staff_queue_during_hold(monkeypatch):
    import owner_conversations as chat
    from assistant_context import candidates
    client,old,new,id=fixture()
    grant=act('share.create',{'patient_id':old['id']},**TARGET)
    act('clinical.reconcile',decision(preview(client,id),old['id']),**TARGET)
    monkeypatch.setattr(chat,'topic',lambda *_:pytest.fail('Held owner question must not call an AI provider'))
    question='SYNTHETIC urgent owner question after the identity hold'
    result=chat.send(grant['id'],chat.Message(message=question,urgent=True,key='held-urgent-question'))
    tid=result['id'];bootstrap=client.get('/api/bootstrap',headers=HEADERS).json()
    visible=next(r for r in bootstrap['records'] if r['id']==tid)
    assert visible['data']['status']=='needs_attention' and visible['data']['urgent']
    assert visible['clinical_reconciliation']['status']=='administrative_attention_only' and question not in json.dumps(visible)
    handover=client.get('/api/handover',headers=HEADERS).json()['owner_conversations']
    assert any(r['id']==tid and r['data']['urgent'] and r['clinical_reconciliation'] for r in handover)
    assert question not in json.dumps(handover)
    staff=client.get('/api/owner-conversations/'+tid,headers=HEADERS).json()
    assert question in json.dumps(staff['turns']) and staff['clinical_reconciliation']
    thread=get(tid);payload={'id':tid,'version':thread['version'],'last_owner_turn':thread['data']['last_owner_turn']}
    err(409,lambda:act('conversation.reply',{**payload,'message':'SYNTHETIC clinical instruction must remain held'},**TARGET))
    reviewed=act('conversation.acknowledge',{**payload,'reason':'SYNTHETIC staff will contact owner and review identity'},**TARGET)
    assert reviewed['data']['status']=='acknowledged'
    with db.connection() as c:
        assert tid not in {r['id'] for r in candidates(c,'clinic-river',tid)[0]}
        assert old['id'] in reconciliation.eligibility(c,'clinic-river')['patients']
