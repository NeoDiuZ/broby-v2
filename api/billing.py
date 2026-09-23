"""Append-only credit notes; original invoice charges and cash movements stay separate."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from db import all_records, get, record, update, event

PERMISSIONS = {'credit_note.create': {'vet', 'admin'}, 'credit_note.reverse': {'vet', 'admin'}}


def net_total(data):
    return 0 if data['status'] == 'void' else data['total_cents'] - data.get('credited_cents', 0)


def outstanding(data):
    return 0 if data['status'] == 'void' else max(0, net_total(data) - data['paid_cents'])


def refund_due(data):
    return 0 if data['status'] == 'void' else max(0, data['paid_cents'] - net_total(data))


def invoice_status(data):
    if data['status'] == 'void':
        return 'void'
    if refund_due(data):
        return 'refund_due'
    if net_total(data) == 0 and data.get('credited_cents'):
        return 'credited'
    if data['paid_cents'] == net_total(data):
        return 'paid'
    return 'partial' if data['paid_cents'] else 'issued'


class CreditTarget(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', str_strip_whitespace=True)
    id: Annotated[str, Field(min_length=1, max_length=200)]
    version: Annotated[int, Field(ge=1, description='Current invoice version, including when reversing a credit note.')]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class CreditCreate(CreditTarget):
    net_cents: Annotated[int, Field(ge=0, description='Explicit credit before tax, in integer cents.')]
    tax_cents: Annotated[int, Field(ge=0, description='Explicit tax credit in integer cents; do not infer tax treatment.')]


def preview(c, clinic, action, payload):
    """Pure validation reused by the executor and assistant proposal preparation."""
    from actions import owned, fail, version
    from stripe_payments import guard_invoice
    try:
        p = (CreditCreate if action == 'credit_note.create' else CreditTarget).model_validate(payload).model_dump()
    except ValidationError as error:
        fields = ', '.join(sorted({'.'.join(map(str, e['loc'])) for e in error.errors()}))
        fail('Check the required credit fields and types: ' + fields)
    credit = None
    if action == 'credit_note.reverse':
        credit = owned(c, p['id'], clinic, 'credit_note')
        invoice = owned(c, credit['data']['invoice_id'], clinic, 'invoice')
        if any(r['data']['credit_note_id'] == credit['id'] for r in all_records(c, clinic, 'credit_note_reversal')):
            fail('This credit note has already been reversed', 409)
        net, tax = credit['data']['net_cents'], credit['data']['tax_cents']
    else:
        invoice = owned(c, p['id'], clinic, 'invoice')
        net, tax = p['net_cents'], p['tax_cents']
    version(invoice, p)
    d = invoice['data']
    if d['status'] == 'void':
        fail('A void invoice cannot receive credit changes', 409)
    guard_invoice(c, clinic, invoice['id'])
    if net + tax <= 0:
        fail('A credit note must contain a positive amount')
    credited = d.get('credited_cents', 0); credited_tax = d.get('credited_tax_cents', 0)
    if action == 'credit_note.create':
        if net > d['total_cents'] - d.get('tax_cents', 0) - (credited - credited_tax):
            fail('Net credit exceeds the remaining invoice charge before tax')
        if tax > d.get('tax_cents', 0) - credited_tax:
            fail('Tax credit exceeds the remaining recorded invoice tax')
    elif net + tax > credited or tax > credited_tax or net > credited - credited_tax:
        fail('Invoice credit totals need reconciliation before reversal', 409)
    sign = 1 if action == 'credit_note.create' else -1
    changed = {**d, 'credited_cents': credited + sign * (net + tax), 'credited_tax_cents': credited_tax + sign * tax}
    changed['status'] = invoice_status(changed)
    return p, invoice, credit, changed, net, tax


def dispatch(c, action, payload, clinic, actor):
    p, invoice, credit, changed, net, tax = preview(c, clinic, action, payload)
    d = invoice['data']
    common = {'invoice_id': invoice['id'], 'invoice_number': d['number'], 'patient_id': d['patient_id'],
              'net_cents': net, 'tax_cents': tax, 'amount_cents': net + tax,
              'reason': p['reason'], 'recorded_by': actor, 'invoice_total_cents': d['total_cents']}
    if action == 'credit_note.create':
        patient = get(c, d['patient_id'], clinic); owner = get(c, patient['data']['owner_id'], clinic)
        common.update(number='CN-' + str(1001 + len(all_records(c, clinic, 'credit_note'))),
                      clinic_name=get(c, clinic, clinic)['data']['name'], patient_name=patient['data']['name'],
                      patient_species=patient['data']['species'], owner_name=owner['data']['name'])
        result = record(c, 'credit_note', clinic, common)
        title = 'Credit note ' + common['number']
    else:
        result = record(c, 'credit_note_reversal', clinic, {**common, 'credit_note_id': credit['id'], 'credit_number': credit['data']['number']})
        title = 'Credit note reversed · ' + credit['data']['number']
    update(c, invoice, changed)
    event(c, clinic, d['patient_id'], 'invoice', title, f"{d['number']} · SGD {(net + tax)/100:.2f} · {p['reason']} · No payment or refund processed.")
    return result
