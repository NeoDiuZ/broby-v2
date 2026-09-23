"""Synthetic integration contract. Deliberately contains no network send operation."""
from db import record,update,all_records,now
PERMISSIONS={'test.payment.create':{'admin'},'test.payment.callback':{'admin'},'test.payment.refund':{'admin'},'test.message.create':{'admin'},'test.message.callback':{'admin'},'test.lab.receive':{'admin'},'escalation.acknowledge':{'vet','admin'}}

def dispatch(c,a,p,clinic,actor):
    from actions import owned,require,integer,version,fail,dispatch as shared
    if a=='test.lab.receive':
        report=dict(p);report.setdefault('event_type','lab_result')
        report['actor']={'kind':'system','name':'Synthetic laboratory adapter'}
        report['body']={**report.get('body',{}),'test_mode':True}
        return shared(c,'clinical.ingest',report,clinic,actor)
    if a=='test.payment.create':
        invoice=owned(c,require(p,'invoice_id'),clinic,'invoice')
        amount=integer(p.get('amount_cents'),'Amount',1)
        from billing import outstanding
        if amount>outstanding(invoice['data']):fail('Amount exceeds the invoice balance')
        return record(c,'test_payment',clinic,{'patient_id':invoice['data']['patient_id'],'invoice_id':invoice['id'],'amount_cents':amount,'currency':'SGD','status':'pending','refunded_cents':0,'test_mode':True})
    if a=='test.payment.callback':
        r=owned(c,require(p,'id'),clinic,'test_payment');status=require(p,'status')
        if status not in ('succeeded','failed'):fail('Unsupported test payment status')
        if r['data']['status']==status:return r
        if r['data']['status']!='pending':fail('Payment is already final',409)
        return update(c,r,{**r['data'],'status':status,'provider_reference':'synthetic:'+r['id'],'completed_at':now()})
    if a=='test.payment.refund':
        r=owned(c,require(p,'id'),clinic,'test_payment');amount=integer(p.get('amount_cents'),'Refund',1)
        if r['data']['status']!='succeeded' or amount>r['data']['amount_cents']-r['data']['refunded_cents']:fail('Refund exceeds successful unrefunded payment')
        require(p,'reason')
        record(c,'test_refund',clinic,{'payment_id':r['id'],'amount_cents':amount,'reason':p['reason'],'test_mode':True})
        return update(c,r,{**r['data'],'refunded_cents':r['data']['refunded_cents']+amount})
    if a=='test.message.create':
        patient=owned(c,require(p,'patient_id'),clinic,'patient')
        return record(c,'test_message',clinic,{'patient_id':patient['id'],'body':require(p,'body'),'status':'queued','test_mode':True,'sending_enabled':False,'attempts':0})
    if a=='test.message.callback':
        r=owned(c,require(p,'id'),clinic,'test_message');status=require(p,'status');current=r['data']['status']
        states={'queued':{'accepted','failed'},'accepted':{'delivered','failed'},'delivered':{'read'},'failed':{'queued'},'read':set()}
        if status==current:return r
        if status not in states[current]:fail('Invalid or out-of-order delivery transition',409)
        attempts=r['data']['attempts']+(status=='accepted')
        if attempts>3 or current=='failed' and attempts>=3:fail('Retry limit reached',409)
        return update(c,r,{**r['data'],'status':status,'attempts':attempts,'updated_at':now()})
    if a=='escalation.acknowledge':
        r=owned(c,require(p,'id'),clinic,'escalation');version(r,p)
        return update(c,r,{**r['data'],'status':'acknowledged','acknowledged_by':actor,'acknowledged_at':now()})
    fail('Unknown test adapter action',404)

def escalate(c,clinic,patient_id,intake_id):
    """Internal attention queue only. No assertion that an external alert was delivered."""
    return record(c,'escalation',clinic,{'patient_id':patient_id,'intake_id':intake_id,'status':'needs_attention','delivery':'disabled','created_at':now()})
