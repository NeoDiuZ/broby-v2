from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import db,auth,main,organization_adoption as adoption
from test_integrity import isolated,act,get,rows,err
ADMIN='clinic-east-admin';TARGET='clinic-river';TARGET_ADMIN='clinic-river-admin'

@pytest.fixture
def org():
 auth.provision('synthetic-master',ADMIN,'clinic-east','Synthetic-password-for-tests')
 auth.provision('synthetic-clinic',TARGET_ADMIN,TARGET,'Synthetic-password-for-tests')
 return act('organization.create',{'name':'Synthetic parent'},actor=ADMIN)

def target(action,p,**kw):return act(action,p,actor=TARGET_ADMIN,clinic=TARGET,**kw)
def join(org):
 with db.connection() as c:p=adoption.consent(c,TARGET,org['id'])
 return target('organization.join_request',{'organization_id':org['id'],'digest':adoption.digest(p),'accept_access':True,'reason':'Synthetic administrator approval'})
def checked(r):
 with db.connection() as c:return adoption.acceptance(c,r)[0]
def approve(r,**kw):
 p=checked(r)
 return act('organization.join_review',{'id':r['id'],'version':r['version'],'decision':'accepted','digest':p['digest'],'accept_access':True,'reason':'Synthetic master review',**kw},actor=ADMIN)

def test_two_sided_acceptance_preserves_clinic_records_and_grants_scoped_membership(org):
 with db.connection() as c:before=db.all_records(c,TARGET)
 r=join(org)
 with db.connection() as c:
  assert not adoption.policy(c,TARGET)
  assert not c.execute('SELECT 1 FROM auth_memberships WHERE username=? AND clinic_id=?',('synthetic-master',TARGET)).fetchone()
 p=checked(r);result=approve(r);assert result['data']['status']=='accepted'
 with db.connection() as c:
  assert all(db.get(c,x['id'])==x for x in before)
  assert adoption.policy(c,TARGET)['id']==org['id']
  assert c.execute('SELECT member_id FROM auth_memberships WHERE username=? AND clinic_id=?',('synthetic-master',TARGET)).fetchone()[0]==result['data']['master_member_id']
  assert db.get(c,result['data']['master_member_id'])['data']['role']=='admin'
  assert c.execute("SELECT COUNT(*) FROM audit WHERE action='organization.join_review' AND resource_id=?",(r['id'],)).fetchone()[0]==2

@pytest.mark.parametrize('change',['policy','clinic','deactivate','demote','expired','joined_elsewhere'])
def test_changed_consent_or_requester_blocks_acceptance(org,change):
 r=join(org)
 if change=='policy':act('organization.policy',{'actions':['source.add']},actor=ADMIN)
 if change=='clinic':
  with db.connection(True) as c:
   row=db.get(c,TARGET);db.update(c,row,{**row['data'],'name':'Renamed'})
 if change in ('deactivate','demote'):
  with db.connection(True) as c:
   row=db.get(c,TARGET_ADMIN);db.update(c,row,{**row['data'],**({'active':False} if change=='deactivate' else {'role':'nurse'})})
 if change=='expired':
  with db.connection(True) as c:r=db.update(c,r,{**r['data'],'expires_at':'2000-01-01T00:00:00+00:00'})
 if change=='joined_elsewhere':target('organization.create',{'name':'Another parent'})
 with db.connection() as c:before=db.all_records(c,TARGET)
 err(409,lambda:approve(r))
 with db.connection() as c:assert db.all_records(c,TARGET)==before

def test_master_preview_record_count_drift_requires_new_review(org):
 r=join(org);p=checked(r)
 with db.connection(True) as c:db.record(c,'patient',TARGET,{'name':'New synthetic patient','species':'Cat'})
 err(409,lambda:approve(r,digest=p['digest']))
 assert approve(r)['data']['status']=='accepted'

@pytest.mark.parametrize('flag',[False,'true',None,1])
def test_explicit_target_access_acknowledgement_required(org,flag):
 with db.connection() as c:p=adoption.consent(c,TARGET,org['id'])
 err(409,lambda:target('organization.join_request',{'organization_id':org['id'],'digest':adoption.digest(p),'accept_access':flag,'reason':'Synthetic consent'}))
 with db.connection() as c:assert db.all_records(c,TARGET,'organization_adoption')==[]

def test_pending_request_duplicate_withdrawal_and_decline(org):
 r=join(org);err(409,lambda:join(org))
 closed=target('organization.join_cancel',{'id':r['id'],'version':r['version'],'reason':'Synthetic withdrawal'})
 assert closed['data']['status']=='withdrawn';err(409,lambda:approve(r))
 r=join(org);result=act('organization.join_review',{'id':r['id'],'version':r['version'],'decision':'declined','reason':'Synthetic decline'},actor=ADMIN)
 assert result['data']['status']=='declined'
 with db.connection() as c:assert not adoption.policy(c,TARGET)
 assert join(org)['data']['status']=='pending'

def test_exact_replay_and_competing_approval_are_atomic(org):
 r=join(org);p=checked(r);payload={'id':r['id'],'version':1,'decision':'accepted','digest':p['digest'],'accept_access':True,'reason':'Synthetic acceptance'}
 result=act('organization.join_review',payload,actor=ADMIN,key='adopt-once')
 assert act('organization.join_review',payload,actor=ADMIN,key='adopt-once')==result
 err(409,lambda:act('organization.join_review',payload,actor=ADMIN))
 with db.connection() as c:
  assert len([x for x in db.all_records(c,TARGET,'member') if '-org-master-' in x['id']])==1

@pytest.mark.parametrize('role,active',[('nurse',True),('admin',False)])
def test_existing_restricted_membership_is_not_silently_elevated(org,role,active):
 with db.connection(True) as c:
  r=db.record(c,'member',TARGET,{'name':'Synthetic existing master member','role':role,'active':active})
  c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',('synthetic-master',r['id'],TARGET))
 err(409,lambda:approve(join(org)))
 assert get(r['id'])==r

def test_existing_active_admin_membership_is_reused(org):
 with db.connection(True) as c:
  r=db.record(c,'member',TARGET,{'name':'Synthetic existing master member','role':'admin','active':True})
  c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',('synthetic-master',r['id'],TARGET))
 accepted=approve(join(org));assert accepted['data']['master_member_id']==r['id'];assert get(r['id'])==r

def test_inherited_locks_take_effect_and_master_can_switch_clinic(org,monkeypatch):
 act('organization.policy',{'actions':['message.queue']},actor=ADMIN);r=join(org);accepted=approve(r)
 err(403,lambda:target('message.queue',{'patient_id':'does-not-exist','body':'Blocked'}))
 with db.connection(True) as c:db.record(c,'owner',TARGET,{'name':'Synthetic owner'},'synthetic-owner');db.record(c,'patient',TARGET,{'name':'Synthetic pet','owner_id':'synthetic-owner'},'synthetic-pet')
 act('message.queue',{'patient_id':'synthetic-pet','body':'Synthetic draft'},clinic=TARGET,actor=accepted['data']['master_member_id'])
 monkeypatch.setenv('BROBY_AUTH_MODE','password');client=TestClient(main.app)
 assert client.post('/api/login',json={'username':'synthetic-master','password':'Synthetic-password-for-tests'}).status_code==200
 response=client.get('/api/bootstrap',headers={'x-clinic-id':TARGET});assert response.status_code==200
 assert response.json()['actor']['id']==accepted['data']['master_member_id']


def test_reads_and_mutations_are_scoped_and_non_admin_is_denied(org):
 r=join(org);client=TestClient(main.app)
 assert client.get('/api/organization/adoptions').status_code==403
 data=client.get('/api/organization/adoptions',headers={'x-actor-id':ADMIN}).json()
 assert len(data)==1 and data[0]['id']==r['id'] and 'record_counts' in data[0]
 assert 'patient' not in json_keys(data[0])
 outsider=act('member.save',{'name':'Other admin','role':'admin'},actor=ADMIN)
 err(403,lambda:act('organization.join_review',{'id':r['id'],'version':1,'decision':'declined','reason':'Unauthorized'},actor=outsider['id']))
 err(404,lambda:act('organization.join_cancel',{'id':r['id'],'version':1,'reason':'Wrong clinic'},actor=ADMIN))
 assert client.post('/api/organization/join-preview',headers={'x-clinic-id':TARGET},json={'organization_id':org['id']}).status_code==403

def json_keys(data):return set(data)-{'record_counts'}


def test_transaction_failure_does_not_leave_membership_or_clinic_link(org,monkeypatch):
 r=join(org)
 def fail(*a,**kw):raise RuntimeError('Synthetic commit-path failure')
 monkeypatch.setattr(adoption,'update',fail)
 with pytest.raises(RuntimeError):approve(r)
 with db.connection() as c:
  assert not adoption.policy(c,TARGET)
  assert not c.execute('SELECT 1 FROM auth_memberships WHERE username=? AND clinic_id=?',('synthetic-master',TARGET)).fetchone()
  assert not any('-org-master-' in m['id'] for m in db.all_records(c,TARGET,'member'))
 assert get(r['id'])==r

@pytest.mark.parametrize('value',[None,[],{},'',123,'x'*101])
def test_invalid_organization_id_is_a_validation_error(value):
 with db.connection() as c:err(422,lambda:adoption.organization(c,value))


def test_two_master_approvals_cannot_create_duplicate_memberships(org):
 r=join(org);p=checked(r);barrier=threading.Barrier(2)
 payload={'id':r['id'],'version':1,'decision':'accepted','digest':p['digest'],'accept_access':True,'reason':'Synthetic concurrent review'}
 def run():
  barrier.wait()
  try:return act('organization.join_review',payload,actor=ADMIN)['data']['status']
  except HTTPException as e:return e.status_code
 with ThreadPoolExecutor(2) as pool:result=list(pool.map(lambda _:run(),range(2)))
 assert set(result)=={'accepted',409}
 with db.connection() as c:assert c.execute('SELECT COUNT(*) FROM auth_memberships WHERE username=? AND clinic_id=?',('synthetic-master',TARGET)).fetchone()[0]==1
