"""Ledger acceptance under retries, signatures, races and provider failures."""
import copy
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
import pytest
import stripe
from fastapi.testclient import TestClient
import db, main, stripe_payments as payments
from test_integrity import isolated, act, get, rows, err


class Object(dict):
    def __getattr__(self, name):
        try: return self[name]
        except KeyError as e: raise AttributeError(name) from e


@pytest.fixture(autouse=True)
def stripe_config(monkeypatch):
    for key,value in {'STRIPE_SECRET_KEY':'sk_test_synthetic','STRIPE_WEBHOOK_SECRET':'whsec_synthetic',
        'BROBY_STRIPE_MODE':'test','BROBY_STRIPE_ACCOUNT_ID':'acct_synthetic',
        'BROBY_STRIPE_CLINIC_ID':'clinic-east','BROBY_PUBLIC_URL':'https://broby.example.test'}.items():
        monkeypatch.setenv(key,value)


@pytest.fixture
def provider(monkeypatch):
    sessions={}; refunds=[]; creates=[]; refund_creates=[]
    def create(params,options):
        creates.append((copy.deepcopy(params),copy.deepcopy(options)))
        key=options['idempotency_key']
        if key not in sessions:
            sessions[key]=Object(id='cs_test_'+params['client_reference_id'],mode='payment',livemode=False,
                amount_total=params['line_items'][0]['price_data']['unit_amount'],currency='sgd',
                metadata=params['metadata'],client_reference_id=params['client_reference_id'],
                status='open',payment_status='unpaid',payment_intent=None,url='https://checkout.stripe.com/test')
        return copy.deepcopy(sessions[key])
    def retrieve(sid):return copy.deepcopy(next(v for v in sessions.values() if v.id==sid))
    def expire(sid,**kwargs):
        s=next(v for v in sessions.values() if v.id==sid);s.status='expired';s['status']='expired'
        return copy.deepcopy(s)
    def refund(params,options):
        refund_creates.append(options['idempotency_key'])
        existing=next((r for r in refunds if r.get('key')==options['idempotency_key']),None)
        if existing:return existing
        r=Object(id='re_test_'+str(len(refunds)),status='succeeded',currency='sgd',amount=params['amount'],
                 payment_intent=params['payment_intent'],key=options['idempotency_key'])
        refunds.append(r);return r
    capi=SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create=create,retrieve=retrieve,expire=expire)),
          refunds=SimpleNamespace(create=refund,list=lambda p:Object(data=[r for r in refunds if r['payment_intent']==p['payment_intent']],has_more=False))))
    monkeypatch.setattr(payments,'client',lambda:capi)
    return SimpleNamespace(client=capi,sessions=sessions,refunds=refunds,creates=creates,refund_creates=refund_creates)


def checkout():
    invoice=act('invoice.create',{'patient_id':'luna','items':[{'name':'Synthetic service','quantity':1,'price_cents':1200}]})
    return invoice,act('stripe.checkout',{'invoice_id':invoice['id'],'version':invoice['version']})


def sync(r):
    act('stripe.refresh',{'id':r['id']});payments.tick()


def paid(provider,r):
    s=provider.sessions['broby-v2-checkout-'+r['id']]
    s.update(status='complete',payment_status='paid',payment_intent='pi_test_'+r['id'],url=None)
    return s


def test_server_balance_reservation_idempotency_and_role(provider):
    invoice,r=checkout();same=act('stripe.checkout',{'invoice_id':invoice['id'],'version':1})
    assert same['id']==r['id']
    err(409,lambda:act('payment.record',{'id':invoice['id'],'version':1,'amount_cents':1200,'method':'cash'}))
    err(409,lambda:act('invoice.void',{'id':invoice['id'],'version':1,'reason':'race'}))
    err(403,lambda:act('stripe.checkout',{'invoice_id':invoice['id'],'version':1},actor='clinic-east-nurse'))
    err(503,lambda:act('stripe.checkout',{'invoice_id':invoice['id'],'version':1},actor='clinic-river-admin',clinic='clinic-river'))
    payments.tick();sync(r)
    assert len(provider.creates)==1
    assert provider.creates[0][0]['line_items'][0]['price_data']['unit_amount']==1200
    assert get(invoice['id'])['data']['paid_cents']==0


def test_paid_duplicate_and_refund_exactly_once(provider):
    invoice,r=checkout();payments.tick();paid(provider,r);sync(r);sync(r)
    assert get(invoice['id'])['data']['paid_cents']==1200 and len(rows('payment'))==1
    err(409,lambda:act('payment.refund',{'id':rows('payment')[0]['id'],'version':get(invoice['id'])['version'],'amount_cents':100,'reason':'manual'}))
    rr=act('stripe.refund',{'id':r['id'],'amount_cents':400,'reason':'Synthetic refund'},actor='clinic-east-admin',key='refund-idempotency')
    act('stripe.refund',{'id':r['id'],'amount_cents':400,'reason':'Synthetic refund'},actor='clinic-east-admin',key='refund-idempotency')
    err(409,lambda:act('stripe.refund',{'id':r['id'],'amount_cents':900,'reason':'too much'},actor='clinic-east-admin'))
    payments.tick();sync(r);sync(r)
    assert get(invoice['id'])['data']['paid_cents']==800 and len(rows('refund'))==1
    assert get(rr['id'])['data']['status']=='succeeded'
    assert len(provider.refund_creates)==1


def test_pending_and_failed_refunds_do_not_reduce_invoice(provider):
    invoice,r=checkout();payments.tick();paid(provider,r);sync(r)
    provider.refunds.append(Object(id='re_external',payment_intent='pi_test_'+r['id'],amount=1200,currency='sgd',status='pending'))
    sync(r);assert get(invoice['id'])['data']['paid_cents']==1200
    provider.refunds[0]['status']='failed';sync(r);assert get(invoice['id'])['data']['paid_cents']==1200
    provider.refunds[0]['status']='succeeded';sync(r)
    assert get(invoice['id'])['data']['paid_cents']==0 and get(invoice['id'])['data']['status']=='issued'


def test_cancel_waits_for_provider_and_releases_balance(provider):
    invoice,r=checkout();payments.tick();act('stripe.cancel',{'id':r['id']})
    err(409,lambda:act('payment.record',{'id':invoice['id'],'version':1,'amount_cents':1200,'method':'cash'}))
    payments.tick();assert get(r['id'])['data']['status']=='expired'
    act('payment.record',{'id':invoice['id'],'version':1,'amount_cents':1200,'method':'cash'})


def test_payment_wins_cancel_race(provider):
    invoice,r=checkout();payments.tick();paid(provider,r);act('stripe.cancel',{'id':r['id']});payments.tick()
    assert get(r['id'])['data']['status']=='paid' and get(invoice['id'])['data']['paid_cents']==1200


@pytest.mark.parametrize('field,value',[('amount_total',9999),('currency','usd'),('livemode',True),('client_reference_id','foreign')])
def test_wrong_provider_facts_never_mark_paid(provider,field,value):
    invoice,r=checkout();payments.tick();s=paid(provider,r);s[field]=value;sync(r)
    assert get(invoice['id'])['data']['paid_cents']==0 and not rows('payment')
    with db.connection() as c:assert c.execute("SELECT COUNT(*) FROM stripe_tasks WHERE status='failed'").fetchone()[0]


def test_provider_timeout_retries_same_checkout_key(provider,monkeypatch):
    invoice,r=checkout();original=provider.client.v1.checkout.sessions.create
    def uncertain(p,o):original(p,o);raise stripe.APIConnectionError('Synthetic lost acknowledgement')
    monkeypatch.setattr(provider.client.v1.checkout.sessions,'create',uncertain)
    payments.tick();assert get(invoice['id'])['data']['paid_cents']==0
    monkeypatch.setattr(provider.client.v1.checkout.sessions,'create',original)
    with db.connection(True) as c:c.execute('UPDATE stripe_tasks SET next_attempt=0')
    payments.tick()
    assert len(provider.sessions)==1 and len(provider.creates)==2
    assert provider.creates[0]==provider.creates[1]


def send_webhook(body,timestamp=None,signature=True):
    raw=json.dumps(body).encode();timestamp=int(time.time()) if timestamp is None else timestamp
    digest=hmac.new(b'whsec_synthetic',str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return TestClient(main.app).post('/api/integrations/stripe/webhook',content=raw,headers={'stripe-signature':f't={timestamp},v1={digest if signature else "incorrect"}'})


def webhook_body(r,id='evt_test_1'):
    return {'id':id,'object':'event','type':'checkout.session.completed','livemode':False,
            'data':{'object':{'id':'cs_test_'+r['id'],'metadata':{'broby_checkout_id':r['id']}}}}


def test_signed_durable_callback_duplicate_and_no_redirect_receipt(provider):
    invoice,r=checkout();payments.tick();body=webhook_body(r)
    assert send_webhook(body,signature=False).status_code==400
    assert send_webhook(body,timestamp=int(time.time())-1000).status_code==400
    assert send_webhook({**body,'livemode':True}).status_code==400
    assert send_webhook(body).status_code==200
    assert send_webhook(body).json()['duplicate'] is True
    # A signed event saying 'completed' is still not proof of paid status.
    payments.tick();assert get(invoice['id'])['data']['paid_cents']==0
    paid(provider,r)
    assert send_webhook(webhook_body(r,'evt_test_2')).status_code==200
    payments.tick();assert get(invoice['id'])['data']['paid_cents']==1200
    with db.connection() as c:assert c.execute('SELECT COUNT(*) FROM stripe_events').fetchone()[0]==2


def test_live_key_rejected_and_unsigned_status_private(monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_live_must_not_work')
    assert payments.configured() is False
    err(503,lambda:checkout())


def test_lease_recovery_and_dashboard_refund(provider):
    invoice,r=checkout()
    with db.connection(True) as c:c.execute("UPDATE stripe_tasks SET status='running',lease_until=?",(time.time()+10,))
    payments.tick();assert not provider.creates
    with db.connection(True) as c:c.execute('UPDATE stripe_tasks SET lease_until=0')
    payments.tick();paid(provider,r);payments.poll();payments.tick()
    assert get(invoice['id'])['data']['paid_cents']==1200
    provider.refunds.append(Object(id='re_dashboard',payment_intent='pi_test_'+r['id'],amount=200,currency='sgd',status='succeeded'))
    payments.poll();payments.tick();assert get(invoice['id'])['data']['paid_cents']==1000


def test_actual_sdk_objects_and_late_webhook_use_canonical_state(provider):
    invoice,r=checkout();payments.tick();s=paid(provider,r)
    actual=stripe.checkout.Session.construct_from(dict(s),'sk_test_synthetic')
    payments.reconcile(r['id'],actual,[])
    assert get(invoice['id'])['data']['paid_cents']==1200
    late=webhook_body(r,'evt_expired_late');late['type']='checkout.session.expired'
    assert send_webhook(late).status_code==200
    payments.tick();assert get(r['id'])['data']['status']=='paid'


def test_refund_lost_ack_reuses_key_and_reservation(provider,monkeypatch):
    invoice,r=checkout();payments.tick();paid(provider,r);sync(r)
    req=act('stripe.refund',{'id':r['id'],'amount_cents':1200,'reason':'Synthetic interrupted refund'},actor='clinic-east-admin')
    original=provider.client.v1.refunds.create
    def uncertain(p,o):original(p,o);raise stripe.APIConnectionError('Synthetic refund acknowledgement lost')
    monkeypatch.setattr(provider.client.v1.refunds,'create',uncertain)
    payments.tick()
    err(409,lambda:act('stripe.refund',{'id':r['id'],'amount_cents':1,'reason':'Duplicate'},actor='clinic-east-admin'))
    monkeypatch.setattr(provider.client.v1.refunds,'create',original)
    with db.connection(True) as c:c.execute('UPDATE stripe_tasks SET next_attempt=0')
    payments.tick();sync(r)
    assert len(provider.refunds)==1 and len(rows('refund'))==1
    assert provider.refund_creates[0]==provider.refund_creates[1]
    assert get(invoice['id'])['data']['paid_cents']==0
    assert get(req['id'])['data']['status']=='succeeded'


def test_permission_revocation_before_network_call(provider):
    invoice,r=checkout()
    member=get('clinic-east-vet')
    with db.connection(True) as c:db.update(c,member,{**member['data'],'active':False})
    payments.tick();assert not provider.creates
    assert get(invoice['id'])['data']['paid_cents']==0


def test_refund_record_catches_up_after_crash(provider,monkeypatch):
    invoice,r=checkout();payments.tick();paid(provider,r);sync(r)
    req=act('stripe.refund',{'id':r['id'],'amount_cents':1200,'reason':'Synthetic DB acknowledgement failure'},actor='clinic-east-admin')
    original=payments.reconcile
    def unavailable(*a):raise stripe.APIConnectionError('Temporary synthetic failure')
    monkeypatch.setattr(payments,'reconcile',unavailable);payments.tick()
    assert get(req['id'])['data']['status']=='pending'
    err(409,lambda:act('stripe.refund',{'id':r['id'],'amount_cents':1,'reason':'Duplicate'},actor='clinic-east-admin'))
    monkeypatch.setattr(payments,'reconcile',original)
    with db.connection(True) as c:c.execute('UPDATE stripe_tasks SET next_attempt=0')
    payments.tick()
    assert get(invoice['id'])['data']['paid_cents']==0 and len(provider.refund_creates)==1
