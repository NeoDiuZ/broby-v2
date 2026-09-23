"""Acceptance of clinic workflows and adversarial retries/access changes."""
from datetime import datetime, timezone
import uuid
import pytest
from fastapi.testclient import TestClient
import actions, db, main, jobs
from clinic_workflows import tick
from test_integrity import isolated, act, get, rows, err, note, generate


def command(client, name, payload, actor='clinic-east-vet', key=None):
    return client.post('/api/actions', json={'action':name,'payload':payload,'key':key or str(uuid.uuid4())}, headers={'x-actor-id':actor})


def configure(**fields):
    settings=get('settings-clinic-east')
    return act('automation.save',dict(version=settings['version'],auto_reminders=False,auto_handover=False,handover_at='07:00',**fields),actor='clinic-east-admin')


def test_patient_dob_roundtrip_and_validation():
    p=act('patient.create',dict(name='Synthetic DOB',species='Cat',owner_name='Test owner',date_of_birth='2020-02-29'))
    assert p['data']['date_of_birth']=='2020-02-29'
    for invalid in ('2020-02-30','2020-1-1','2999-01-01','not-a-date'):
        err(422,lambda:act('patient.update',dict(id=p['id'],version=p['version'],date_of_birth=invalid)))
    updated=act('patient.update',dict(id=p['id'],version=p['version'],date_of_birth=''))
    assert updated['data']['date_of_birth'] is None
    with db.connection() as c:
        assert c.execute('SELECT count(*) FROM record_versions WHERE record_id=?',(p['id'],)).fetchone()[0]==1


def test_owner_relationships_revoke_old_grants_and_preserve_primary():
    g=act('share.create',{'patient_id':'luna'})
    owner=act('owner.create',{'name':'Additional owner'})
    p=act('patient.owners',dict(id='luna',version=1,owner_id='owner-luna',additional_owner_ids=[owner['id'],owner['id'],'owner-luna']))
    assert p['data']['additional_owner_ids']==[owner['id']]
    assert TestClient(main.app).get('/api/owner/'+g['id']).status_code==404
    foreign=actions.execute('owner.create',{'name':'Other clinic'},'clinic-river','clinic-river-vet',str(uuid.uuid4()))
    err(404,lambda:act('patient.owners',dict(id='luna',version=p['version'],owner_id=foreign['id'])))
    assert get('luna')['data']['owner_id']=='owner-luna'


def test_owner_merge_moves_additional_links_without_duplicates():
    act('patient.owners',dict(id='luna',version=1,owner_id='owner-luna',additional_owner_ids=['owner-milo']))
    act('owner.merge',dict(id='owner-milo',version=1,target_id='owner-luna'),actor='clinic-east-admin')
    assert get('milo')['data']['owner_id']=='owner-luna'
    assert get('luna')['data']['additional_owner_ids']==[]


def test_multiple_saved_pets_require_individual_claims_and_revoke_independently():
    browser=TestClient(main.app)
    links={pid:act('share.create',{'patient_id':pid})['id'] for pid in ('luna','milo')}
    browser.post('/api/owner/'+links['luna']+'/claim')
    assert [p['id'] for p in browser.get('/api/owner-account').json()['pets']]==['luna']
    assert browser.get('/api/owner-account/pets/milo').status_code==404
    browser.post('/api/owner/'+links['milo']+'/claim')
    assert {p['id'] for p in browser.get('/api/owner-account').json()['pets']}=={'milo','luna'}
    assert browser.get('/api/owner-account/pets/luna').json()['patient']['id']=='luna'
    assert TestClient(main.app).get('/api/owner-account/pets/luna').status_code==401
    act('share.revoke',{'token':links['luna']})
    assert browser.get('/api/owner-account/pets/luna').status_code==404
    assert browser.get('/api/owner-account/pets/milo').status_code==200


def test_owner_intake_edit_is_private_versioned_and_frozen_after_review():
    browser=TestClient(main.app);token=act('share.create',{'patient_id':'luna'})['id'];url='/api/owner/'+token
    assert browser.post(url+'/intake',json={'reason':'   ','key':'whitespace-key'}).status_code==422
    body={'reason':'Original owner report','key':'first-intake-key'}
    id=browser.post(url+'/intake',json=body).json()['id']
    edited={'reason':'Updated owner report','key':'edited-intake-key','version':1}
    assert browser.put(url+'/intake/'+id,json=edited).status_code==200
    assert browser.put(url+'/intake/'+id,json=edited).status_code==200
    assert get(id)['version']==2
    other=act('share.create',{'patient_id':'luna'})['id']
    assert browser.get('/api/owner/'+other).json()['intakes']==[]
    assert browser.put('/api/owner/'+other+'/intake/'+id,json=edited).status_code==404
    accepted=act('intake.accept',{'id':id,'version':2})
    assert 'Updated owner report' in get(accepted['data']['source_id'])['data']['text']
    assert browser.put(url+'/intake/'+id,json={**edited,'version':3,'key':'late-edit-key'}).status_code==409
    assert 'Original owner report' not in get(accepted['data']['source_id'])['data']['text']


def test_legacy_saved_access_migrates_without_losing_the_previous_pet():
    import hashlib
    browser=TestClient(main.app);secret='synthetic-legacy-cookie'
    first=act('share.create',{'patient_id':'luna'})['id'];second=act('share.create',{'patient_id':'milo'})['id']
    with db.connection(True) as c:
        c.execute('INSERT INTO owner_claims VALUES(?,?,?)',(hashlib.sha256(secret.encode()).hexdigest(),first,'2099-01-01T00:00:00+00:00'))
    browser.cookies.set('broby_owner',secret,path='/api/owner-account')
    assert browser.post('/api/owner-account/claim/'+second).status_code==200
    assert {p['id'] for p in browser.get('/api/owner-account').json()['pets']}=={'luna','milo'}
    assert browser.get('/api/owner/vault:malformed').status_code==404


def test_reminder_edit_cancel_complete_invalidates_unsent_drafts():
    for action in ('reminder.update','reminder.cancel','reminder.complete'):
        r=act('reminder.create',{'patient_id':'luna','title':'Synthetic recall','due':'2020-01-01'})
        act('reminder.queue_due',{});r=get(r['id']);out=r['data']['outbox_id']
        p={'id':r['id'],'version':r['version']}
        if action=='reminder.update':p.update(title='Corrected recall',due='2030-01-01')
        act(action,p)
        assert get(out)['data']['status']=='cancelled'
        err(409,lambda:act('message.complete',{'id':out,'version':get(out)['version']}))
    err(422,lambda:act('reminder.create',dict(patient_id='luna',title='Invalid',due='2026-99-01')))


def test_scheduler_is_timezone_aware_idempotent_and_preserves_preferences():
    settings=get('settings-clinic-east')
    act('automation.save',dict(version=settings['version'],auto_reminders=True,auto_handover=True,handover_at='07:00'),actor='clinic-east-admin')
    setting=get(settings['id'])
    act('settings.save',dict(version=setting['version'],retention='medical_context',reminder_days=0),actor='clinic-east-admin')
    assert get(settings['id'])['data']['auto_handover'] is True
    instant=datetime(2030,1,1,23,0,tzinfo=timezone.utc) # 07:00 Jan 2 Singapore
    r=act('reminder.create',dict(patient_id='luna',title='Tomorrow locally',due='2030-01-03'))
    due=act('reminder.create',dict(patient_id='luna',title='Today locally',due='2030-01-02'))
    tick(instant);tick(instant)
    assert not get(r['id'])['data'].get('outbox_id')
    assert get(due['id'])['data']['outbox_id']
    assert len(rows('handover'))==1 and rows('handover')[0]['data']['date']=='2030-01-02'
    out=[x for x in rows('outbox') if x['data'].get('reminder_id')==due['id']]
    assert len(out)==1 and out[0]['data']['status']=='pending' and out[0]['data']['channel']=='manual'
    tick(datetime(2030,1,2,0,0,tzinfo=timezone.utc))
    assert len(rows('handover'))==1


def test_scheduler_stops_when_its_account_is_deactivated():
    settings=get('settings-clinic-east')
    act('automation.save',dict(version=settings['version'],auto_reminders=True,auto_handover=True,handover_at='00:00'),actor='clinic-east-admin')
    with db.connection(True) as c:
        member=db.get(c,'clinic-east-admin');db.update(c,member,{**member['data'],'active':False})
    tick()
    assert not rows('outbox') and not rows('handover')


def test_handover_prepare_and_acknowledgement_are_persistent_and_per_actor():
    first=act('handover.prepare',{});second=act('handover.prepare',{})
    assert first['id']==second['id']
    act('handover.acknowledge',{'id':first['id']},actor='clinic-east-nurse')
    act('handover.acknowledge',{'id':first['id']},actor='clinic-east-nurse')
    assert len(get(first['id'])['data']['acknowledged_by'])==1
    assert get(first['id'])['data']['snapshot']==first['data']['snapshot']


def test_speaker_labels_preserve_machine_evidence_and_audio_finalization():
    source=note('Synthetic speech')
    with db.connection(True) as c:
        source=db.update(c,source,{**source['data'],'utterances':[{'speaker':0,'start':0,'end':1,'text':'Synthetic speech'}]})
    result=act('source.speakers',dict(id=source['id'],version=source['version'],speaker_labels={'0':'Vet'}))
    assert result['data']['utterances']==source['data']['utterances'] and result['data']['text']=='Synthetic speech'
    err(422,lambda:act('source.speakers',dict(id=result['id'],version=result['version'],speaker_labels={'99':'Invented'})))
    rec=act('recording.create',dict(patient_id='luna',consultation_id='consult-luna'))
    client=TestClient(main.app);client.put('/api/recordings/'+rec['id']+'/chunks/0',content=b'0123456789')
    finished=act('recording.complete',dict(id=rec['id'],expected_chunks=1,duration=10))
    assert act('recording.complete',dict(id=rec['id'],expected_chunks=1,duration=10))['version']==finished['version']
    err(409,lambda:act('recording.complete',dict(id=rec['id'],expected_chunks=1,duration=11)))
    renamed=act('recording.rename',dict(id=rec['id'],version=finished['version'],title='Discharge explanation'))
    assert renamed['data']['number']==1


def test_audio_ranges_and_owner_revocation_apply_to_every_request():
    client=TestClient(main.app);rec=act('recording.create',dict(patient_id='luna',consultation_id='consult-luna'))
    client.put('/api/recordings/'+rec['id']+'/chunks/0',content=b'0123456789')
    rec=act('recording.complete',dict(id=rec['id'],expected_chunks=1,duration=10))
    g=act('share.create',{'patient_id':'luna'});url='/api/owner/'+g['id']+'/audio/'+rec['id']
    assert client.get(url,headers={'Range':'bytes=2-4'}).status_code==404
    act('recording.approve',{'id':rec['id'],'version':rec['version']})
    for header,expected in [('bytes=2-4',b'234'),('bytes=-3',b'789'),('bytes=8-',b'89')]:
        r=client.get(url,headers={'Range':header});assert r.status_code==206 and r.content==expected
    assert client.get(url,headers={'Range':'bytes=99-'}).status_code==416
    act('share.revoke',{'token':g['id']});assert client.get(url,headers={'Range':'bytes=0-2'}).status_code==404


def test_discharge_package_contains_only_approved_records_and_manual_link():
    note('PRIVATE SOURCE MUST NOT APPEAR')
    out=act('discharge.queue',{'patient_id':'luna'},key='package-once')
    assert act('discharge.queue',{'patient_id':'luna'},key='package-once')==out
    assert 'PRIVATE SOURCE MUST NOT APPEAR' not in out['data']['body']
    assert out['data']['channel']=='manual' and out['data']['status']=='pending'
    token=out['data']['grant_token'];client=TestClient(main.app)
    assert client.get('/api/owner/'+token+'/discharge.pdf').content.startswith(b'%PDF-')
    act('message.cancel',{'id':out['id'],'version':out['version']})
    assert client.get('/api/owner/'+token+'/discharge.pdf').status_code==404
    err(403,lambda:act('discharge.queue',{'patient_id':'luna'},actor='clinic-east-nurse'))


def test_capture_locks_apply_to_uploads_chunks_and_catalog():
    rec=act('recording.create',dict(patient_id='luna',consultation_id='consult-luna'))
    act('feature_locks.save',{'version':1,'actions':['source.add','recording.create','message.queue']},actor='clinic-east-admin')
    client=TestClient(main.app)
    assert client.post('/api/uploads',data={'patient_id':'luna'},files={'file':('x.txt',b'test','text/plain')}).status_code==403
    assert client.put('/api/recordings/'+rec['id']+'/chunks/0',content=b'test').status_code==403
    assert 'source.add' not in client.get('/api/bootstrap').json()['permissions']
    err(403,lambda:act('reminder.queue_due',{}))
    assert client.post('/api/uploads',headers={'x-actor-id':'clinic-east-admin'},data={'patient_id':'luna'},files={'file':('x.txt',b'test','text/plain')}).status_code==200


def test_generation_records_context_preference_at_request_time():
    note();job=generate()
    settings=get('settings-clinic-east')
    act('settings.save',{'version':settings['version'],'retention':'medical_context'},actor='clinic-east-admin')
    jobs.run_job(job['id'])
    assert get('consult-luna')['data']['context_preference']=='medical'
    assert get('consult-luna')['data']['generation_mode']=='verbatim_source_assembly'
