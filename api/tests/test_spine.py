"""Specification acceptance tests against a real, isolated PostgreSQL schema."""
import uuid,os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,text,select,func
from alembic import command
from alembic.config import Config
import db,auth,main,actions
from spine import database,projection
from spine.models import Event,Observation,Member,Patient,Owner,OwnerPatient

@pytest.fixture
def client(tmp_path,monkeypatch):
    url=os.getenv('BROBY_TEST_SPINE_URL') or os.getenv('BROBY_SPINE_URL')
    if not url:pytest.fail('PostgreSQL acceptance tests require BROBY_TEST_SPINE_URL or BROBY_SPINE_URL; run scripts/start-spine.sh')
    admin=create_engine(url);schema='acceptance_'+uuid.uuid4().hex
    with admin.begin() as c:c.exec_driver_sql('CREATE SCHEMA '+schema)
    engine=create_engine(url,connect_args={'options':'-csearch_path='+schema})
    monkeypatch.setattr(database,'engine',lambda:engine)
    monkeypatch.setattr(db,'DB',tmp_path/'legacy.sqlite3');monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setenv('BROBY_AUTH_MODE','demo')
    try:
        command.upgrade(Config(str(Path(main.__file__).parent/'alembic.ini')),'head')
        db.init();auth.setup_tables();projection.setup_queue()
        yield TestClient(main.app)
    finally:
        engine.dispose()
        with admin.begin() as c:c.exec_driver_sql('DROP SCHEMA '+schema+' CASCADE')
        admin.dispose()

def result(**changes):
    return {'patient_id':'milo','dedupe_key':'lab:report-001','occurred_at':'2026-09-18T09:14:00Z','summary':'Haematology + biochemistry','actor':{'kind':'system','name':'Synthetic analyser'},'source':{'kind':'document','id':'report-001','page':1,'text':'Potassium 5.8 mmol/L. Lab reference 3.5–5.1.'},'body':{'accession':'001'},'observations':[{'concept':'potassium','name':'Potassium','value':5.8,'unit':'mmol/L','ref_low':3.5,'ref_high':5.1}],**changes}


def test_sqlite_projection_queue_tracks_only_clinical_writes(client):
    if db.store()!='sqlite':pytest.skip('SQLite projection queue contract')
    with db.connection(True) as c:
        before=c.execute("SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id='clinic-east'").fetchone()[0]
        dashboard=db.record(c,'dashboard','clinic-east',{'name':'Synthetic display only'})
        db.update(c,dashboard,{'name':'Synthetic display revised'})
        assert c.execute("SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id='clinic-east'").fetchone()[0]==before
        owner=db.get(c,'owner-milo')
        db.update(c,owner,{**owner['data'],'name':'SYNTHETIC changed owner'})
        assert c.execute("SELECT COALESCE(MAX(sequence),0) FROM spine_changes WHERE clinic_id='clinic-east'").fetchone()[0]>before

def ingest(client,p=None,**kwargs):return client.post('/api/v2/ingest/lab',json=p or result(),**kwargs)

def test_lab_without_visit_is_one_patient_event(client):
    with db.connection() as c:before=len(db.all_records(c,'clinic-east','consultation'))
    response=ingest(client);assert response.status_code==200,response.text
    eid=response.json()['id'];timeline=client.get('/api/v2/patients/milo/timeline').json()
    e=next(x for x in timeline['items'] if x['id']==eid)
    assert e['event_type']=='lab_result' and e['source']['page']==1
    assert e['observations'][0]['value']==5.8
    with db.connection() as c:assert len(db.all_records(c,'clinic-east','consultation'))==before
    with database.session() as s:assert s.scalar(select(func.count()).select_from(Event).where(Event.dedupe_key=='lab:report-001'))==1

def test_portal_conversation_projects_exact_human_receipts_to_patient_timeline(client,monkeypatch):
    import owner_conversations as chat
    monkeypatch.setattr(chat,'topic',lambda message:('staff','rules'))
    token=actions.execute('share.create',{'patient_id':'milo'},'clinic-east','clinic-east-vet',str(uuid.uuid4()))['id']
    question=chat.Message(message='SYNTHETIC owner question without a visit',key='timeline-question')
    result=chat.send(token,question);chat.send(token,question)
    with db.connection() as c:thread=db.get(c,result['id'])
    actions.execute('conversation.reply',{'id':thread['id'],'version':thread['version'],'last_owner_turn':thread['data']['last_owner_turn'],'message':'SYNTHETIC clinic reply'},'clinic-east','clinic-east-vet',str(uuid.uuid4()))
    timeline=client.get('/api/v2/patients/milo/timeline?category=message').json()['items']
    assert len(timeline)==2
    texts=[]
    for event in timeline:
        assert event['event_type']=='message' and event['source']['kind']=='human'
        receipt=client.get('/api/v2/sources/'+event['source']['receipt_id'])
        assert receipt.status_code==200
        texts.append(receipt.json()['text'])
    assert set(texts)=={'SYNTHETIC owner question without a visit','SYNTHETIC clinic reply'}
    assert client.get('/api/v2/patients/luna/timeline?category=message').json()['items']==[]

def test_same_result_across_actors_and_concurrent_requests_creates_one(client):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(lambda n:ingest(client,headers={'x-actor-id':'clinic-east-vet' if n%2 else 'clinic-east-nurse'}),range(4)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert len({r.json()['id'] for r in responses})==1
    assert sum(not r.json()['duplicate'] for r in responses)==1
    with database.session() as s:assert s.scalar(select(func.count()).select_from(Observation).join(Event).where(Event.dedupe_key=='lab:report-001'))==1
    assert ingest(client,result(summary='Changed report')).status_code==409

def test_missing_source_is_returned_as_needs_checking(client):
    e=ingest(client,result(source=None)).json()['event']
    assert e['source'] is None
    assert {'type':'missing_source'} in e['flags']
    assert any(f.get('observation_id') for f in e['flags'] if f['type']=='missing_source')

def test_ranges_high_low_normal_and_absent_are_deterministic(client):
    cases=[(5.8,3.5,5.1,'high'),(4.0,3.5,5.1,None),(3.0,3.5,5.1,'low'),(99,None,None,None)]
    for i,(value,low,high,expected) in enumerate(cases):
        p=result(dedupe_key='range:'+str(i),observations=[{'concept':'potassium','name':'Potassium','value':value,'unit':'mmol/L','ref_low':low,'ref_high':high}])
        e=ingest(client,p).json()['event'];assert e['observations'][0]['flag']==expected
        assert any(f['type']=='out_of_range' for f in e['flags'])==(expected is not None)
    series=client.get('/api/v2/patients/milo/observations?concept=potassium').json()
    assert len(series['series'])==4 and series['concept']['unit']=='mmol/L'
    assert all(x['event_id'] and x['source']['page']==1 for x in series['series'])

def test_new_event_type_no_migration(client):
    p=result(event_type='home_monitor_reading',observations=[],dedupe_key='new-type')
    r=client.post('/api/v2/events',json=p);assert r.status_code==200,r.text
    assert r.json()['event']['event_type']=='home_monitor_reading'
    assert client.get('/api/v2/patients/milo/timeline?category=home_monitor_reading').json()['items'][0]['id']==r.json()['id']

def test_clinic_patient_and_receipt_isolation(client):
    r=ingest(client).json();rid=r['event']['source']['receipt_id']
    other={'x-clinic-id':'clinic-river','x-actor-id':'clinic-river-vet'}
    for path in ('/api/v2/patients/milo/timeline','/api/v2/sources/'+rid):assert client.get(path,headers=other).status_code==404
    assert ingest(client,headers=other).status_code==404
    assert client.get('/api/v2/patients/luna/events/'+r['id']).status_code==404

def test_cursor_pagination_and_owner_search(client):
    for i in range(6):assert ingest(client,result(dedupe_key='page:'+str(i))).status_code==200
    seen=[];cursor=''
    while True:
        r=client.get('/api/v2/patients/milo/timeline',params={'limit':2,'cursor':cursor,'category':'lab_result'}).json()
        seen.extend(x['id'] for x in r['items']);cursor=r['next_cursor']
        if not cursor:break
    assert len(seen)==6 and len(set(seen))==6
    patients=client.get('/api/v2/patients?q=Rachel').json()['items'];assert [p['id'] for p in patients]==['milo']
    assert client.get('/api/v2/patients/milo/timeline?cursor=invalid').status_code==422

def test_invalid_result_is_atomic(client):
    p=result();p['observations'].append({**p['observations'][0],'ref_low':10,'ref_high':1})
    assert ingest(client,p).status_code==422
    with database.session() as s:assert s.scalar(select(func.count()).select_from(Event).where(Event.dedupe_key=='lab:report-001'))==0
    p=result(occurred_at='2026-09-18T09:14:00');assert ingest(client,p).status_code==422

def test_member_can_belong_to_multiple_clinics(client):
    auth.provision('shared','clinic-east-vet','clinic-east','test-password-1234')
    with db.connection(True) as c:c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',('shared','clinic-river-vet','clinic-river'))
    projection.sync('clinic-east');projection.sync('clinic-river')
    with database.session() as s:assert len(s.scalars(select(Member).where(Member.person_id=='account:shared')).all())==2

def test_legacy_change_projects_without_overwriting_native_event(client):
    native=ingest(client).json()['id']
    actions.execute('patient.update',{'id':'milo','version':1,'name':'Milo updated'},'clinic-east','clinic-east-vet','rename-test-key')
    assert client.get('/api/v2/patients/milo').json()['name']=='Milo updated'
    assert client.get('/api/v2/patients/milo/events/'+native).status_code==200

def test_source_positions_and_permission_locks(client):
    p=result(source={'kind':'audio','id':'sample-note','start_ms':1200,'end_ms':2400,'text':'Recorded statement'})
    e=ingest(client,p).json()['event'];source=client.get('/api/v2/sources/'+e['source']['receipt_id']).json()
    assert source['start_ms']==1200 and source['end_ms']==2400
    actions.execute('feature_locks.save',{'version':1,'actions':['source.add']},'clinic-east','clinic-east-admin','lock-test-key')
    assert ingest(client,result(dedupe_key='blocked')).status_code==403

def test_alembic_revision_and_jsonb_tables(client):
    with database.engine().connect() as c:
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0003'
        assert c.execute(text("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='events' AND column_name='body'")).scalar_one()=='jsonb'


def test_owner_contacts_dob_and_category_aliases_project_consistently(client):
    from clinic_workflows import owner_ids
    actions.execute('patient.update',{'id':'luna','version':1,'date_of_birth':'2020-02-29'},'clinic-east','clinic-east-vet','dob-roundtrip')
    actions.execute('patient.owners',{'id':'luna','version':2,'owner_id':'owner-luna','additional_owner_ids':['owner-milo']},'clinic-east','clinic-east-vet','owners-roundtrip')
    p=client.get('/api/v2/patients/luna').json()
    assert p['date_of_birth']=='2020-02-29' and p['owner']['id']=='owner-luna'
    with database.session() as s:
        assert len(s.scalars(select(OwnerPatient).where(OwnerPatient.patient_id=='luna')).all())==2
    assert any(p['id']=='luna' for p in client.get('/api/v2/patients?q=Rachel').json()['items'])
    source=actions.execute('source.add',{'patient_id':'luna','category':'x-ray','title':'Imaging note','text':'Searchable synthetic imaging detail'},'clinic-east','clinic-east-vet','xray-source')
    for category in ('x-ray','x_ray','xray'):
        records=client.get('/api/v2/patients/luna/timeline',params={'category':category,'q':'synthetic imaging detail'}).json()['items']
        assert len(records)==1 and records[0]['event_type']=='x_ray'


def test_overview_includes_native_labs_scopes_clinic_and_keeps_exact_boundaries(client):
    from datetime import datetime,timezone
    p=result(occurred_at=datetime.now(timezone.utc).isoformat())
    eid=ingest(client,p).json()['id']
    data=client.get('/api/v2/overview?days=7').json()
    assert any(r['event_id']==eid and r['source']['page']==1 for r in data['flagged'])
    assert any(r['name']=='lab_result' and r['count']>=1 for r in data['categories'])
    other=client.get('/api/v2/overview',headers={'x-clinic-id':'clinic-river'}).json()
    assert other['flagged']==[] and other['patient_count']==0
    for value in (3.5,5.1):
        p=result(dedupe_key='boundary:'+str(value),observations=[{'concept':'potassium','name':'Potassium','value':value,'unit':'mmol/L','ref_low':3.5,'ref_high':5.1}])
        assert ingest(client,p).json()['event']['observations'][0]['flag'] is None


def test_upgrade_from_existing_0001_preserves_patient_events(client):
    p=result();eid=ingest(client,p).json()['id']
    config=Config(str(Path(main.__file__).parent/'alembic.ini'))
    command.downgrade(config,'0001')
    with database.engine().connect() as c:
        assert c.execute(text('SELECT count(*) FROM events WHERE id=:id'),{'id':eid}).scalar_one()==1
    command.upgrade(config,'head')
    current=client.get('/api/v2/patients/milo/events/'+eid).json()
    assert current['observations'][0]['value']==5.8
    assert client.get('/api/v2/patients/milo').json()['owner']['id']=='owner-milo'

@pytest.mark.parametrize('value,value_type,code', [('No growth','text','culture_finding'),(False,'boolean','parasites_seen')])
def test_typed_native_facts_reach_assistant_saved_view_and_approved_owner(client,monkeypatch,value,value_type,code):
    import providers
    monkeypatch.setattr(providers,'available',lambda:{'ai':False})
    p=result(dedupe_key='typed:'+code,observations=[{'concept':code,'name':code,'value':value,'value_type':value_type,'unit':''}])
    response=ingest(client,p);assert response.status_code==200,response.text
    e=response.json()['event'];assert e['observations'][0]['value']==value and e['observations'][0]['value_type']==value_type
    assert any(r['kind']=='observation' and r['data'].get('native_spine') and r['data']['value']==value for r in client.get('/api/bootstrap').json()['records'])
    assistant=client.post('/api/assistant',json={'message':'Show observations','patient_id':'milo'}).json()
    assert any(r['data']['value']==value and r['data'].get('native_spine') for r in assistant['sources'])
    view=actions.execute('dashboard.save',{'name':'Typed facts','query':{'kind':'observation','patient_id':'milo','code':code,'value_equals':value}},'clinic-east','clinic-east-vet',str(uuid.uuid4()))
    filtered=client.get('/api/dashboards/'+view['id']).json()['result']
    assert filtered['count']==1 and filtered['records'][0]['data']['value']==value
    grant=actions.execute('share.create',{'patient_id':'milo'},'clinic-east','clinic-east-vet',str(uuid.uuid4()))
    assert not any(r['id']==e['id'] for r in client.get('/api/owner/'+grant['id']).json()['events'])
    actions.execute('clinical.approve',{'id':e['id'],'approved':True},'clinic-east','clinic-east-vet',str(uuid.uuid4()))
    owner=client.get('/api/owner/'+grant['id']).json()
    event=next(r for r in owner['events'] if r['id']==e['id'])
    assert event['data']['observations'][0]['value']==value
    assert 'source' not in event['data']['observations'][0] and 'receipt' not in event['data']
    assert client.get('/api/dashboards/'+view['id'],headers={'x-clinic-id':'clinic-river'}).status_code==404


def test_native_query_assistant_dashboard_numeric_date_and_receipt_parity(client,monkeypatch):
    import providers
    for i,(value,when) in enumerate([(6.2,'2026-09-23T17:00:00Z'),(4.1,'2026-09-23T17:00:00Z'),(6.3,'2026-09-23T15:00:00Z')]):
        assert ingest(client,result(dedupe_key='query:'+str(i),occurred_at=when,observations=[{'concept':'potassium','name':'Potassium','value':value,'unit':'mmol/L'}])).status_code==200
    contract={'kind':'observation','code':'potassium','unit':'mmol/L','value_min':5,'start':'2026-09-24','end':'2026-09-24','group_by':'day'}
    monkeypatch.setattr(providers,'available',lambda:{'ai':True})
    monkeypatch.setattr(providers,'model_json',lambda *args:{'read':contract})
    answer=client.post('/api/assistant',json={'message':'Show recorded potassium at least 5 mmol/L on 2026-09-24','patient_id':'milo'}).json()
    assert answer['dashboard']['count']==1 and answer['sources'][0]['data']['value']==6.2
    assert answer['sources'][0]['data']['receipt']['receipt_id']
    view=actions.execute('dashboard.save',{'name':'Native filtered facts','query':answer['dashboard']['query']},'clinic-east','clinic-east-vet',str(uuid.uuid4()))
    saved=client.get('/api/dashboards/'+view['id']).json()['result']
    assert saved['records']==answer['sources'] and saved['groups']==[{'label':'2026-09-24','count':1}]


def test_typed_values_reject_ranges_coercion_and_concept_type_changes(client):
    for value,typ in [('5.8','number'),(1,'boolean'),(True,'number'),('', 'text')]:
        p=result(observations=[{'concept':'typed','name':'Typed','value':value,'value_type':typ,'unit':'unit'}])
        assert ingest(client,p).status_code==422
    p=result(observations=[{'concept':'text_entry','name':'Text','value':'present','value_type':'text','unit':'','ref_low':0}])
    assert ingest(client,p).status_code==422
    assert ingest(client).status_code==200
    p=result(dedupe_key='changed-type',observations=[{'concept':'potassium','name':'Potassium','value':'positive','value_type':'text','unit':'mmol/L'}])
    assert ingest(client,p).status_code==409


def test_ingest_cannot_self_approve_and_shared_action_is_audited(client):
    p=result(event_type='lab_result',body={'owner_approved':True,'approved_by':'forged'})
    r=client.post('/api/actions',json={'action':'clinical.ingest','payload':p,'key':'shared-ingest-key'});assert r.status_code==200,r.text
    assert not r.json()['event']['body'].get('owner_approved')
    with db.connection() as c:assert c.execute("SELECT count(*) FROM audit WHERE action='clinical.ingest'").fetchone()[0]==1


def test_legacy_text_and_boolean_observations_are_projected(client):
    source=actions.execute('source.add',{'patient_id':'milo','text':'Synthetic no growth'},'clinic-east','clinic-east-vet',str(uuid.uuid4()))
    actions.execute('observation.record',{'patient_id':'milo','source_id':source['id'],'code':'cytology_finding','value':'Synthetic no growth'},'clinic-east','clinic-east-vet',str(uuid.uuid4()))
    events=client.get('/api/v2/patients/milo/timeline').json()['items']
    assert any(o['value']=='Synthetic no growth' and o['value_type']=='text' for e in events for o in e['observations'])


def test_clinic_archive_preserves_native_facts_and_blocks_partial_restore(client,tmp_path):
    import io,json,zipfile
    from restore_backup import restore
    eid=ingest(client).json()['id']
    admin={'x-actor-id':'clinic-east-admin'}
    assert any(r['id']==eid for r in client.get('/api/export',headers=admin).json()['records'])
    r=client.get('/api/backup',headers=admin);assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest=json.loads(z.read('manifest.json'));spine=json.loads(z.read('spine.json'))
    assert manifest['native_event_count']==1
    assert any(e['id']==eid and e['dedupe_key']=='lab:report-001' for e in spine['tables']['events'])
    assert all(e['clinic_id']=='clinic-east' for e in spine['tables']['events'])
    assert any(o['event_id']==eid and o['value']==5.8 for o in spine['tables']['observations'])
    other=client.get('/api/backup',headers={'x-clinic-id':'clinic-river','x-actor-id':'clinic-river-admin'})
    with zipfile.ZipFile(io.BytesIO(other.content)) as z:
        assert not json.loads(z.read('spine.json'))['tables']['events']
    archive=tmp_path/'native.zip';archive.write_bytes(r.content)
    with pytest.raises(ValueError,match='coordinated'):restore(archive,tmp_path/'restore')


def test_existing_patient_link_preserves_native_history_and_owner_projection(client):
    """Exercise the receiving record review and transfer across both real stores."""
    from fastapi import HTTPException
    import transfers
    river={'x-clinic-id':'clinic-river','x-actor-id':'clinic-river-vet'}
    def act(name,p,clinic='clinic-river'):
        return actions.execute(name,p,clinic,clinic+'-vet',str(uuid.uuid4()))
    patient=act('patient.create',{'name':'SYNTHETIC independent Luna','species':'Cat','owner_name':'Receiving owner'})
    extra=act('owner.create',{'name':'Receiving additional owner'})
    patient=act('patient.owners',{'id':patient['id'],'version':patient['version'],'owner_id':patient['data']['owner_id'],'additional_owner_ids':[extra['id']]})
    target_lab=client.post('/api/v2/ingest/lab',json=result(patient_id=patient['id'],dedupe_key='link:receiving',summary='Independent receiving lab'),headers=river)
    assert target_lab.status_code==200,target_lab.text
    target_id=target_lab.json()['id']
    source_lab=ingest(client,result(patient_id='luna',dedupe_key='link:source',summary='Approved source lab')).json()
    act('clinical.approve',{'id':source_lab['id'],'approved':True},'clinic-east')
    grant=act('share.create',{'patient_id':'luna'},'clinic-east')
    request=client.post('/api/owner/'+grant['id']+'/transfers',json={'target_clinic':'clinic-river','consent':True}).json()
    route='/api/transfers/'+request['id']+'/preview'
    def review():
        response=client.get(route,params={'target_patient_id':patient['id']},headers=river)
        assert response.status_code==200,response.text
        return response.json()
    first=review()
    assert any(x['id']==target_id and x['data']['native_spine'] for x in first['existing_patient_review']['existing_records'])
    p={'id':request['id'],'target_patient_id':patient['id'],'expected_digest':first['digest'],'link_existing_patient':True,'acknowledge_existing_history':True,'patient_match_reason':'Checked synthetic patient identity and independently recorded lab history.'}
    act('clinical.approve',{'id':target_id,'approved':True})
    with pytest.raises(HTTPException) as exc:act('transfer.accept',p)
    assert exc.value.status_code==409
    current=review()
    result_=act('transfer.accept',{**p,'expected_digest':current['digest']})
    assert result_['id']==patient['id']
    timeline=client.get('/api/v2/patients/'+patient['id']+'/timeline',headers=river).json()['items']
    assert any(e['id']==target_id for e in timeline)
    assert any(e['summary']=='Reviewed existing-patient link' and e['source'] for e in timeline)
    with database.session() as s:
        assert s.get(Event,target_id).body['owner_approved'] is True
        assert s.scalar(select(func.count()).select_from(Patient).where(Patient.clinic_id=='clinic-river'))==1
        assert {link.owner_id for link in s.scalars(select(OwnerPatient).where(OwnerPatient.patient_id==patient['id']))}=={patient['data']['owner_id'],extra['id']}
        assert s.get(Patient,patient['id']).name=='SYNTHETIC independent Luna'
        assert s.get(Owner,patient['data']['owner_id']).name=='Receiving owner'
    with db.connection() as c:assert db.get(c,patient['id'])==patient


def test_patient_page_aggregates_are_bounded_and_preserve_counts_and_owner(client):
    from sqlalchemy import event
    from spine import service
    projection.sync('clinic-east')
    with database.session() as s:
        selected=s.scalars(select(Patient).where(Patient.clinic_id=='clinic-east')).all()
        expected={p.id:service.patient_view(s,p) for p in selected}
    queries=[]
    def capture(c,cursor,statement,parameters,context,executemany):queries.append(statement)
    engine=database.engine();event.listen(engine,'before_cursor_execute',capture)
    try:
        with database.session() as s:result=service.patients(s,'clinic-east','',200,'')
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert len(queries)==5
    assert {r['id']:r for r in result['items']}==expected
    milo=next(r for r in result['items'] if r['id']=='milo')
    assert milo['owner']=={'id':'owner-milo','name':'Rachel Tan'}
    assert milo['stats']=={'visits':1,'observations':1,'document_sources':0}
    with database.session() as s:
        assert service.patients(s,'clinic-river','',50,'')['items']==[]
        assert service.patients(s,'clinic-east','no such synthetic name',50,'')['items']==[]
