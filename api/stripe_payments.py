"""Single-clinic Stripe sandbox payments with a durable, idempotent task inbox.

A browser redirect is never a receipt. Only Stripe's canonical paid session and
successful refunds change the synthetic clinic ledger. Network calls happen
outside the clinic's write transaction; tasks survive process restarts.
"""
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit

import stripe
from fastapi import APIRouter, Request
from db import connection, record, get, update, all_records, now, uid

PERMISSIONS = {'stripe.checkout': {'vet', 'admin'}, 'stripe.refresh': {'vet', 'admin'},
               'stripe.cancel': {'vet', 'admin'}, 'stripe.refund': {'admin'}}
ACTIVE = {'creating', 'open', 'cancel_requested', 'needs_review'}
router = APIRouter(prefix='/api/integrations/stripe')
API_VERSION = '2026-08-26.dahlia'


def setup(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS stripe_tasks(
      id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL, kind TEXT NOT NULL,
      resource_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
      attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
      lease_until REAL NOT NULL DEFAULT 0, token TEXT, error TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS stripe_tasks_due ON stripe_tasks(status,next_attempt,lease_until);
    CREATE TABLE IF NOT EXISTS stripe_events(
      id TEXT PRIMARY KEY, event_type TEXT NOT NULL, object_id TEXT,
      received_at TEXT NOT NULL, matched INTEGER NOT NULL);
    ''')


def configured(clinic=None):
    key = os.getenv('STRIPE_SECRET_KEY', '')
    return (os.getenv('BROBY_STRIPE_MODE') == 'test' and
            key.startswith(('sk_test_', 'rk_test_')) and
            bool(os.getenv('STRIPE_WEBHOOK_SECRET')) and
            bool(os.getenv('BROBY_STRIPE_ACCOUNT_ID')) and
            bool(os.getenv('BROBY_STRIPE_CLINIC_ID')) and
            (clinic is None or clinic == os.getenv('BROBY_STRIPE_CLINIC_ID')))


def config(clinic):
    from actions import fail
    if not configured(clinic):
        fail('Stripe test payments are not configured for this clinic', 503)
    origin = os.getenv('BROBY_PUBLIC_URL', '').rstrip('/')
    url = urlsplit(origin)
    if url.scheme != 'https' or not url.netloc or url.path or url.query or url.fragment:
        fail('Configure the public HTTPS origin before starting payments', 503)
    return origin


def client():
    # Live keys are deliberately rejected in this synthetic-data release.
    if not configured():
        raise RuntimeError('Stripe sandbox configuration is incomplete')
    return stripe.StripeClient(os.environ['STRIPE_SECRET_KEY'], stripe_version=API_VERSION,
                              stripe_account=os.environ['BROBY_STRIPE_ACCOUNT_ID'],
                              http_client=stripe.RequestsClient(timeout=15), max_network_retries=1)


def enqueue(c, clinic, kind, resource_id, key=None):
    tid = key or uid()
    c.execute('INSERT OR IGNORE INTO stripe_tasks(id,clinic_id,kind,resource_id,created_at,updated_at) VALUES(?,?,?,?,?,?)',
              (tid, clinic, kind, resource_id, now(), now()))
    return tid


def active_checkout(c, clinic, invoice_id):
    return next((r for r in all_records(c, clinic, 'stripe_checkout')
                 if r['data']['invoice_id'] == invoice_id and r['data']['status'] in ACTIVE), None)


def guard_invoice(c, clinic, invoice_id):
    from actions import fail
    if active_checkout(c, clinic, invoice_id):
        fail('An online checkout reserves this invoice. Cancel it and wait for Stripe confirmation before recording another payment or voiding.', 409)


def dispatch(c, action, p, clinic, actor):
    from actions import owned, version, fail, require, integer
    origin = config(clinic)
    if action == 'stripe.checkout':
        invoice = owned(c, require(p, 'invoice_id'), clinic, 'invoice')
        version(invoice, p)
        d = invoice['data']
        if d['status'] == 'void' or d['paid_cents'] >= d['total_cents']:
            fail('This invoice has no payable balance', 409)
        existing = active_checkout(c, clinic, invoice['id'])
        if existing:
            return existing
        currency = owned(c, clinic, clinic, 'clinic')['data'].get('currency', 'SGD').lower()
        if currency != 'sgd':
            fail('This release supports SGD clinic invoices only')
        r = record(c, 'stripe_checkout', clinic, {
            'invoice_id': invoice['id'], 'patient_id': d['patient_id'],
            'amount_cents': d['total_cents'] - d['paid_cents'], 'currency': currency,
            'invoice_number': d['number'], 'status': 'creating', 'test_mode': True,
            'account_id': os.environ['BROBY_STRIPE_ACCOUNT_ID'], 'requested_by': actor,
            'expires_at': int(time.time()) + 3600, 'return_url': origin + '/app#Billing'})
        enqueue(c, clinic, 'create', r['id'], 'create:' + r['id'])
        return r
    r = owned(c, require(p, 'id'), clinic, 'stripe_checkout')
    if action in ('stripe.refresh', 'stripe.cancel'):
        if action == 'stripe.cancel':
            if r['data']['status'] not in ACTIVE:
                fail('Only an active checkout can be cancelled', 409)
            r = update(c, r, {**r['data'], 'status': 'cancel_requested'})
            enqueue(c, clinic, 'cancel', r['id'])
        else:
            enqueue(c, clinic, 'sync' if r['data'].get('session_id') else 'create', r['id'])
        return r
    if action == 'stripe.refund':
        amount = integer(require(p, 'amount_cents'), 'Refund amount', 1)
        reason = require(p, 'reason')
        if not isinstance(reason, str) or len(reason) > 500:
            fail('Keep the refund reason under 500 characters')
        payment = get(c, payment_id(r['id']), clinic)
        if not payment:
            fail('Refresh and verify a successful Stripe payment before refunding', 409)
        requests = [v for v in all_records(c, clinic, 'stripe_refund') if v['data']['checkout_id'] == r['id']]
        reserved = sum(v['data']['amount_cents'] for v in requests if v['data']['status'] in ('queued', 'pending', 'needs_review'))
        already = sum(v['data']['amount_cents'] for v in all_records(c, clinic, 'refund') if v['data']['payment_id'] == payment['id'])
        if amount > payment['data']['amount_cents'] - already - reserved:
            fail('Refund exceeds the remaining unrefunded payment', 409)
        refund = record(c, 'stripe_refund', clinic, {
            'checkout_id': r['id'], 'invoice_id': r['data']['invoice_id'],
            'patient_id': r['data']['patient_id'], 'amount_cents': amount,
            'reason': reason, 'status': 'queued', 'requested_by': actor, 'test_mode': True})
        enqueue(c, clinic, 'refund', refund['id'], 'refund:' + refund['id'])
        return refund
    fail('Unknown Stripe action', 404)


def payment_id(checkout_id):
    return 'stripe-payment-' + checkout_id


def refund_id(provider_id):
    return 'stripe-refund-' + hashlib.sha256(provider_id.encode()).hexdigest()


def audit(c, clinic, action, resource):
    c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (uid(), clinic, 'provider:stripe', action, resource, now()))


def plain(value):
    return value.to_dict() if isinstance(value, stripe.StripeObject) else value


def checked_session(r, session):
    session = plain(session)
    d = r['data']
    if (session.get('livemode') is not False or session.get('mode') != 'payment' or
        session.get('amount_total') != d['amount_cents'] or session.get('currency') != d['currency'] or
        session.get('client_reference_id') != r['id'] or
        session.get('metadata', {}).get('broby_checkout_id') != r['id'] or
        session.get('metadata', {}).get('broby_clinic_id') != r['clinic_id'] or
        d['account_id'] != os.environ['BROBY_STRIPE_ACCOUNT_ID'] or
        (d.get('session_id') and d['session_id'] != session['id'])):
        raise ValueError('Stripe session does not match the reserved invoice')
    url = session.get('url')
    if url and (urlsplit(url).scheme != 'https' or urlsplit(url).hostname != 'checkout.stripe.com'):
        raise ValueError('Unexpected Stripe checkout URL')


def reconcile(checkout_id, session, refunds):
    """Canonical provider facts + all ledger changes commit atomically and once."""
    from actions import owned
    session = plain(session); refunds = [plain(v) for v in refunds]
    with connection(True) as c:
        r = get(c, checkout_id)
        checked_session(r, session)
        clinic = r['clinic_id']; d = r['data']
        invoice = owned(c, d['invoice_id'], clinic, 'invoice')
        data = dict(invoice['data'])
        payment = get(c, payment_id(r['id']), clinic)
        paid = session['payment_status'] == 'paid'
        payment_intent = session.get('payment_intent')
        if isinstance(payment_intent, dict):
            payment_intent = payment_intent['id']
        if paid and not payment_intent:
            raise ValueError('Paid Checkout has no payment intent')
        state = d['status']
        if paid:
            if not payment:
                # Never hide overpayments or void races as a normal paid invoice.
                if data['status'] == 'void' or d['amount_cents'] > data['total_cents'] - data['paid_cents']:
                    update(c, r, {**d, 'session_id': session['id'], 'payment_intent': payment_intent,
                                  'status': 'needs_review', 'error': 'Stripe received payment but the invoice balance changed. Reconcile this payment manually.'})
                    audit(c, clinic, 'stripe.balance_conflict', r['id'])
                    return
                payment = record(c, 'payment', clinic, {
                    'invoice_id': invoice['id'], 'patient_id': d['patient_id'],
                    'amount_cents': d['amount_cents'], 'method': 'stripe_test',
                    'reference': payment_intent, 'checkout_id': r['id'], 'test_mode': True,
                    'recorded_by': 'provider:stripe'}, payment_id(r['id']))
                data['paid_cents'] += d['amount_cents']
                audit(c, clinic, 'stripe.payment_verified', payment['id'])
            state = 'paid'
        elif not payment:
            state = 'expired' if session.get('status') == 'expired' else 'cancel_requested' if state == 'cancel_requested' else 'open'
        for refund in refunds:
            if (refund.get('payment_intent') != payment_intent or
                refund.get('currency') != d['currency'] or not isinstance(refund.get('amount'), int) or refund['amount'] <= 0):
                raise ValueError('Stripe refund does not match its payment')
            if refund.get('status') != 'succeeded':
                continue
            if not payment:
                raise ValueError('Refund arrived before its successful payment')
            rid = refund_id(refund['id'])
            if not get(c, rid, clinic):
                old = sum(v['data']['amount_cents'] for v in all_records(c, clinic, 'refund') if v['data']['payment_id'] == payment['id'])
                if old + refund['amount'] > payment['data']['amount_cents'] or refund['amount'] > data['paid_cents']:
                    raise ValueError('Refund exceeds reconciled payment')
                record(c, 'refund', clinic, {'payment_id': payment['id'], 'invoice_id': invoice['id'],
                    'patient_id': d['patient_id'], 'amount_cents': refund['amount'], 'provider_refund_id': refund['id'],
                    'reason': 'Stripe refund verified', 'recorded_by': 'provider:stripe', 'test_mode': True}, rid)
                data['paid_cents'] -= refund['amount']
                audit(c, clinic, 'stripe.refund_verified', rid)
        if payment:
            data['status'] = 'paid' if data['paid_cents'] == data['total_cents'] else 'partial' if data['paid_cents'] else 'issued'
            if data != invoice['data']:
                update(c, invoice, data)
        mapped = {v['id']: v for v in refunds}
        for request in all_records(c, clinic, 'stripe_refund'):
            if request['data']['checkout_id'] != r['id']:
                continue
            actual = mapped.get(request['data'].get('provider_refund_id'))
            if actual:
                update(c, request, {**request['data'], 'status': actual['status']})
        update(c, r, {**d, 'status': state, 'session_id': session['id'], 'payment_intent': payment_intent,
                      'checkout_url': session.get('url') or d.get('checkout_url'), 'verified_at': now(),
                      'refunded_cents': sum(v['amount'] for v in refunds if v.get('status') == 'succeeded'), 'error': None})


def provider_snapshot(capi, r, session=None):
    s = plain(session or capi.v1.checkout.sessions.retrieve(r['data']['session_id']))
    checked_session(r, s)
    refunds = []
    pi = s.get('payment_intent')
    if isinstance(pi, dict): pi = pi['id']
    if pi:
        result = capi.v1.refunds.list({'payment_intent': pi, 'limit': 100})
        if result.has_more:
            raise ValueError('Payment has more refunds than this release can reconcile automatically')
        refunds = [plain(v) for v in result.data]
    return s, refunds


def perform(task):
    """Tasks hold no database lock during provider HTTP calls."""
    from actions import authorize
    with connection() as c:
        r = get(c, task['resource_id'], task['clinic_id'])
        if not r: raise ValueError('Payment resource not found')
        if task['kind'] in ('create', 'refund'):
            authorize(c, r['clinic_id'], r['data']['requested_by'], 'stripe.checkout' if task['kind'] == 'create' else 'stripe.refund')
    capi = client()
    if task['kind'] == 'refund':
        with connection() as c: checkout = get(c, r['data']['checkout_id'], r['clinic_id'])
        if not r['data'].get('provider_refund_id'):
            # Stripe only guarantees idempotency retention for 24 hours. Never
            # blindly create a new refund after that boundary on an ambiguous task.
            if datetime.now(timezone.utc) - datetime.fromisoformat(r['created_at']) >= timedelta(hours=23):
                raise ValueError('Refund acknowledgement is too old to retry safely; reconcile in Stripe')
            result = capi.v1.refunds.create({'payment_intent': checkout['data']['payment_intent'],
                'amount': r['data']['amount_cents'], 'metadata': {'broby_refund_id': r['id']}},
                {'idempotency_key': 'broby-v2-refund-' + r['id']})
            with connection(True) as c:
                latest = get(c, r['id'], r['clinic_id'])
                # Reserve the amount until canonical reconciliation has committed
                # its ledger entry, including after a crash at this boundary.
                update(c, latest, {**latest['data'], 'provider_refund_id': result.id, 'status': 'pending'})
        s, refunds = provider_snapshot(capi, checkout)
        reconcile(checkout['id'], s, refunds)
        return
    if not r['data'].get('session_id'):
        if r['data']['expires_at'] < time.time() + 1800:
            # Don't recreate a potentially accepted checkout with a fresh amount,
            # new expiration or new idempotency key after an uncertain response.
            raise ValueError('Checkout creation acknowledgement expired; reconcile in Stripe')
        d = r['data']
        s = capi.v1.checkout.sessions.create({
            'mode': 'payment', 'payment_method_types': ['card'],
            'client_reference_id': r['id'], 'metadata': {'broby_checkout_id': r['id'], 'broby_clinic_id': r['clinic_id']},
            'payment_intent_data': {'metadata': {'broby_checkout_id': r['id'], 'broby_clinic_id': r['clinic_id']}},
            'line_items': [{'price_data': {'currency': d['currency'], 'unit_amount': d['amount_cents'],
                           'product_data': {'name': 'Broby test invoice ' + d['invoice_number']}}, 'quantity': 1}],
            'success_url': d['return_url'], 'cancel_url': d['return_url'], 'expires_at': d['expires_at']},
            {'idempotency_key': 'broby-v2-checkout-' + r['id']})
        checked_session(r, s)
        with connection(True) as c:
            latest = get(c, r['id'], r['clinic_id'])
            r = update(c, latest, {**latest['data'], 'session_id': s.id, 'checkout_url': s.url})
    s, refunds = provider_snapshot(capi, r)
    with connection() as c: latest = get(c, r['id'], r['clinic_id'])
    if latest['data']['status'] == 'cancel_requested' and s['status'] == 'open':
        try:
            capi.v1.checkout.sessions.expire(s['id'], options={'idempotency_key': 'broby-v2-expire-' + r['id']})
        except stripe.InvalidRequestError:
            # Payment and cancellation can race. Retrieve the winner, never
            # assume cancellation succeeded because the operator requested it.
            pass
        s, refunds = provider_snapshot(capi, r)
    reconcile(r['id'], s, refunds)


def run_task(task_id):
    with connection(True) as c:
        task = c.execute('SELECT * FROM stripe_tasks WHERE id=?', (task_id,)).fetchone()
        if not task or task['status'] not in ('queued', 'running') or task['lease_until'] > time.time() or task['next_attempt'] > time.time():
            return
        token = secrets.token_hex(20)
        c.execute("UPDATE stripe_tasks SET status='running',attempts=attempts+1,lease_until=?,token=?,updated_at=? WHERE id=?",
                  (time.time() + 300, token, now(), task_id))
        task = dict(task)
    try:
        perform(task)
    except Exception as exc:
        retry = isinstance(exc, (stripe.APIConnectionError, stripe.RateLimitError, stripe.APIError)) and task['attempts'] < 4
        message = 'Stripe request could not be confirmed; retry scheduled.' if retry else 'Payment needs review. Check provider configuration and refresh; the invoice ledger was not guessed.'
        with connection(True) as c:
            c.execute('UPDATE stripe_tasks SET status=?,error=?,next_attempt=?,lease_until=0,updated_at=? WHERE id=? AND token=?',
                      ('queued' if retry else 'failed', message, time.time() + min(300, 30 * 2 ** task['attempts']), now(), task_id, token))
            r = get(c, task['resource_id'], task['clinic_id'])
            if r:
                # A rejected API request has a known outcome. A timeout or 5xx
                # might already have created a payment resource: keep it reserved.
                rejected = isinstance(exc, (stripe.InvalidRequestError, stripe.AuthenticationError, stripe.PermissionError))
                terminal = 'failed' if rejected and not r['data'].get('session_id') and not r['data'].get('provider_refund_id') else 'needs_review'
                update(c, r, {**r['data'], 'error': message, **({'status': terminal} if not retry and r['data']['status'] in ('creating', 'queued') else {})})
        return
    with connection(True) as c:
        c.execute("UPDATE stripe_tasks SET status='completed',lease_until=0,error=NULL,updated_at=? WHERE id=? AND token=?", (now(), task_id, token))


def tick():
    if not configured(): return
    with connection() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM stripe_tasks WHERE status IN ('queued','running') AND next_attempt<=? AND lease_until<=? ORDER BY created_at LIMIT 10", (time.time(), time.time()))]
    for task_id in ids: run_task(task_id)


def poll():
    """Reconcile missed callbacks independently of the browser being open."""
    if not configured(): return
    clinic = os.environ['BROBY_STRIPE_CLINIC_ID']
    with connection(True) as c:
        for r in all_records(c, clinic, 'stripe_checkout'):
            # Recent paid checkouts also catch dashboard refunds and late events.
            recent = datetime.now(timezone.utc) - datetime.fromisoformat(r['created_at']) < timedelta(days=7)
            if r['data'].get('session_id') and (r['data']['status'] in ACTIVE or r['data']['status'] == 'paid' and recent):
                waiting = c.execute("SELECT 1 FROM stripe_tasks WHERE resource_id=? AND status IN ('queued','running')", (r['id'],)).fetchone()
                if not waiting: enqueue(c, clinic, 'sync', r['id'])


def loop(stop):
    last_poll = 0
    while not stop.wait(1):
        try:
            if time.monotonic() - last_poll > 60:
                poll(); last_poll = time.monotonic()
            tick()
        except Exception:
            # Durable tasks remain claimable; avoid logging credentials or payloads.
            pass


@router.post('/webhook')
async def webhook(request: Request):
    from actions import fail
    if not configured(): fail('Stripe webhook is not configured', 503)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024: fail('Stripe event exceeds 1 MB', 413)
    try:
        event = stripe.Webhook.construct_event(bytes(raw), request.headers.get('stripe-signature', ''), os.environ['STRIPE_WEBHOOK_SECRET']).to_dict()
    except (ValueError, stripe.SignatureVerificationError):
        fail('Invalid Stripe webhook signature', 400)
    if event.get('livemode') is not False or event.get('account'):
        fail('Unexpected Stripe account or live event', 400)
    supported = {'checkout.session.completed', 'checkout.session.async_payment_succeeded', 'checkout.session.async_payment_failed', 'checkout.session.expired', 'refund.created', 'refund.updated', 'refund.failed', 'charge.refunded'}
    if event['type'] not in supported: return {'received': True, 'ignored': True}
    obj = event['data']['object']
    clinic = os.environ['BROBY_STRIPE_CLINIC_ID']
    with connection(True) as c:
        if c.execute('SELECT 1 FROM stripe_events WHERE id=?', (event['id'],)).fetchone():
            return {'received': True, 'duplicate': True}
        checkout = None
        if event['type'].startswith('checkout.session.'):
            candidate = get(c, obj.get('metadata', {}).get('broby_checkout_id', ''), clinic)
            if candidate and candidate['kind'] == 'stripe_checkout': checkout = candidate
        else:
            checkout = next((r for r in all_records(c, clinic, 'stripe_checkout') if r['data'].get('payment_intent') and r['data']['payment_intent'] == obj.get('payment_intent')), None)
        c.execute('INSERT INTO stripe_events VALUES(?,?,?,?,?)', (event['id'], event['type'], obj.get('id'), now(), int(bool(checkout))))
        if checkout: enqueue(c, clinic, 'sync', checkout['id'], 'event:' + event['id'])
    return {'received': True}


@router.get('/status')
def status(request: Request):
    from main import identity
    clinic, actor = identity(request)
    from actions import owned
    with connection() as c:
        role = owned(c, actor, clinic, 'member')['data']['role']
        errors = [dict(r) for r in c.execute("SELECT id,kind,resource_id,status,attempts,error,updated_at FROM stripe_tasks WHERE clinic_id=? AND status='failed' ORDER BY updated_at DESC LIMIT 20", (clinic,))] if role == 'admin' else []
        events = c.execute('SELECT COUNT(*) FROM stripe_events WHERE matched=1').fetchone()[0] if configured(clinic) else 0
    return {'configured': configured(clinic), 'mode': 'test' if configured(clinic) else 'disabled',
            'currency': 'SGD', 'matched_events': events, 'failed_tasks': errors}
