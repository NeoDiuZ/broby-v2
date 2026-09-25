#!/usr/bin/env python3
"""Staged, opt-in synthetic exact reads and numeric chart acceptance.

Setup only adds new marked patients and synthetic lab events to the explicitly
selected SYNTHETIC clinic. Evaluation uses the configured model but never
confirms an action. The human browser step saves the chart and opens receipts;
readback verifies persistence, not that a human actually performed those clicks.
"""
import argparse
import json
import os
import uuid
from pathlib import Path
import httpx


def check(ok,label):
    assert ok,label
    print('PASS '+label,flush=True)


def run(args,client_factory=httpx.Client):
    base=args.base_url.rstrip('/')
    state=json.loads(args.state.read_text()) if args.state.exists() else {}
    binding={'base':base,'clinic':args.clinic,'actor':args.actor}
    if state:assert all(state.get(k)==v for k,v in binding.items()),'State belongs to another target.'
    else:
        assert args.phase=='setup','Create synthetic fixtures first.'
        state={**binding,'tag':uuid.uuid4().hex[:10],'phase':'setup_started','fixtures':{}}
        args.state.parent.mkdir(parents=True,exist_ok=True)
        with os.fdopen(os.open(args.state,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:json.dump(state,f,indent=2)
    def save():
        args.state.write_text(json.dumps(state,indent=2));args.state.chmod(0o600)
    with client_factory(base_url=base+'/api/',headers={'Origin':base},timeout=210) as client:
        def req(method,path,**kwargs):
            response=client.request(method,path,**kwargs)
            assert response.status_code==200,(method,path.split('/')[0],response.status_code)
            return response.json()
        def fixture(case,action,payload):
            if case not in state['fixtures']:
                state['fixtures'][case]=req('POST','actions',json={'action':action,'payload':payload,'key':'visual-'+state['tag']+'-'+case});save()
            return state['fixtures'][case]
        credentials=json.loads(args.credentials.read_text())
        req('POST','login',json={key:credentials[key] for key in ('username','password')})
        client.headers.update({'x-clinic-id':args.clinic,'x-actor-id':args.actor})
        try:
            snapshot=req('GET','bootstrap')
            check(snapshot['clinic']['id']==args.clinic and snapshot['actor']['id']==args.actor and snapshot['clinic']['data']['name'].startswith('SYNTHETIC'),'exact synthetic clinic and actor verified')
            f=state['fixtures'];code='synthetic_trend_'+state['tag'];literal='SYNTHETIC '+state['tag']+' A%_B [literal] whole clinic today Milo'
            if args.phase=='setup':
                assert state['phase']=='setup_started','Setup already completed.'
                for case in ('patient','other-patient'):
                    fixture(case,'patient.create',{'name':'SYNTHETIC Visual '+case+' '+state['tag'],'species':'Cat','owner_name':'SYNTHETIC Visual owner '+case+' '+state['tag']})
                for case,patient,unit,value,day,low,high in [
                    ('point-0',f['patient']['id'],'mmol/L',0,10,1,3),
                    ('point-1',f['patient']['id'],'mmol/L',2,11,None,None),
                    ('point-2',f['patient']['id'],'mmol/L',4,12,1,3),
                    ('other-unit',f['patient']['id'],'mg/L',88,11,None,None),
                    ('other-patient-point',f['other-patient']['id'],'mmol/L',99,11,None,None),
                ]:
                    record=fixture(case,'test.lab.receive',{'patient_id':patient,'dedupe_key':'visual-'+state['tag']+'-'+case,'occurred_at':f'2098-07-{day:02}T01:00:00Z','summary':literal if case in ('point-0','other-patient-point') else 'SYNTHETIC visual point '+case,'body':{'text':literal if case in ('point-0','other-patient-point') else 'SYNTHETIC recorded numeric point'},'source':{'kind':'document','id':'visual-'+state['tag']+'-'+case,'page':1,'text':f'SYNTHETIC ONLY {case}: {value} {unit}; supplied range {low}–{high}. Not for clinical use.'},'observations':[{'concept':code,'name':'SYNTHETIC visual marker '+state['tag'],'value':value,'unit':unit,'ref_low':low,'ref_high':high}]})
                    state.setdefault('events',{})[case]=req('GET','v2/patients/'+patient+'/events/'+record['id']);save()
                state['phase']='setup';save()
            elif args.phase=='evaluate':
                assert state['phase'] in ('setup','evaluation_started'),'Complete setup before evaluation.'
                check(snapshot['integrations']['ai'],'configured model enabled for acceptance')
                state['phase']='evaluation_started';save()
                patient=f['patient']['id'];event=state['events']['point-0'];points=[state['events']['point-'+str(i)]['observations'][0]['id'] for i in range(3)]
                cases=[
                    ('exact-event','Show event record ID '+event['id'],{'kind':'event','patient_id':patient,'record_id':event['id']},[event['id']]),
                    ('literal-event','Show events whose text contains "'+literal+'"',{'kind':'event','patient_id':patient,'text_contains':literal},[event['id']]),
                    ('exact-point','Show observation record ID '+points[0],{'kind':'observation','patient_id':patient,'record_id':points[0]},[points[0]]),
                    ('trend',f'Plot observations whose code equals "{code}" and unit equals "mmol/L" from 2098-07-10 to 2098-07-12',{'kind':'observation','presentation':'trend','patient_id':patient,'code':code,'unit':'mmol/L','start':'2098-07-10','end':'2098-07-12'},points),
                ]
                before={r['id']:r for r in snapshot['records']}
                for case,message,expected,ids in cases:
                    answer=req('POST','assistant',json={'message':message,'patient_id':patient,'key':'visual-'+state['tag']+'-'+case})
                    state.setdefault('answers',{})[case]=answer;save()
                    check(not answer.get('action') and bool(answer.get('dashboard')),case+': factual answer without action proposal')
                    actual=dict(answer['dashboard']['query']);actual.pop('group_by',None)
                    check(actual==expected and answer['dashboard']['count']==len(ids) and set(answer['dashboard']['source_ids'])==set(ids) and {r['id'] for r in answer['sources']}==set(ids),case+': exact filters, complete count and sources')
                trend=state['answers']['trend']['dashboard']['trend'];series=trend['series']
                check(trend['concept']['code']==code and trend['concept']['unit']=='mmol/L' and [p['record_id'] for p in series]==points,'trend retains one exact recorded concept/unit and point identity')
                check([(p['value'],p['ref_low'],p['ref_high'],p['flag']) for p in series]==[(0,1,3,'low'),(2,None,None,None),(4,1,3,'high')],'trend preserves zero, missing range and supplied bounds without inference')
                for i,p in enumerate(series):
                    event=state['events']['point-'+str(i)];observation=event['observations'][0]
                    check(p['event_id']==event['id'] and p['source_id']==observation['source']['receipt_id'] and p['source']==observation['source'] and p['version']==1,'point '+str(i)+': original event/source/version identity')
                check({r['id']:r for r in req('GET','bootstrap')['records']}==before,'model reads leave all clinic records unchanged')
                state['browser']={'patient_url':base+'/app#Patient/'+patient,'conversation_id':state['answers']['trend']['conversation_id'],'turn_id':state['answers']['trend']['turn_id'],'view_name':state['answers']['trend']['dashboard']['title'],'instructions':'Open this saved trend conversation; verify three points and their supplied ranges; click a point and its source receipt; Save this view; open Reports, select it, refresh and reload. Then run readback. API readback does not attest browser clicks.'}
                state['phase']='evaluated';save()
            elif args.phase=='guides':
                assert state['phase'] in ('setup','evaluated','complete'),'Complete fixture setup first.'
                before={r['id']:r for r in snapshot['records']}
                for action,section in [('migration.preview','Data & migration'),('twilio.trial_send','Integrations'),('twilio.reconcile','Integrations'),('operations.alert.retry','Sync & jobs'),('schedule.configure','Clinic'),('organization.policy','Clinic')]:
                    answer=req('POST','assistant',json={'message':'Open the dedicated review for '+action+'. Do not propose or execute a mutation.','key':'visual-'+state['tag']+'-guide-'+action})
                    state.setdefault('guides',{})[action]=answer;save()
                    check(answer.get('navigate')=='Settings' and answer.get('navigate_section')==section and not answer.get('action'),'saved '+action+' guide routes to '+section)
                check({r['id']:r for r in req('GET','bootstrap')['records']}==before,'guide questions leave all clinic records unchanged')
            else:
                assert state['phase'] in ('evaluated','complete'),'Evaluate and complete the browser save before readback.'
                for case,answer in state['answers'].items():
                    stored=req('GET','assistant/conversations/'+answer['conversation_id'])['turns'][0]
                    check(stored.get('dashboard')==answer['dashboard'] and stored.get('sources')==answer['sources'] and not stored.get('execution'),case+': saved answer and original receipt versions survive reload')
                expected=state['answers']['trend']['dashboard']
                views=[r for r in snapshot['records'] if r['kind']=='dashboard' and not r['data'].get('archived') and r['data'].get('name')==state['browser']['view_name'] and r['data'].get('query')==expected['query']]
                check(len(views)==1,'one browser-saved exact trend view exists')
                saved=req('GET','dashboards/'+views[0]['id'])['result']
                check(saved['query']==expected['query'] and saved['count']==expected['count'] and saved['trend']==expected['trend'] and {r['id'] for r in saved['records']}==set(expected['source_ids']) and not saved['truncated'],'saved view refresh preserves full chart/count/ranges/source parity')
                for p in saved['trend']['series']:
                    receipt=req('GET','v2/sources/'+p['source_id'])
                    check(receipt['receipt_id']==p['source_id'] and receipt['id']==p['source']['id'] and 'SYNTHETIC' in receipt.get('text',''),'original synthetic point receipt remains readable')
                for action,answer in state.get('guides',{}).items():
                    stored=req('GET','assistant/conversations/'+answer['conversation_id'])['turns'][0]
                    check(stored.get('navigate_section')==answer['navigate_section'] and not stored.get('execution'),'guide '+action+' destination persists without execution')
                state['saved_view_id']=views[0]['id'];state['phase']='complete';save()
        finally:
            req('POST','logout')
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url');parser.add_argument('--credentials',required=True,type=Path)
    parser.add_argument('--state',required=True,type=Path);parser.add_argument('--clinic',required=True);parser.add_argument('--actor',required=True)
    parser.add_argument('--phase',required=True,choices=('setup','evaluate','guides','readback'))
    run(parser.parse_args())


if __name__=='__main__':main()
