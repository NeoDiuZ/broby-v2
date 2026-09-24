"""Authorized synthetic scheduling acceptance, with durable receipts and read-only replay.

Only prepare a new --state once. Scheduling changes touch a newly created test
member; the existing configuration is restored. All messages/providers stay idle.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import uuid
import httpx
from verification_records import stable_record

p = argparse.ArgumentParser()
p.add_argument('base_url'); p.add_argument('--credentials', required=True, type=Path)
p.add_argument('--state', required=True, type=Path); p.add_argument('--verify-only', action='store_true')
a = p.parse_args(); base = a.base_url.rstrip('/'); checks = []
if not a.verify_only and a.state.exists(): raise SystemExit('State already exists; inspect it or use --verify-only. Do not recreate fixtures.')
s = json.loads(a.state.read_text()) if a.verify_only else {'tag': uuid.uuid4().hex[:8], 'phase': 'starting'}
def save():
    a.state.parent.mkdir(parents=True, exist_ok=True)
    a.state.write_text(json.dumps(s, indent=2)); a.state.chmod(0o600)
def check(ok, message):
    if not ok: raise AssertionError(message)
    checks.append(message); print('PASS '+message, flush=True)
with httpx.Client(base_url=base+'/api/', headers={'Origin': base, 'x-clinic-id': 'clinic-east'}, timeout=60) as c:
    def req(method, path, expected=200, **kw):
        r = c.request(method, path, **kw)
        if r.status_code != expected: raise AssertionError(f'{method} API expected {expected}, received {r.status_code}')
        return r.json()
    def act(action, payload, expected=200, key=None):
        return req('POST', 'actions', expected, json={'action': action, 'payload': payload, 'key': key or str(uuid.uuid4())})
    def records(): return req('GET', 'bootstrap')['records']
    def current(id): return next(r for r in records() if r['id'] == id)
    def config(): return next((r for r in records() if r['kind'] == 'schedule'), None)
    credentials=json.loads(a.credentials.read_text())
    req('POST', 'login', json={k: credentials[k] for k in ('username','password')})
    try:
        check(req('GET','ready')['status']=='ready','both stores and file volume ready')
        if not a.verify_only:
            before = records(); s['before'] = before; save()
            m=act('member.save', {'name':'SYNTHETIC Leave '+s['tag'], 'role':'vet'}); s['member']=m['id']; save()
            patient=act('patient.create', {'name':'SYNTHETIC Scheduling '+s['tag'], 'species':'Cat','owner_name':'SYNTHETIC Scheduling Owner '+s['tag']});s['patient']=patient['id'];save()
            original=config();s['original_schedule']=original;save()
            data=deepcopy(original['data']) if original else {'rooms':[], 'availability':{}, 'date_overrides':{}, 'periods':{}}
            data.setdefault('periods',{})[m['id']]=[{'start':'2099-01-05','end':'2099-01-06','week':{'0':[{'start':'09:00','end':'17:00'}],'1':[{'start':'09:00','end':'17:00'}]},'reason':'SYNTHETIC temporary cover'}]
            conf=act('schedule.configure',{**data,'version':original['version'] if original else None})
            booking={'patient_id':patient['id'],'clinician':m['id'],'date':'2099-01-05','time':'09:00','duration':30,'reason':'SYNTHETIC scheduling acceptance'}
            appt=act('appointment.create',booking);s['appointments']=[appt['id']];save()
            r=act('leave.request',{'member_id':m['id'],'start':'2099-01-05','end':'2099-01-06','reason':'SYNTHETIC leave request'});s['leave']=r['id'];save()
            review=req('POST','schedule/leave/preview',json={'id':r['id'],'version':1})
            check([x['id'] for x in review['conflicts']]==[appt['id']],'pending leave permits booking and review exposes its conflict')
            approval={'id':r['id'],'version':1,'schedule_version':conf['version'],'decision':'approved','reason':'SYNTHETIC coverage reviewed'}
            act('leave.review',approval,409)
            check(current(r['id'])==r,'conflicted approval makes no partial change')
            act('appointment.update',{'id':appt['id'],'version':1,'status':'cancelled'})
            check(not req('POST','schedule/leave/preview',json={'id':r['id'],'version':1})['conflicts'],'cancelled booking clears review')
            later=act('appointment.create',{**booking,'time':'10:00'});s['appointments'].append(later['id']);save()
            act('leave.review',approval,409);check(True,'booking made after preview is rechecked before approval')
            act('appointment.update',{'id':later['id'],'version':1,'status':'cancelled'})
            key='synthetic-leave-'+s['tag'];approved=act('leave.review',approval,key=key)
            check(act('leave.review',approval,key=key)==approved,'approval retry returns exactly the same receipt')
            act('appointment.create',{**booking,'time':'11:00'},409)
            check(True,'approved leave blocks booking even inside the period hours')
            days=req('GET','schedule/rota',params={'start':'2099-01-05','days':3})
            own=next(x['days'] for x in days['members'] if x['id']==m['id'])
            check(own[0]['source']==own[1]['source']=='approved_leave' and own[2]['source']=='unrestricted','leave covers both inclusive dates only')
            act('leave.cancel',{'id':r['id'],'version':2,'reason':'SYNTHETIC restore planned rota'})
            act('appointment.create',{**booking,'time':'08:00'},409)
            restored=act('appointment.create',{**booking,'time':'11:00'});s['appointments'].append(restored['id']);save()
            act('appointment.update',{'id':restored['id'],'version':1,'status':'cancelled'})
            check(True,'withdrawal restores period restrictions and valid booking hours')
            fresh=config(); restore=original['data'] if original else {'rooms':[], 'availability':{}, 'date_overrides':{}, 'periods':{}}
            saved=act('schedule.configure',{**restore,'version':fresh['version']})
            s['restored_schedule']=saved;save()
            member=current(m['id']);act('member.save',{'id':m['id'],'version':member['version'],'name':member['data']['name'],'role':'vet','active':False})
            s['phase']='complete';save()
        check(s['phase']=='complete','test fixture finished without leaving active bookings')
        leave=current(s['leave'])
        check(leave['data']['status']=='cancelled' and [h['status'] for h in leave['data']['history']]==['pending','approved','cancelled'],'complete decision history survives fresh reads')
        check(all(current(id)['data']['status']=='cancelled' for id in s['appointments']),'all synthetic test bookings cancelled')
        check(current(s['member'])['data']['active'] is False,'test-only clinician deactivated')
        restored=config()
        check(restored['data']==s['restored_schedule']['data'],'original clinic rota restored')
        after={r['id']:r for r in records()};before=s['before'];old_schedule=s.get('original_schedule')
        others=[r for r in before if not old_schedule or r['id']!=old_schedule['id']]
        check(all(stable_record(after.get(r['id']))==stable_record(r) for r in others),f'all {len(others)} unrelated existing records retain their content and balances')
        refreshed=sum(after.get(r['id'])!=r for r in others)
        print(f'INFO {refreshed} records have only independently refreshed Stripe verification metadata')
        with httpx.Client(base_url=base+'/api/',timeout=30) as anonymous:
            check(anonymous.post('schedule/leave/preview',json={'id':s['leave'],'version':leave['version']}).status_code==401,'unauthenticated leave review denied')
        s['checks']=checks;save();print(f'{len(checks)} scheduling acceptance checks passed.')
    finally:
        c.post('logout')
