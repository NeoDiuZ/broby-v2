#!/usr/bin/env python3
"""Opt-in synthetic hosted credit acceptance. Never use a live-money account."""
import argparse
import csv
import io
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

p = argparse.ArgumentParser()
p.add_argument('base_url')
p.add_argument('--credentials', type=Path, required=True)
p.add_argument('--state', type=Path, required=True)
p.add_argument('--clinic', required=True)
p.add_argument('--actor', required=True)
p.add_argument('--phase', choices=['prepare', 'evaluate', 'clarify', 'planner', 'checkout', 'settle', 'readback'], required=True)
args = p.parse_args()
state = json.loads(args.state.read_text()) if args.state.exists() else {}


def persist():
    args.state.write_text(json.dumps(state, indent=2)); args.state.chmod(0o600)


def check(ok, label):
    assert ok, label
    state.setdefault('checks', []).append({'phase': args.phase, 'label': label, 'at': datetime.now(timezone.utc).isoformat()})
    persist(); print('PASS ' + label, flush=True)


with httpx.Client(base_url=args.base_url.rstrip('/') + '/api/', timeout=180) as client:
    def req(method, route, expected=200, **kwargs):
        response = client.request(method, route, **kwargs)
        assert response.status_code == expected, (method, route.split('/')[0], response.status_code)
        return response.json()

    def act(name, payload, expected=200, key=None):
        return req('POST', 'actions', expected, json={'action': name, 'payload': payload, 'key': key or str(uuid.uuid4())})

    def records():
        return {r['id']: r for r in req('GET', 'bootstrap')['records']}

    def remember(key, result):
        state[key] = result['id']; persist(); return result

    def ask(case, message):
        result = req('POST', 'assistant', json={'message': message, 'patient_id': state['patient'], 'key': 'credit-' + state['suffix'] + '-' + case})
        state.setdefault('turns', {})[case] = result; persist(); return result

    def confirm(case, expected=200):
        turn = state['turns'][case]
        return req('POST', f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm", expected)

    def wait_record(id, test):
        for _ in range(35):
            r = records()[id]
            if test(r): return r
            time.sleep(1)
        raise AssertionError('Provider reconciliation did not reach the expected state')

    req('POST', 'login', json={k: json.loads(args.credentials.read_text())[k] for k in ('username', 'password')})
    client.headers.update({'x-clinic-id': args.clinic, 'x-actor-id': args.actor})
    if args.phase == 'prepare':
        assert not state, 'Existing fixture state; do not repeat preparation'
        state.update(suffix=uuid.uuid4().hex[:8], clinic=args.clinic, actor=args.actor, synthetic_only=True)
        persist()
        patient = remember('patient', act('patient.create', {'name': 'SYNTHETIC Credits ' + state['suffix'], 'species': 'Dog', 'owner_name': 'SYNTHETIC Credit Owner'}))
        for key, amount, tax in [('manual_invoice', 1000, 900), ('browser_invoice', 1000, 900), ('stripe_invoice', 100, 0)]:
            remember(key, act('invoice.create', {'patient_id': patient['id'], 'items': [{'name': 'SYNTHETIC ' + key, 'quantity': 1, 'price_cents': amount}], 'tax_bps': tax}))
        check(req('GET', 'ready')['status'] == 'ready', 'fresh synthetic patient and three invoices created')
    else:
        assert state['clinic'] == args.clinic and state['actor'] == args.actor
        if args.phase == 'evaluate':
            assert not state.get('evaluate_started'), 'Evaluation already started; inspect saved steps before resuming'
            state['evaluate_started'] = True; persist()
            invoice = records()[state['manual_invoice']]
            payment = remember('manual_payment', act('payment.record', {'id': invoice['id'], 'version': invoice['version'], 'amount_cents': 1090, 'method': 'cash', 'reference': 'SYNTHETIC no real cash'}))
            before = records()
            turn = ask('issue', f"Issue a credit note for invoice {invoice['id']}: credit SGD 3.00 before tax and SGD 0.27 tax. Reason: SYNTHETIC service correction. Do not refund money.")
            check(turn.get('action', {}).get('action') == 'credit_note.create' and bool(turn.get('review')), 'real model proposes a reviewed credit note')
            check(records() == before, 'assistant proposal makes no financial mutation')
            check({'label': 'Refund due after confirmation', 'value': 'SGD 3.27'} in turn['review']['fields'], 'review separates refund due from cash movement')
            note = remember('manual_credit', confirm('issue'))
            check(confirm('issue') == note, 'saved credit confirmation replays exactly once')
            current = records()[invoice['id']]
            check(current['data']['status'] == 'refund_due' and current['data']['paid_cents'] == 1090 and current['data']['credited_cents'] == 327, 'credit retains cash and shows refund due')
            act('payment.refund', {'id': payment['id'], 'version': current['version'], 'amount_cents': 327, 'reason': 'SYNTHETIC recorded refund; no real cash'})
            check(records()[invoice['id']]['data']['status'] == 'paid', 'separate refund closes only the refund due')
            turn = ask('reverse', f"Reverse credit note {note['id']} in full. Reason: SYNTHETIC reversal acceptance.")
            check(turn.get('action', {}).get('action') == 'credit_note.reverse' and bool(turn.get('review')), 'real model proposes the selected full reversal')
            remember('manual_reversal', confirm('reverse'))
            current = records()[invoice['id']]
            check(current['data']['credited_cents'] == 0 and current['data']['paid_cents'] == 763 and current['data']['status'] == 'partial', 'reversal restores charge and reopens only 327 cents debt')
        if args.phase in ('evaluate', 'clarify'):
            invoice = records()[state['manual_invoice']]
            turn = ask('missing_tax', f"Issue a new credit note of SGD 1.00 for invoice {invoice['id']}. Reason: SYNTHETIC unclear tax. I have not supplied a tax allocation; ask me for it.")
            check(not turn.get('action'), 'missing explicit tax allocation requires clarification')
        elif args.phase == 'checkout':
            assert not state.get('checkout_started'), 'Checkout acceptance already started; inspect saved steps before resuming'
            state['checkout_started'] = True; persist()
            inv = records()[state['stripe_invoice']]
            remember('stripe_credit', act('credit_note.create', {'id': inv['id'], 'version': inv['version'], 'net_cents': 20, 'tax_cents': 0, 'reason': 'SYNTHETIC checkout credit'}))
            inv = records()[inv['id']]
            checkout = remember('checkout', act('stripe.checkout', {'invoice_id': inv['id'], 'version': inv['version']}))
            checkout = wait_record(checkout['id'], lambda r: r['data']['status'] == 'open')
            state['checkout_session'] = checkout['data']['session_id']; persist()
            check(checkout['data']['test_mode'] and checkout['data']['amount_cents'] == 80, 'real Stripe sandbox checkout reserves net 80 cents')
            act('credit_note.create', {'id': inv['id'], 'version': inv['version'], 'net_cents': 1, 'tax_cents': 0, 'reason': 'SYNTHETIC reservation race'}, 409)
            act('credit_note.reverse', {'id': state['stripe_credit'], 'version': inv['version'], 'reason': 'SYNTHETIC reservation race'}, 409)
            check(records()[inv['id']] == inv, 'open provider checkout blocks both credit and reversal')
        elif args.phase == 'settle':
            assert not state.get('settle_started'), 'Settlement already started; inspect saved steps before resuming'
            inv = records()[state['stripe_invoice']]
            check(inv['data']['paid_cents'] == 80 and inv['data']['status'] == 'paid', 'browser sandbox payment reconciles to net credited balance')
            state['settle_started'] = True; persist()
            remember('stripe_postpay_credit', act('credit_note.create', {'id': inv['id'], 'version': inv['version'], 'net_cents': 30, 'tax_cents': 0, 'reason': 'SYNTHETIC paid credit refund acceptance'}))
            inv = records()[inv['id']]
            check(inv['data']['status'] == 'refund_due' and inv['data']['paid_cents'] == 80, 'post-payment credit records refund due without a refund')
            refund = remember('stripe_refund', act('stripe.refund', {'id': state['checkout'], 'amount_cents': 30, 'reason': 'SYNTHETIC credit refund acceptance'}))
            inv = wait_record(inv['id'], lambda r: r['data']['paid_cents'] == 50)
            check(inv['data']['status'] == 'paid' and inv['data']['credited_cents'] == 50, 'real Stripe sandbox refund settles exactly the credit')
        elif args.phase == 'planner':
            before = records()
            attempt = state.get('planner_attempt', 0) + 1
            state.update(planner_attempt=attempt, planner_before=before); persist()
            def planner_ask(case, message):return ask('structured_' + case + '_' + str(attempt), message)
            turn = planner_ask('credit', f"Propose a credit note for invoice {state['browser_invoice']}: SGD 0.10 before tax, SGD 0.00 tax. Reason: SYNTHETIC transport review. Do not confirm it.")
            check(turn.get('action', {}).get('action') == 'credit_note.create' and bool(turn.get('review')), 'structured real model returns a reviewed credit proposal')
            turn = planner_ask('reverse', f"Propose reversing credit note {state['stripe_credit']} in full. Reason: SYNTHETIC transport review. Do not confirm it.")
            check(turn.get('action', {}).get('action') == 'credit_note.reverse' and bool(turn.get('review')), 'structured real model returns a reviewed reversal proposal')
            turn = planner_ask('read', 'Show outstanding invoices for this patient.')
            check(not turn.get('action') and state['manual_invoice'] in {r['id'] for r in turn.get('sources', [])}, 'structured real model retains invoice read behavior')
            turn = planner_ask('reminder', 'Create a reminder titled SYNTHETIC transport proposal due on 2098-08-01 for this patient. Only propose it.')
            check(turn.get('action', {}).get('action') == 'reminder.create' and bool(turn.get('review')), 'structured real model retains routine operation proposals')
            after = records(); state['planner_after'] = after; persist()
            def stable(rows):
                copy = json.loads(json.dumps(rows))
                for r in copy.values():
                    if r['kind'] == 'stripe_checkout':
                        # The existing worker refreshes these even without a payment.
                        r.pop('version', None); r.pop('updated_at', None)
                        r['data'].pop('verified_at', None)
                return copy
            check(stable(after) == stable(before), 'structured calls change no records except independent Stripe poll timestamps')
        elif args.phase == 'readback':
            rows = records(); inv = rows[state['manual_invoice']]; d = inv['data']
            check(d['total_cents'] == 1090 and d['credited_cents'] == 0 and d['paid_cents'] == 763, 'fresh session retains original invoice and reversed credit balance')
            check(rows[state['manual_credit']]['data']['amount_cents'] == 327 and rows[state['manual_reversal']]['data']['credit_note_id'] == state['manual_credit'], 'immutable original note and linked reversal persist')
            for case in ('issue', 'reverse'):
                turn = state['turns'][case]
                saved = req('GET', 'assistant/conversations/' + turn['conversation_id'])
                found = next(r for r in saved['turns'] if r['turn_id'] == turn['turn_id'])
                expected_id = state['manual_credit' if case == 'issue' else 'manual_reversal']
                check(found.get('execution', {}).get('id') == expected_id and found['review'] == turn['review'], case + ' saved review remains completed')
            response = client.get('credit-notes/export'); assert response.status_code == 200
            register = list(csv.DictReader(io.StringIO(response.text)))
            row = next(r for r in register if r['Record ID'] == state['manual_credit'])
            check(row['Status'] == 'reversed' and row['Total credit cents'] == '327', 'credit register exports original amount and reversal state')
            for key, route in [('credit', 'credit-notes/' + state['manual_credit'] + '/pdf'), ('invoice', 'invoices/' + inv['id'] + '/pdf')]:
                response = client.get(route); assert response.status_code == 200
                dest = args.state.with_name('credit-acceptance-' + key + '.pdf'); dest.write_bytes(response.content); dest.chmod(0o600)
                check(response.content.startswith(b'%PDF'), key + ' PDF downloads from stored records')
            d = rows[state['stripe_invoice']]['data']
            check(d['total_cents'] == 100 and d['credited_cents'] == 50 and d['paid_cents'] == 50 and d['status'] == 'paid', 'Stripe charge credit and verified refund remain balanced')
            check(sum(r['data']['amount_cents'] for r in rows.values() if r['kind'] == 'refund' and r['data']['invoice_id'] == state['stripe_invoice']) == 30, 'Stripe refund is recorded once')
    state[args.phase + '_verified_at'] = datetime.now(timezone.utc).isoformat(); persist()
    req('POST', 'logout')
