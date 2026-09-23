import csv
import io
import uuid

import pytest
from fastapi.testclient import TestClient

import assistant
import assistant_history
import billing
import db
import main
import stripe_payments
from test_integrity import isolated, act, get, rows, err
from test_stripe_payments import stripe_config, provider, paid, sync


def invoice():
    return act('invoice.create', {'patient_id': 'luna', 'items': [{'name': 'Synthetic service', 'quantity': 1, 'price_cents': 1000}], 'tax_bps': 900})


def credit(inv, net=300, tax=27, key=None):
    return act('credit_note.create', {'id': inv['id'], 'version': inv['version'], 'net_cents': net, 'tax_cents': tax, 'reason': 'Synthetic correction'}, key=key)


def test_credit_keeps_original_charge_and_reduces_payable_balance_once():
    inv = invoice(); note = credit(inv, key='credit-once')
    assert credit(inv, key='credit-once') == note
    current = get(inv['id'])
    assert current['data']['total_cents'] == 1090 and billing.net_total(current['data']) == 763
    assert current['data']['paid_cents'] == 0 and current['data']['credited_tax_cents'] == 27
    assert len(rows('credit_note')) == 1 and not rows('payment') and not rows('refund')
    err(422, lambda: act('payment.record', {'id': inv['id'], 'version': current['version'], 'amount_cents': 764, 'method': 'cash'}))
    act('payment.record', {'id': inv['id'], 'version': current['version'], 'amount_cents': 763, 'method': 'cash'})
    assert get(inv['id'])['data']['status'] == 'paid'
    err(409, lambda: credit(inv))


@pytest.mark.parametrize('changes', [
    {'net_cents': True}, {'net_cents': '300'}, {'net_cents': 1.5}, {'net_cents': -1},
    {'tax_cents': 91}, {'net_cents': 1001}, {'net_cents': 0, 'tax_cents': 0},
    {'reason': ' '}, {'tax_cents': None}, {'version': True}, {'send_refund': True},
])
def test_invalid_credit_is_atomic(changes):
    inv = invoice()
    p = {'id': inv['id'], 'version': inv['version'], 'net_cents': 300, 'tax_cents': 27, 'reason': 'Synthetic'}
    err(422, lambda: act('credit_note.create', {**p, **changes}))
    assert get(inv['id']) == inv and not rows('credit_note')


def test_cumulative_net_and_tax_limits_are_independent_and_full_credit_closes():
    inv = invoice(); credit(inv, 1000, 0); current = get(inv['id'])
    err(422, lambda: credit(current, 1, 0))
    credit(current, 0, 90); current = get(inv['id'])
    assert current['data']['status'] == 'credited' and billing.outstanding(current['data']) == 0
    err(422, lambda: credit(current, 0, 1))
    err(409, lambda: act('stripe.checkout', {'invoice_id': inv['id'], 'version': current['version']}))


def test_paid_credit_shows_refund_due_until_external_refund_is_recorded():
    inv = invoice()
    payment = act('payment.record', {'id': inv['id'], 'version': inv['version'], 'amount_cents': 1090, 'method': 'cash'})
    note = credit(get(inv['id'])); current = get(inv['id'])
    assert current['data']['status'] == 'refund_due' and billing.refund_due(current['data']) == 327
    assert billing.outstanding(current['data']) == 0 and not rows('refund')
    act('payment.refund', {'id': payment['id'], 'version': current['version'], 'amount_cents': 327, 'reason': 'Synthetic refund received'})
    current = get(inv['id'])
    assert current['data']['paid_cents'] == 763 and current['data']['status'] == 'paid'
    assert get(note['id']) == note


def test_full_reversal_is_immutable_idempotent_and_reopens_charge_after_refund():
    inv = invoice(); payment = act('payment.record', {'id': inv['id'], 'version': 1, 'amount_cents': 1090, 'method': 'cash'})
    note = credit(get(inv['id'])); current = get(inv['id'])
    act('payment.refund', {'id': payment['id'], 'version': current['version'], 'amount_cents': 327, 'reason': 'Synthetic'})
    current = get(inv['id']); payload = {'id': note['id'], 'version': current['version'], 'reason': 'Reinstate original charge'}
    rev = act('credit_note.reverse', payload, key='reverse-once')
    assert act('credit_note.reverse', payload, key='reverse-once') == rev
    assert get(note['id']) == note and get(inv['id'])['data']['credited_cents'] == 0
    assert billing.outstanding(get(inv['id'])['data']) == 327
    err(409, lambda: act('credit_note.reverse', {**payload, 'version': get(inv['id'])['version']}))
    err(409, lambda: act('invoice.void', {'id': inv['id'], 'version': get(inv['id'])['version'], 'reason': 'Must preserve credit history'}))


def test_void_role_lock_and_cross_clinic_boundaries():
    inv = invoice(); p = {'id': inv['id'], 'version': 1, 'net_cents': 100, 'tax_cents': 0, 'reason': 'Synthetic'}
    err(403, lambda: act('credit_note.create', p, actor='clinic-east-nurse'))
    err(404, lambda: act('credit_note.create', p, actor='clinic-river-vet', clinic='clinic-river'))
    practice = get('clinic-east')
    act('feature_locks.save', {'version': practice['version'], 'actions': ['credit_note.create']}, actor='clinic-east-admin')
    err(403, lambda: act('credit_note.create', p))
    note = act('credit_note.create', p, actor='clinic-east-admin')
    err(403, lambda: act('credit_note.reverse', {'id': note['id'], 'version': get(inv['id'])['version'], 'reason': 'Locked'}))
    other = invoice(); act('invoice.void', {'id': other['id'], 'version': 1, 'reason': 'Synthetic'})
    err(409, lambda: act('credit_note.create', {**p, 'id': other['id'], 'version': get(other['id'])['version']}, actor='clinic-east-admin'))


def test_legacy_invoice_without_tax_breakdown_can_only_credit_net_amount():
    inv = rows('invoice')[0]
    assert 'tax_cents' not in inv['data']
    err(422, lambda: credit(inv, 0, 1))
    credit(inv, 100, 0)
    assert billing.net_total(get(inv['id'])['data']) == inv['data']['total_cents'] - 100


def test_stripe_reservation_blocks_credit_and_reversal_and_checkout_uses_net_balance(provider):
    inv = invoice(); note = credit(inv); current = get(inv['id'])
    checkout = act('stripe.checkout', {'invoice_id': inv['id'], 'version': current['version']})
    assert checkout['data']['amount_cents'] == 763
    err(409, lambda: credit(current, 100, 0))
    err(409, lambda: act('credit_note.reverse', {'id': note['id'], 'version': current['version'], 'reason': 'Race'}))
    stripe_payments.tick(); assert provider.creates[0][0]['line_items'][0]['price_data']['unit_amount'] == 763
    paid(provider, checkout); sync(checkout); sync(checkout)
    assert get(inv['id'])['data']['status'] == 'paid' and get(inv['id'])['data']['paid_cents'] == 763


def test_stripe_refund_reconciles_credit_without_reopening_paid_balance(provider):
    inv = invoice(); checkout = act('stripe.checkout', {'invoice_id': inv['id'], 'version': 1})
    stripe_payments.tick(); paid(provider, checkout); sync(checkout)
    credit(get(inv['id']))
    sync(checkout)  # A duplicate canonical payment must not erase the credit status.
    assert get(inv['id'])['data']['status'] == 'refund_due'
    act('stripe.refund', {'id': checkout['id'], 'amount_cents': 327, 'reason': 'Synthetic credit settlement'}, actor='clinic-east-admin')
    stripe_payments.tick(); sync(checkout); sync(checkout)
    current = get(inv['id'])
    assert current['data']['status'] == 'paid' and billing.refund_due(current['data']) == 0
    assert current['data']['paid_cents'] == 763 and len(rows('refund')) == 1


def test_assistant_proposes_exact_credit_and_saved_confirmation_replays(monkeypatch):
    inv = invoice(); payload = {'id': inv['id'], 'version': 1, 'net_cents': 300, 'tax_cents': 27, 'reason': 'Synthetic model credit'}
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    monkeypatch.setattr(assistant.providers, 'model_json', lambda *a: {'action': {'action': 'credit_note.create', 'payload': payload}})
    def ask(patient='luna'):
        return assistant_history.ask('clinic-east','clinic-east-vet','Issue explicitly supplied credit',patient,None,str(uuid.uuid4()))
    assert 'action' not in ask('milo')
    turn=ask(); assert get(inv['id']) == inv
    assert {'label': 'Net invoice charge after confirmation', 'value': 'SGD 7.63'} in turn['review']['fields']
    client=TestClient(main.app); path=f"/api/assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm"
    first=client.post(path); assert first.status_code == 200
    assert client.post(path).json() == first.json() and len(rows('credit_note')) == 1
    payload.pop('tax_cents'); assert 'action' not in ask()
    monkeypatch.setattr(assistant.providers, 'model_json', lambda *a: {'action': {'action': 'credit_note.reverse', 'payload': {'id': first.json()['id'], 'version': get(inv['id'])['version'], 'reason': 'Reverse synthetic credit'}}})
    reverse=ask(); assert reverse['review']['title'] == 'Reverse credit note'
    path=f"/api/assistant/conversations/{reverse['conversation_id']}/turns/{reverse['turn_id']}/confirm"
    assert client.post(path).status_code == 200 and get(inv['id'])['data']['credited_cents'] == 0


def test_outstanding_reads_and_credit_register_pdf_are_scoped(monkeypatch):
    from record_queries import select_records
    inv=invoice(); note=credit(inv,1000,90)
    with db.connection() as c:
        result=select_records(c,'clinic-east',{'kind':'invoice','outstanding':True})
        assert inv['id'] not in {r['id'] for r in result['records']}
    client=TestClient(main.app)
    assert client.get('/api/credit-notes/'+note['id']+'/pdf',headers={'x-clinic-id':'clinic-river','x-actor-id':'clinic-river-vet'}).status_code == 404
    captured=[]
    monkeypatch.setattr('exports.render',lambda title,practice,patient,content:captured.append((title,practice,patient,[x.getPlainText() for x in content])) or b'%PDF-verified-test')
    patient=get('luna'); act('patient.update',{'id':'luna','version':patient['version'],'name':'Changed later'})
    assert client.get('/api/credit-notes/'+note['id']+'/pdf').status_code == 200
    assert captured[0][2]['data']['name']=='Luna' and 'Total credit: SGD 10.90' in captured[0][3]
    assert 'Status: Issued' in captured[0][3]
    current=get(inv['id']); act('credit_note.reverse',{'id':note['id'],'version':current['version'],'reason':'=SUM(1,2)'})
    client.get('/api/credit-notes/'+note['id']+'/pdf'); assert 'Status: Reversed' in captured[1][3]
    exported=client.get('/api/credit-notes/export');assert exported.status_code==200
    register=list(csv.DictReader(io.StringIO(exported.text)))
    assert len(register)==1 and register[0]['Status']=='reversed' and register[0]['Reversal reason']=="'=SUM(1,2)"
    assert register[0]['Net credit cents']=='1000' and register[0]['Tax credit cents']=='90'
    other=client.get('/api/credit-notes/export',headers={'x-clinic-id':'clinic-river','x-actor-id':'clinic-river-vet'})
    assert list(csv.DictReader(io.StringIO(other.text)))==[]
