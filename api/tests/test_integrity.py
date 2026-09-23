import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import db, actions, jobs, main

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db,'DB',tmp_path/'test.sqlite3')
    monkeypatch.setattr(main,'DATA',tmp_path)
    db.init()

def act(name,p,actor='clinic-east-vet',key=None,clinic='clinic-east'):
    return actions.execute(name,p,clinic,actor,key or str(uuid.uuid4()))
def get(id):
    with db.connection() as c: return db.get(c,id)
def rows(kind):
    with db.connection() as c: return db.all_records(c,'clinic-east',kind)
def note(text='Owner reports normal appetite.'):
    return act('source.add',dict(patient_id='luna',consultation_id='consult-luna',text=text,section='Subjective'))
def generate():
    r=get('consult-luna')
    return act('summary.generate',dict(id=r['id'],version=r['version']))
def err(code,fn):
    with pytest.raises(HTTPException) as e: fn()
    assert e.value.status_code==code

def test_same_name_patients_are_isolated():
    act('source.add',dict(patient_id='bella-dog',text='Dog-only finding'))
    with TestClient(main.app) as client:
        response=client.post('/api/assistant',json={'message':'Bella history'}).json()
        assert len(response['choices'])==2
        response=client.post('/api/assistant',json={'message':'history','patient_id':'bella-cat'}).json()
        assert 'Dog-only finding' not in response['text']
        assert all(x['data']['patient_id']=='bella-cat' for x in response['sources'])

def test_cross_clinic_record_cannot_be_used():
    err(404,lambda:act('consultation.create',{'patient_id':'luna'},actor='clinic-river-vet',clinic='clinic-river'))

def test_duplicate_delivery_creates_one_note():
    p=dict(patient_id='luna',consultation_id='consult-luna',text='A finding')
    first=act('source.add',p,key='same-key-123')
    assert act('source.add',p,key='same-key-123')==first
    assert get('consult-luna')['data']['source_ids']==[first['id']]
    err(409,lambda:act('source.add',{**p,'text':'different'},key='same-key-123'))

def test_stale_job_never_overwrites_human_edit():
    note(); job=generate(); consult=get('consult-luna')
    act('summary.save',{'id':consult['id'],'version':consult['version'],'summary':[{'name':'Plan','text':'Reviewed by veterinarian','source_ids':[]}]})
    jobs.run_job(job['id'])
    assert get('consult-luna')['data']['summary'][0]['text']=='Reviewed by veterinarian'
    with db.connection() as c: assert c.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]=='conflict'

def test_new_note_during_generation_is_not_consumed():
    first=note(); job=generate(); second=note('New finding after job queued'); jobs.run_job(job['id'])
    assert get('consult-luna')['data']['source_ids']==[first['id'],second['id']]
    assert len(rows('source'))>=2
    latest=generate(); jobs.run_job(latest['id'])
    summary=get('consult-luna')['data']['summary'][0]
    assert 'New finding after job queued' in summary['text']
    assert summary['source_ids']==[first['id'],second['id']]

def test_stale_document_save_rejected():
    r=get('consult-luna'); note()
    err(409,lambda:act('summary.save',{'id':r['id'],'version':r['version'],'summary':[]}))

def test_nurse_cannot_approve_or_change_stock():
    err(403,lambda:act('consultation.approve',{'id':'consult-luna','version':1},actor='clinic-east-nurse'))
    err(403,lambda:act('inventory.adjust',{},actor='clinic-east-nurse'))

def test_foreign_receipt_rejected():
    s=act('source.add',dict(patient_id='milo',text='Other patient'))
    err(422,lambda:act('summary.save',dict(id='consult-luna',version=1,summary=[dict(name='Plan',text='Wrong source',source_ids=[s['id']])])) )

def test_payment_retries_and_overpayment():
    inv=rows('invoice')[0]; p={'id':inv['id'],'version':inv['version'],'amount_cents':1000,'method':'cash'}
    act('payment.record',p,key='payment-once'); act('payment.record',p,key='payment-once')
    assert get(inv['id'])['data']['paid_cents']==1000
    assert len(rows('payment'))==1
    err(422,lambda:act('payment.record',{**p,'version':2,'amount_cents':999999}))

def test_dispensing_stock_is_atomic_and_versioned():
    stock=next(r for r in rows('inventory') if r['data']['unit']=='tablet')
    p=dict(patient_id='luna',inventory_id=stock['id'],version=stock['version'],quantity=2,dose='As prescribed',frequency='As prescribed',instructions='Veterinarian instructions')
    act('medication.dispense',p)
    err(409,lambda:act('medication.dispense',p))
    assert get(stock['id'])['data']['stock']==stock['data']['stock']-2
    assert len(rows('medication'))==1

def test_schedule_overlap_rejected():
    p=dict(patient_id='luna',date='2030-01-01',time='10:00',duration=30,reason='Check')
    act('appointment.create',p)
    err(409,lambda:act('appointment.create',{**p,'time':'10:15'}))
    act('appointment.create',{**p,'time':'10:30'})

def test_import_is_all_or_nothing():
    before=len(rows('patient'))
    err(422,lambda:act('import.patients',{'rows':[dict(name='Import',species='Cat',owner_name='Owner'),dict(name='Bad',species='Cat')]},actor='clinic-east-admin'))
    assert len(rows('patient'))==before

def test_owner_link_only_approved_and_revocable():
    note('Private unapproved note')
    grant=act('share.create',{'patient_id':'luna'})
    client=TestClient(main.app)
    response=client.get('/api/owner/'+grant['id'])
    assert response.status_code==200
    assert 'Private unapproved note' not in response.text
    assert all(e['data']['patient_id']=='luna' for e in response.json()['events'])
    act('share.revoke',{'token':grant['id']})
    assert client.get('/api/owner/'+grant['id']).status_code==404

def test_audio_gap_and_duplicate_chunks():
    r=act('recording.create',dict(patient_id='luna',consultation_id='consult-luna'))
    client=TestClient(main.app); url='/api/recordings/'+r['id']+'/chunks/'
    assert client.put(url+'0',content=b'first').status_code==200
    assert client.put(url+'0',content=b'first').status_code==200
    assert client.put(url+'0',content=b'changed').status_code==409
    err(409,lambda:act('recording.complete',dict(id=r['id'],expected_chunks=2,duration=10)))
    assert client.put(url+'1',content=b'second').status_code==200
    act('recording.complete',dict(id=r['id'],expected_chunks=2,duration=10))
    assert client.get('/api/recordings/'+r['id']+'/audio').content==b'firstsecond'

def test_observation_numeric_validation_and_provenance():
    s=note(); p=dict(patient_id='luna',source_id=s['id'],name='Weight',unit='kg',value=4.1,low=2,high=6)
    act('observation.add',p)
    err(422,lambda:act('observation.add',{**p,'low':10,'high':2}))
    err(422,lambda:act('observation.add',{**p,'value':float('nan')}))
    err(422,lambda:act('observation.add',{**p,'patient_id':'milo'}))

def test_feature_locks_block_staff_but_not_admin():
    r=get('clinic-east')
    act('feature_locks.save',{'version':r['version'],'actions':['share.create']},actor='clinic-east-admin')
    err(403,lambda:act('share.create',{'patient_id':'luna'}))
    assert act('share.create',{'patient_id':'luna'},actor='clinic-east-admin')['url']

def test_owner_document_requires_explicit_approval():
    client=TestClient(main.app)
    file=client.post('/api/uploads',data={'patient_id':'luna'},files={'file':('test.txt',b'Shared instructions','text/plain')}).json()
    grant=act('share.create',{'patient_id':'luna'}); url='/api/owner/'+grant['id']
    assert client.get(url).json()['files']==[]
    assert client.get(url+'/files/'+file['id']).status_code==404
    act('attachment.approve',{'id':file['id'],'version':file['version']})
    assert len(client.get(url).json()['files'])==1
    assert client.get(url+'/files/'+file['id']).content==b'Shared instructions'
    assert 'path' not in client.get(url).json()['files'][0]['data']
    other=act('share.create',{'patient_id':'milo'})
    assert client.get('/api/owner/'+other['id']+'/files/'+file['id']).status_code==404

def test_new_source_invalidates_review_and_blocks_stale_approval():
    note(); j=generate(); jobs.run_job(j['id']); r=get('consult-luna')
    act('consultation.approve',{'id':r['id'],'version':r['version']})
    note('A later finding'); r=get('consult-luna')
    assert r['data']['status']=='in_progress'
    err(409,lambda:act('consultation.approve',{'id':r['id'],'version':r['version']}))

def test_reopening_cancelled_slot_cannot_double_book():
    p=dict(patient_id='luna',date='2030-02-01',time='11:00',duration=30,reason='Check')
    first=act('appointment.create',p)
    first=act('appointment.update',{'id':first['id'],'version':first['version'],'status':'cancelled'})
    act('appointment.create',p)
    err(409,lambda:act('appointment.update',{'id':first['id'],'version':first['version'],'status':'arrived'}))

def test_revision_history_is_immutable_and_scoped():
    before=get('luna');act('patient.update',{'id':'luna','version':before['version'],'weight':4.4})
    client=TestClient(main.app);history=client.get('/api/records/luna/history').json()
    assert history['versions'][0]['data']['weight']==4.2
    assert history['current']['data']['weight']==4.4
    assert client.get('/api/records/luna/history',headers={'x-clinic-id':'clinic-river'}).status_code==404

def test_recurring_schedule_rolls_back_on_one_collision():
    p=dict(patient_id='luna',date='2031-01-01',time='09:00',duration=30,reason='Check')
    act('appointment.create',{**p,'date':'2031-01-08'})
    before=len(rows('appointment'))
    err(409,lambda:act('appointment.series',{**p,'count':3,'interval_days':7}))
    assert len(rows('appointment'))==before

def test_reschedule_preserves_identity_and_rejects_collision():
    p=dict(patient_id='luna',date='2031-02-01',time='09:00',duration=30,reason='Check')
    first=act('appointment.create',p);other=act('appointment.create',{**p,'time':'10:00'})
    err(409,lambda:act('appointment.reschedule',{'id':first['id'],'version':first['version'],'date':p['date'],'time':'10:00'}))
    assert get(first['id'])['data']['time']=='09:00'
    moved=act('appointment.reschedule',{'id':first['id'],'version':first['version'],'date':p['date'],'time':'11:00'})
    assert moved['id']==first['id'] and moved['data']['time']=='11:00'

def test_owner_intake_retry_then_staff_acceptance():
    g=act('share.create',{'patient_id':'luna'});client=TestClient(main.app)
    body={'reason':'Owner reports reduced appetite','urgent':True,'key':'owner-request-123'}
    first=client.post('/api/owner/'+g['id']+'/intake',json=body)
    assert first.status_code==200
    assert client.post('/api/owner/'+g['id']+'/intake',json=body).json()==first.json()
    assert len(rows('intake'))==1
    r=rows('intake')[0];act('intake.accept',{'id':r['id'],'version':r['version']})
    assert get(r['id'])['data']['source_id']
    err(409,lambda:act('intake.accept',{'id':r['id'],'version':r['version']}))

def test_downstream_owner_grant_revoked_with_parent():
    client=TestClient(main.app);g=act('share.create',{'patient_id':'luna'})
    child=client.post('/api/owner/'+g['id']+'/share').json()['url'].split('token=')[1]
    assert client.get('/api/owner/'+child).status_code==200
    act('share.revoke',{'token':g['id']})
    assert client.get('/api/owner/'+child).status_code==404

def test_reminders_queue_only_once_without_sending():
    first=act('reminder.queue_due',{});second=act('reminder.queue_due',{})
    assert first['count']==1 and second['count']==0
    assert len(rows('outbox'))==1 and rows('outbox')[0]['data']['status']=='pending'

def test_refund_cannot_exceed_received_payment():
    inv=rows('invoice')[0]
    pay=act('payment.record',{'id':inv['id'],'version':inv['version'],'amount_cents':1000,'method':'cash'})
    act('payment.refund',{'id':pay['id'],'version':get(inv['id'])['version'],'amount_cents':600,'reason':'Refund received externally'})
    err(422,lambda:act('payment.refund',{'id':pay['id'],'version':get(inv['id'])['version'],'amount_cents':500,'reason':'Too much'}))
    assert get(inv['id'])['data']['paid_cents']==400

def test_typed_qualitative_observation_keeps_source():
    source=note();r=act('observation.record',{'patient_id':'luna','code':'cytology_finding','value':'Reported sample finding','source_id':source['id']})
    assert r['data']['value_type']=='text' and r['data']['source_id']==source['id']
    err(422,lambda:act('observation.record',{'patient_id':'milo','code':'cytology_finding','value':'Wrong patient','source_id':source['id']}))

def test_ai_excerpts_reject_invented_facts(monkeypatch):
    import providers
    s=note('Measured weight 4.2 kg. Owner reports normal appetite.')
    monkeypatch.setattr(providers,'model_json',lambda *a:{'sections':[{'name':'Objective','evidence':[{'source_id':s['id'],'quote':'Measured weight 9.9 kg.'}]}]})
    with pytest.raises(providers.ProviderError):providers.assemble([s],['Objective'],'medical')
    monkeypatch.setattr(providers,'model_json',lambda *a:{'sections':[{'name':'Objective','evidence':[{'source_id':s['id'],'quote':'Measured weight 4.2 kg.'}]}]})
    sections,omitted=providers.assemble([s],['Objective'],'medical')
    assert sections[0]['text']=='Measured weight 4.2 kg.'
    assert omitted[0]['text']=='Owner reports normal appetite.'

def test_transcription_job_preserves_audio_and_appends_once(monkeypatch,tmp_path):
    import providers,json
    monkeypatch.setattr(providers,'available',lambda:{'transcription':True,'ai':False})
    monkeypatch.setattr(providers,'transcribe',lambda *a:{'text':'Recorded finding.','utterances':[{'start':0,'end':1,'speaker':0,'text':'Recorded finding.'}],'provider':'mock','request_id':'test'})
    r=act('recording.create',dict(patient_id='luna',consultation_id='consult-luna'));client=TestClient(main.app)
    client.put('/api/recordings/'+r['id']+'/chunks/0',content=b'test-audio')
    act('recording.complete',{'id':r['id'],'expected_chunks':1,'duration':1})
    job=act('recording.transcribe',{'id':r['id']});jobs.run_job(job['id']);jobs.run_job(job['id'])
    source_id=get(r['id'])['data']['transcript_source_id']
    assert get(source_id)['data']['utterances'][0]['end']==1
    assert get('consult-luna')['data']['source_ids']==[source_id]
    assert client.get('/api/recordings/'+r['id']+'/audio').content==b'test-audio'

def test_password_mode_rejects_spoofed_actor_headers(monkeypatch):
    import auth
    auth.setup_tables();auth.provision('nurse','clinic-east-nurse','clinic-east','long-test-password')
    monkeypatch.setenv('BROBY_AUTH_MODE','password');client=TestClient(main.app)
    assert client.get('/api/bootstrap').status_code==401
    assert client.post('/api/login',json={'username':'nurse','password':'incorrect'}).status_code==401
    assert client.post('/api/login',json={'username':'nurse','password':'long-test-password'}).status_code==200
    data=client.get('/api/bootstrap',headers={'x-actor-id':'clinic-east-admin'}).json()
    assert data['actor']['data']['role']=='nurse'
    assert client.get('/api/bootstrap',headers={'x-clinic-id':'clinic-river'}).status_code==403
    client.post('/api/logout');assert client.get('/api/bootstrap').status_code==401

def test_complete_backup_restores_files_and_revisions(tmp_path):
    from restore_backup import restore
    import zipfile,io,json,sqlite3
    client=TestClient(main.app);r=client.post('/api/uploads',data={'patient_id':'luna'},files={'file':('notes.txt',b'Test attachment','text/plain')}).json()
    act('patient.update',{'id':'luna','version':1,'weight':4.5})
    response=client.get('/api/backup',headers={'x-actor-id':'clinic-east-admin'})
    assert response.status_code==200
    archive=tmp_path/'backup.zip';archive.write_bytes(response.content);destination=tmp_path/'restored'
    assert restore(archive,destination)>0
    assert (destination/'files'/r['id']).read_bytes()==b'Test attachment'
    with sqlite3.connect(destination/'broby.sqlite3') as c:assert c.execute("SELECT count(*) FROM record_versions WHERE record_id='luna'").fetchone()[0]==1
    with pytest.raises(ValueError):restore(archive,destination)

def test_pdf_export_returns_real_documents():
    note();j=generate();jobs.run_job(j['id']);client=TestClient(main.app)
    r=client.get('/api/consultations/consult-luna/pdf');assert r.status_code==200 and r.content.startswith(b'%PDF-')
    inv=rows('invoice')[0];assert client.get('/api/invoices/'+inv['id']+'/pdf').content.startswith(b'%PDF-')

def test_assistant_date_boundaries_and_patient_name_matching():
    import reads
    from datetime import date
    start,end=reads.period('last month');assert start.day==1 and end.month==start.month
    client=TestClient(main.app)
    result=client.post('/api/assistant',json={'message':'show information about a milestone'}).json()
    assert result.get('patient_id') is None

def test_numeric_ontology_is_persisted():
    source=note()
    r=act('observation.record',dict(patient_id='luna',source_id=source['id'],code='weight',value=4))
    assert r['data']['code']=='weight' and r['data']['value_type']=='number'

def test_import_rejects_foreign_singular_receipts_and_malformed_sections():
    source=act('source.add',dict(patient_id='milo',text='Other patient'))
    row={'id':'foreign-observation','kind':'observation','data':dict(patient_id='luna',source_id=source['id'],name='Weight',value=4,unit='kg')}
    err(422,lambda:act('import.records',{'records':[row]},actor='clinic-east-admin'))
    row={'id':'malformed-consult','kind':'consultation','data':dict(patient_id='luna',template_id='soap-clinic-east',summary=['broken'])}
    err(422,lambda:act('import.records',{'records':[row]},actor='clinic-east-admin'))
    assert get('foreign-observation') is None and get('malformed-consult') is None

def test_provider_http_contracts(monkeypatch):
    import providers,httpx,json
    monkeypatch.setenv('BROBY_ENABLE_AI','1');monkeypatch.setenv('DEEPGRAM_API_KEY','test-key');monkeypatch.setenv('ANTHROPIC_API_KEY','test-key');monkeypatch.setenv('ANTHROPIC_MODEL','test-model')
    real_client=httpx.Client
    def respond(request):
        if request.url.host=='api.deepgram.com':
            assert request.url.params['diarize']=='true' and request.url.params['utterances']=='true'
            assert request.headers['authorization']=='Token test-key'
            return httpx.Response(200,json={'results':{'channels':[{'alternatives':[{'transcript':'Recorded finding'}]}],'utterances':[{'start':0,'end':2,'speaker':0,'transcript':'Recorded finding'}]}})
        body=json.loads(request.content)
        assert body['model']=='test-model' and request.headers['anthropic-version']=='2023-06-01'
        return httpx.Response(200,json={'content':[{'type':'text','text':'{"intent":"read"}'}],'stop_reason':'end_turn'})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(respond)))
    assert providers.transcribe(b'test','audio/webm')['utterances'][0]['end']==2
    assert providers.model_json('system',{})=={'intent':'read'}

def test_lab_import_is_atomic_and_preserves_original():
    raw='name,value,unit,low,high\nCreatinine,1.2,mg/dL,0.8,2.4\nHaematocrit,40,%,30,45'
    result=act('lab.import',dict(patient_id='luna',title='Synthetic laboratory report',csv=raw))
    assert result['count']==2 and get(result['id'])['data']['text']==raw
    before=len(rows('source'))
    err(422,lambda:act('lab.import',dict(patient_id='luna',title='Invalid',csv=raw+'\nWrong,abc,kg,0,10')))
    assert len(rows('source'))==before

def test_saved_owner_vault_media_survive_link_expiry_but_not_revocation():
    client=TestClient(main.app)
    file=client.post('/api/uploads',data={'patient_id':'luna'},files={'file':('demo.txt',b'Approved instructions','text/plain')}).json()
    act('attachment.approve',{'id':file['id'],'version':file['version']})
    g=act('share.create',{'patient_id':'luna'})
    assert client.post('/api/owner/'+g['id']+'/claim').status_code==200
    with db.connection(True) as c:c.execute("UPDATE grants SET expires_at='2020-01-01' WHERE token=?",(g['id'],))
    assert client.get('/api/owner-account/files/'+file['id']).content==b'Approved instructions'
    act('share.revoke',{'token':g['id']})
    assert client.get('/api/owner-account/files/'+file['id']).status_code==404

def test_queued_generation_rechecks_current_permissions():
    note();job=generate()
    clinic=get('clinic-east')
    act('feature_locks.save',{'version':clinic['version'],'actions':['summary.generate']},actor='clinic-east-admin')
    err(403,lambda:jobs.run_job(job['id']))
    assert get('consult-luna')['data']['summary']==[]
