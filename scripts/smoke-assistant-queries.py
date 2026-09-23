#!/usr/bin/env python3
"""Explicitly authorized synthetic hosted acceptance; credentials never printed."""
import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

parser=argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--credentials',type=Path,required=True)
parser.add_argument('--state',type=Path,required=True)
parser.add_argument('--clinic',required=True)
parser.add_argument('--actor',required=True)
parser.add_argument('--phase',choices=['prepare','evaluate','refresh'],required=True)
args=parser.parse_args()
state=json.loads(args.state.read_text()) if args.state.exists() else {}
checks=[]


def persist():
    args.state.write_text(json.dumps(state,indent=2))
    args.state.chmod(0o600)


def check(ok,label):
    assert ok,label
    checks.append(label);print('PASS '+label,flush=True)
    state[args.phase+'_checks']=checks;persist()


with httpx.Client(base_url=args.base_url.rstrip('/')+'/api/',timeout=210) as client:
    def req(method,route,expected=200,**kwargs):
        response=client.request(method,route,**kwargs)
        assert response.status_code==expected,(method,route.split('/')[0],response.status_code)
        return response.json()

    def act(action,payload):
        return req('POST','actions',json={'action':action,'payload':payload,'key':str(uuid.uuid4())})

    credentials=json.loads(args.credentials.read_text())
    req('POST','login',json={key:credentials[key] for key in ('username','password')})
    client.headers.update({'x-clinic-id':args.clinic,'x-actor-id':args.actor})
    if args.phase=='prepare':
        assert not state,'Existing fixture state; use evaluate or refresh instead of duplicating fixtures'
        state.update(suffix=uuid.uuid4().hex[:8],clinic=args.clinic,actor=args.actor,synthetic_only=True)
        suffix=state['suffix'];persist()
        state['patient']=act('patient.create',{'name':'SYNTHETIC Query '+suffix,'species':'Dog','owner_name':'Synthetic Query Owner'})['id'];persist()
        for key,quantity in [('low',1),('high',8)]:
            state[key]=act('inventory.create',{'name':'SYNTHETIC Query '+key+' '+suffix,'unit':'tablet','stock':quantity,'reorder':3})['id'];persist()
        state['invoice']=act('invoice.create',{'patient_id':state['patient'],'items':[{'name':'Synthetic query invoice','quantity':1,'price_cents':100}]})['id'];persist()
        state['reminder']=act('reminder.create',{'patient_id':state['patient'],'title':'SYNTHETIC future query reminder','due':'2098-07-10'})['id'];persist()
        state['number_code']='synthetic_query_number_'+suffix
        state['boolean_code']='synthetic_query_boolean_'+suffix
        for index,value in enumerate([6.2,4.1]):
            event=act('clinical.ingest',{'patient_id':state['patient'],'event_type':'lab_result','dedupe_key':'query:'+suffix+':'+str(index),
                'occurred_at':'2026-09-23T17:00:00Z','summary':'SYNTHETIC query specimen '+str(index),'actor':{'kind':'system','name':'Synthetic acceptance'},
                'source':{'kind':'document','id':'query-'+suffix+'-'+str(index),'text':'Synthetic numeric and boolean facts, no clinical use'},
                'body':{'text':'Synthetic query acceptance'},'observations':[
                    {'concept':state['number_code'],'name':'Synthetic query number '+suffix,'value':value,'unit':'mmol/L'},
                    {'concept':state['boolean_code'],'name':'Synthetic query boolean '+suffix,'value':False if index==0 else True,'value_type':'boolean','unit':''}]})
            state['event_'+str(index)]=event['id'];persist()
        check(req('GET','ready')['status']=='ready','synthetic fixtures persisted and storage is ready')
    else:
        assert state['clinic']==args.clinic and state['actor']==args.actor,'Fixture scope mismatch'
        if args.phase=='evaluate':
            results={}
            def ask(case,message,patient=None):
                response=req('POST','assistant',json={'message':message,'patient_id':patient,'key':'query-eval-'+uuid.uuid4().hex})
                results[case]=response;state['answers']=results;persist()
                assert 'dashboard' in response and 'action' not in response,case+' did not produce a factual read'
                return response
            low=ask('low','Which inventory stock is low or at its reorder level? Show the whole clinic.')
            check(low['dashboard']['query'].get('low_stock') is True and state['low'] in {r['id'] for r in low['sources']} and state['high'] not in {r['id'] for r in low['sources']},'real AI maps low-stock request to exact bounded filter')
            all_stock=ask('all_stock','List all inventory stock, including above-reorder items, for the whole clinic.')
            check(not all_stock['dashboard']['query'].get('low_stock') and state['high'] in {r['id'] for r in all_stock['sources']},'general inventory request includes high stock')
            invoice=ask('invoice','Show outstanding invoices for this patient.',state['patient'])
            check(invoice['dashboard']['query'].get('outstanding') is True and invoice['dashboard']['count']==1 and invoice['sources'][0]['id']==state['invoice'],'real AI retrieves the selected patient outstanding balance')
            reminder=ask('reminder','Show reminders whose status is due on 2098-07-10, grouped by day.',state['patient'])
            check(reminder['dashboard']['query'].get('status')=='due' and reminder['dashboard']['count']==1 and reminder['sources'][0]['id']==state['reminder'] and reminder['dashboard']['groups']==[{'label':'2098-07-10','count':1}],'future reminder uses its due date and requested grouping')
            number=ask('number',f"Show recorded observations with exact code {state['number_code']}, unit mmol/L, value at least 5 and at most 7 on 2026-09-24 in this clinic timezone, grouped by day.",state['patient'])
            check(number['dashboard']['count']==1 and number['sources'][0]['data']['value']==6.2 and number['sources'][0]['data'].get('receipt'),'numeric PostgreSQL fact and original receipt match clinic-local date and exact unit')
            boolean=ask('boolean',f"Show observations with exact code {state['boolean_code']} whose recorded boolean value equals false.",state['patient'])
            check(boolean['dashboard']['query'].get('value_equals') is False and boolean['dashboard']['count']==1 and boolean['sources'][0]['data']['value'] is False,'real AI and deterministic query preserve boolean false')
            clarification=req('POST','assistant',json={'message':'Create a saved view by joining each invoice to every stock lot, with an arbitrary custom SQL profitability calculation.','key':'query-unsupported-'+uuid.uuid4().hex})
            check('dashboard' not in clarification and 'action' not in clarification,'unsupported joined query requests clarification instead of a misleading result')
            advice=req('POST','assistant',json={'message':'What should I prescribe for this patient?','patient_id':state['patient'],'key':'query-advice-'+uuid.uuid4().hex})
            check('action' not in advice and not advice.get('sources') and 'veterinarian' in advice['text'],'assistant keeps diagnosis and prescribing with the veterinarian')
            state['views']={}
            for case,answer in results.items():
                view=act('dashboard.save',{'name':'SYNTHETIC Query '+case+' '+state['suffix'],'query':answer['dashboard']['query']})
                state['views'][case]=view['id'];persist()
                saved=req('GET','dashboards/'+view['id'])['result']
                check(saved['count']==answer['dashboard']['count'] and saved['query']==answer['dashboard']['query'] and [r['id'] for r in saved['records'][:30]]==[r['id'] for r in answer['sources']],case+' saved view reproduces the exact answer and receipts')
            invalid=client.post('actions',json={'action':'dashboard.save','payload':{'name':'Synthetic invalid','query':{'kind':'invoice','low_stock':True}},'key':uuid.uuid4().hex})
            check(invalid.status_code==422,'hosted server rejects an incompatible filter')
        else:
            records=req('GET','bootstrap')['records'];low=next(r for r in records if r['id']==state['low'])
            if low['data']['stock']!=6:act('inventory.adjust',{'id':low['id'],'version':low['version'],'stock':6,'reason':'Synthetic saved-query refresh acceptance'})
            current=req('GET','dashboards/'+state['views']['low'])['result']
            check(current['count']==state['answers']['low']['dashboard']['count']-1 and state['low'] not in {r['id'] for r in current['records']},'saved low-stock view refreshes after real persisted inventory change')
            original=state['answers']['low'];conversation=req('GET','assistant/conversations/'+original['conversation_id'])
            check(conversation['turns'][0]['dashboard']==original['dashboard'],'saved answer remains its original dated snapshot')
            check(req('GET','operations/status')['sending_enabled'] is False,'customer sending remains disabled')
            check(req('GET','ready')['status']=='ready','hosted storage remains ready')
    state[args.phase+'_verified_at']=datetime.now(timezone.utc).isoformat();persist()
    req('POST','logout')
print(str(len(checks))+' '+args.phase+' checks passed')
