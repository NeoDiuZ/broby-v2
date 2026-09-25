"""Security boundaries exercised through HTTP and the shared action executor."""
import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
import db, main, actions, read_access
from test_integrity import isolated, act, get, rows, err

ADMIN='clinic-east-admin'
VET='clinic-east-vet'

def restrict(capability, actor=VET):
    member=get(actor)
    return act('access.member',{'id':actor,'version':member['version'],'restrictions':[capability],'reason':'Synthetic access review'},actor=ADMIN)

def client(actor=VET):
    return TestClient(main.app,headers={'x-clinic-id':'clinic-east','x-actor-id':actor})

def test_every_staff_route_has_explicit_policy():
    assert all(read_access.route_policy(r.path) is not None for r in main.app.routes if isinstance(r,APIRoute))
    assert read_access.route_policy('/api/future-secret-export') is None

@pytest.mark.parametrize('capability',read_access.READS)
def test_bootstrap_filters_records_and_dependent_writes(capability):
    before=client().get('/api/bootstrap').json()
    restrict(capability)
    result=client().get('/api/bootstrap').json()
    assert capability not in result['read_permissions']
    assert not result['jobs']
    assert all(r['id']==VET or capability not in read_access.requirements(r) for r in result['records'])
    assert all(capability not in read_access.action_reads(a) for a in result['permissions'])
    assert any(r['id']==VET for r in result['records'])
    assert len(result['records'])<len(before['records'])
    assert get(VET)['data']['role']=='vet'

@pytest.mark.parametrize('path',[
 '/api/assistant/conversations','/api/assistant/conversations/old',
 '/api/files/old','/api/recordings/old/audio','/api/recordings/old/manifest',
 '/api/jobs/old','/api/records/old/history','/api/patients/luna/timeline',
 '/api/v2/patients/luna/timeline','/api/v2/patients/luna/events/old',
 '/api/v2/sources/old','/api/consultations/consult-luna/pdf',
 '/api/dashboards/old','/api/handover','/api/v2/overview',
 '/api/transfers/incoming','/api/transfers/old/preview',
 '/api/operations/status','/api/operations/health',
 '/api/invoices/old/pdf','/api/credit-notes/old/pdf','/api/credit-notes/export',
 '/api/reports/financial','/api/reports/financial/export','/api/integrations/stripe/status',
 '/api/reports/operations','/api/reports/operations/export',
])
def test_restricted_paths_fail_before_missing_record_or_provider_read(path):
    restrict('read.billing')
    assert client().get(path).status_code==403

@pytest.mark.parametrize('path',['/api/export','/api/backup','/api/audit'])
def test_restricted_administrator_cannot_export_or_audit(path):
    other=act('member.save',{'name':'Synthetic reviewer','role':'admin'},actor=ADMIN)
    restrict('read.billing',other['id'])
    assert client(other['id']).get(path).status_code==403

def test_clinic_locks_spare_admin_but_inherited_locks_do_not():
    clinic=get('clinic-east')
    act('feature_locks.save',{'version':clinic['version'],'actions':['read.billing']},actor=ADMIN)
    assert 'read.billing' not in client().get('/api/bootstrap').json()['read_permissions']
    assert 'read.billing' in client(ADMIN).get('/api/bootstrap').json()['read_permissions']
    act('organization.create',{'name':'Synthetic org'},actor=ADMIN)
    other=act('member.save',{'name':'Second admin','role':'admin'},actor=ADMIN)
    act('organization.policy',{'actions':['read.inventory']},actor=ADMIN)
    assert 'read.inventory' not in client(other['id']).get('/api/bootstrap').json()['read_permissions']
    assert 'read.inventory' in client(ADMIN).get('/api/bootstrap').json()['read_permissions']
    err(409,lambda:act('access.member',{'id':ADMIN,'version':get(ADMIN)['version'],'restrictions':['read.billing'],'reason':'Try master'},actor=other['id']))

def test_versioned_access_changes_preserve_member_fields_and_history():
    with db.connection(True) as c:
        m=db.get(c,VET);db.update(c,m,{**m['data'],'extra':'keep'})
    old=get(VET)
    restrict('read.billing')
    changed=get(VET)
    assert changed['data']['extra']=='keep'
    err(409,lambda:act('access.member',{'id':VET,'version':old['version'],'restrictions':[],'reason':'stale'},actor=ADMIN))
    act('member.save',{'id':VET,'version':changed['version'],'name':'Renamed vet','role':'vet','active':True},actor=ADMIN)
    assert get(VET)['data']['read_restrictions']==['read.billing']
    with db.connection() as c:
        assert c.execute('SELECT count(*) FROM audit WHERE action=?',('access.member',)).fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM record_versions WHERE record_id=?',(VET,)).fetchone()[0]>=2
    act('access.member',{'id':VET,'version':get(VET)['version'],'restrictions':[],'reason':'Restore access'},actor=ADMIN)
    assert 'read.billing' in client().get('/api/bootstrap').json()['read_permissions']

@pytest.mark.parametrize('values',[['wrong'],[{}],'read.billing',None])
def test_invalid_restrictions_cannot_change_access(values):
    before=get(VET)
    err(422,lambda:act('access.member',{'id':VET,'version':before['version'],'restrictions':values,'reason':'invalid'},actor=ADMIN))
    assert get(VET)==before

def test_no_self_lock_or_cross_clinic_member_change():
    err(409,lambda:act('access.member',{'id':ADMIN,'version':get(ADMIN)['version'],'restrictions':['read.billing'],'reason':'self'},actor=ADMIN))
    err(404,lambda:act('access.member',{'id':'clinic-river-vet','version':1,'restrictions':['read.billing'],'reason':'foreign'},actor=ADMIN))
    err(403,lambda:act('access.member',{'id':ADMIN,'version':1,'restrictions':[],'reason':'not admin'}))

def test_action_retry_does_not_return_now_hidden_invoice():
    payload={'patient_id':'luna','items':[{'name':'Synthetic fee','quantity':1,'price_cents':100}]}
    first=act('invoice.create',payload,key='invoice-before-lock')
    restrict('read.billing')
    err(403,lambda:act('invoice.create',payload,key='invoice-before-lock'))
    err(403,lambda:act('invoice.create',payload))
    assert get(first['id'])['data']['total_cents']==100
    assert client().get('/api/patients').status_code==200
    assert client().post('/api/actions',json={'action':'read.billing','payload':{},'key':'not-a-write'}).status_code==404

def test_assistant_and_cached_turns_do_not_leak_after_revocation(monkeypatch):
    monkeypatch.setattr('providers.available',lambda:{'ai':False,'transcription':False})
    cli=client()
    first=cli.post('/api/assistant',json={'message':'outstanding invoices','key':'question-before-lock'}).json()
    assert first.get('conversation_id')
    restrict('read.billing')
    monkeypatch.setattr('providers.model_json',lambda *a,**k:pytest.fail('No provider call after revoked access'))
    assert cli.post('/api/assistant',json={'message':'outstanding invoices','key':'question-before-lock'}).status_code==403
    assert cli.get('/api/assistant/conversations/'+first['conversation_id']).status_code==403
    from assistant_history import ask
    err(403,lambda:ask('clinic-east',VET,'outstanding invoices',None,None,'question-before-lock'))

def test_unknown_record_and_mixed_copy_hidden_for_restricted_member():
    with db.connection(True) as c: db.record(c,'future_financial_document','clinic-east',{'body':'must not leak'})
    restrict('read.inventory')
    result=client().get('/api/bootstrap').json()
    assert 'must not leak' not in str(result)
    assert not any(r['kind'] in ('event','source','recording','attachment') for r in result['records'])

def test_old_owner_grant_is_separate_and_still_only_approved():
    grant=act('share.create',{'patient_id':'luna'})
    restrict('read.billing')
    response=client().get('/api/owner/'+grant['id'])
    assert response.status_code==200
    assert 'invoice' not in response.json()

@pytest.mark.parametrize('saved',[False,True])
def test_permission_revoked_during_model_call_blocks_returned_answer(monkeypatch,saved):
    monkeypatch.setattr('providers.available',lambda:{'ai':True,'transcription':False})
    def response(*args,**kwargs):
        restrict('read.billing')
        return {'read':{'kind':'invoice'}}
    monkeypatch.setattr('providers.model_json',response)
    payload={'message':'outstanding invoices'}
    if saved:payload['key']='inflight-revocation-test'
    assert client().post('/api/assistant',json=payload).status_code==403
    with db.connection() as c:
        assert c.execute("SELECT count(*) FROM assistant_turns WHERE status='completed'").fetchone()[0]==0
