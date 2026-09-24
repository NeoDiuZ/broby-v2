#!/usr/bin/env python3
"""Real-model, authenticated synthetic acceptance of the expanded assistant.

No provider send or Stripe charge occurs. Cash/refunds are synthetic bookkeeping
receipts, and the synthetic invoice is voided after its exact refund.
"""
import argparse,json,uuid
from datetime import datetime,timezone
from pathlib import Path
import httpx

p=argparse.ArgumentParser();p.add_argument('base_url');p.add_argument('--credentials',type=Path,required=True)
p.add_argument('--state',type=Path,required=True);p.add_argument('--phase',choices=['prepare','evaluate','readback'],required=True)
p.add_argument('--retry-case',action='append',default=[],help='Explicitly create a fresh model attempt for an unexecuted case; preserve the earlier response.')
a=p.parse_args();state=json.loads(a.state.read_text()) if a.state.exists() else {}

def save():a.state.write_text(json.dumps(state,indent=2));a.state.chmod(0o600)
def check(ok,label):
    assert ok,label
    print('PASS '+label,flush=True);state.setdefault('checks',[]).append({'phase':a.phase,'label':label});save()

def comparable(row):
    # The live Stripe reconciler refreshes its own verification receipt while
    # these tests run. Ignore only its polling metadata, never money, provider
    # IDs, statuses, invoice/payment records or any other business field.
    if row is None or row['kind'] not in ('stripe_checkout','stripe_refund'):return row
    row={k:v for k,v in row.items() if k not in ('version','updated_at')}
    if row['kind']=='stripe_checkout':row={**row,'data':{k:v for k,v in row['data'].items() if k!='verified_at'}}
    return row

for case in a.retry_case:
    assert a.phase=='evaluate' and case in state.get('turns',{}) and case not in state.get('executions',{}),'Retry only an existing unexecuted evaluation case'
    state.setdefault('prior_attempts',{}).setdefault(case,[]).append(state['turns'][case])
    state.setdefault('attempts',{})[case]=state.get('attempts',{}).get(case,0)+1
    save()

with httpx.Client(base_url=a.base_url.rstrip('/')+'/api/',timeout=210) as client:
    def req(method,route,expected=200,**kw):
        r=client.request(method,route,**kw)
        assert r.status_code==expected,(method,route.split('/')[0],r.status_code)
        return r.json()
    def act(name,payload):return req('POST','actions',json={'action':name,'payload':payload,'key':str(uuid.uuid4())})
    def records():return {r['id']:r for r in req('GET','bootstrap')['records']}
    def unchanged(before,after):return all(comparable(after.get(id))==comparable(row) for id,row in before.items())
    def ask(case,message,operation=None,patient=None):
        # Key is stable for interrupted-run inspection, never repeat writes blindly.
        attempt=state.get('attempts',{}).get(case,0)
        result=req('POST','assistant',json={'message':message,'patient_id':patient,'key':'completion-'+state['suffix']+'-'+case+('-'+str(attempt) if attempt else '')})
        state.setdefault('turns',{})[case]=result;save()
        if operation:check(result.get('action',{}).get('action')==operation and bool(result.get('review')),case+': real model returned the expected typed review')
        return result
    def confirm(case,expected=200):
        turn=state['turns'][case]
        result=req('POST',f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm",expected)
        if expected==200:state.setdefault('executions',{})[case]=result;save()
        return result
    def execute(case,message,operation,patient=None):
        if case in state.get('executions',{}):return state['executions'][case]
        before=records();ask(case,message,operation,patient)
        after=records()
        check(before.keys()==after.keys() and unchanged(before,after),case+': review preserves every business field (Stripe polling metadata excluded)')
        return confirm(case)
    credentials=json.loads(a.credentials.read_text())
    req('POST','login',json={k:credentials[k] for k in ('username','password')})
    if a.phase=='prepare':
        assert not state,'Preparation already exists'
        state['suffix']=uuid.uuid4().hex[:8];state['baseline']=records();save()
        suffix=state['suffix']
        state['patient']=act('patient.create',{'name':'SYNTHETIC AI completion '+suffix,'species':'Cat','owner_name':'SYNTHETIC AI owner '+suffix})['id']
        save();check(True,'isolated synthetic patient prepared with unchanged original-record baseline')
    else:
        pid=state['patient'];suffix=state['suffix']
        if a.phase=='evaluate':
            patient=execute('patient',f'Update this patient breed to "SYNTHETIC Reviewed {suffix}". Preserve all other fields.','patient.update',pid)
            check(patient['data']['breed']=='SYNTHETIC Reviewed '+suffix,'patient edit preserves exact requested breed')
            owner=execute('owner',f'Create a new owner named "SYNTHETIC Extra {suffix}" with email "synthetic-{suffix}@example.test" and blank phone. Do not send an invitation.','owner.create')
            check(owner['data']['email']==f'synthetic-{suffix}@example.test','new owner retains the supplied synthetic email')
            invoice=execute('invoice','Create an invoice for this patient with one line named "SYNTHETIC acceptance", quantity 2, price SGD 1.00 each. Discount SGD 0.00, tax rate 0 percent.','invoice.create',pid)
            check(invoice['data']['total_cents']==200,'explicit invoice prices and zero tax produce exactly 200 cents')
            payment=execute('payment',f'Record an already completed synthetic cash payment of SGD 1.00 against invoice {invoice["id"]}. This is test bookkeeping only.','payment.record',pid)
            check(payment['data']['amount_cents']==100,'synthetic external payment recorded for exact amount')
            refund=execute('refund',f'Record an already completed external refund of SGD 1.00 for payment {payment["id"]}. Reason: Synthetic acceptance complete. Use its invoice current version.','payment.refund',pid)
            check(refund['data']['amount_cents']==100,'synthetic refund offsets the exact recorded payment')
            void=execute('void',f'Void invoice {invoice["id"]}. Reason: Synthetic acceptance complete.','invoice.void',pid)
            check(void['data']['status']=='void','synthetic invoice closed without moving money')
            item=execute('inventory',f'Create inventory named "SYNTHETIC AI supply {suffix}", unit pack, opening stock 0, reorder threshold 2, unit price SGD 1.00.','inventory.create')
            receipt=execute('receive',f'Receive 3 packs into inventory {item["id"]}. Batch SYNTHETIC-{suffix}, supplier SYNTHETIC supplier. No expiry supplied and no purchase order.','inventory.receive')
            check(receipt['data']['quantity']==3,'stock receipt has exactly three units')
            adjusted=execute('adjust',f'Stocktake inventory {item["id"]} to 2 packs. Reason: Synthetic one-unit correction.','inventory.adjust')
            check(adjusted['data']['stock']==2,'stocktake reconciles exact remaining units')
            # Fresh non-overlapping dates in one deterministic time slot per fixture.
            day=10+int(suffix[:2],16)%15
            appointment=execute('appointment',f'Book this patient on 2098-11-{day:02} at 10:00 for 30 minutes with clinician clinic-east-vet. Reason: SYNTHETIC assistant acceptance. No room.','appointment.create',pid)
            moved=execute('move',f'Move appointment {appointment["id"]} to 2098-11-{day:02} at 11:00. Keep its duration, clinician and reason.','appointment.reschedule',pid)
            check(moved['data']['time']=='11:00' and moved['data']['duration']==30,'appointment reschedule preserves duration')
            cancelled=execute('cancel',f'Cancel appointment {appointment["id"]}.','appointment.update',pid)
            check(cancelled['data']['status']=='cancelled','synthetic appointment cancelled')
            template=execute('template',f'Create a template named "SYNTHETIC AI template {suffix}" with exactly two sections, "Owner report" and "Recorded findings".','template.save')
            check(template['data']['sections']==['Owner report','Recorded findings'],'template contains the exact section list')
            view=execute('dashboard',f'Save a clinic-wide dashboard named "SYNTHETIC unpaid {suffix}" showing outstanding invoices only. No date limit.','dashboard.save')
            check(view['data']['query']['kind']=='invoice' and view['data']['query']['outstanding'] is True,'saved dashboard retains the requested validated filter')
            guided=ask('guide','I want to make a refund through Stripe. Open the required provider review screen.')
            check('action' not in guided and guided.get('navigate')=='Billing','provider money workflow directs to Billing without a raw AI mutation')
            missing=ask('missing','Create an invoice for this patient for a service, but I have not decided the amount or tax. Do not guess.',patient=pid)
            check('action' not in missing,'missing amount and tax require clarification')
            turn=ask('stale','Change this patient breed to "SYNTHETIC stale proposal". Preserve everything else.','patient.update',pid)
            current=records()[pid]
            act('patient.update',{'id':pid,'version':current['version'],'breed':'SYNTHETIC concurrent edit '+suffix})
            confirm('stale',expected=409)
            check(records()[pid]['data']['breed']=='SYNTHETIC concurrent edit '+suffix,'stale saved confirmation cannot overwrite a concurrent edit')
            first=state['executions']['payment'];check(confirm('payment')==first,'payment confirmation replay returns the original receipt')
        else:
            for case,original in state.get('executions',{}).items():
                turn=state['turns'][case];saved=req('GET','assistant/conversations/'+turn['conversation_id'])['turns'][0]
                check(saved['review']==turn['review'] and saved['execution']==original,case+': exact review and result persist after a new login')
        current=records()
        check(unchanged(state['baseline'],current),'every original clinic business record is unchanged (Stripe polling metadata excluded)')
        check(req('GET','ready')['pms_store']=='postgres','deployed application remains ready on PostgreSQL')
    state[a.phase+'_verified_at']=datetime.now(timezone.utc).isoformat();save();req('POST','logout')
