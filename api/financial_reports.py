"""Recorded financial movements, with dated voids and explicit reconciliation gaps.

This is a source register, not a general ledger or bank/Stripe settlement report.
All existing billing writers use SGD and integer cents. Never infer tax or backdate
provider cash to a payment-intent creation time.
"""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query, Request, Response
from actions import fail, owned
from db import connection, get, now, unpack

router = APIRouter(prefix='/api/reports/financial')
KINDS = ('invoice', 'payment', 'refund', 'credit_note', 'credit_note_reversal', 'invoice_void')
MAX_RECORDS = 50000


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    return result.astimezone(timezone.utc)


def cents(value):
    if type(value) is not int or not 0 <= value <= 10**14:
        raise ValueError('Expected nonnegative integer cents')
    return value


def build(c, clinic, start, end):
    practice = get(c, clinic, clinic)
    if practice['data'].get('currency', 'SGD') != 'SGD':
        fail('This register supports the current SGD billing records only', 409)
    try:
        zone = ZoneInfo(practice['data'].get('timezone', 'Asia/Singapore'))
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat() != start or last.isoformat() != end or not 0 <= (last-first).days <= 365:
            raise ValueError()
        lower = datetime.combine(first, time.min, zone).astimezone(timezone.utc)
        upper = datetime.combine(last+timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        fail('Choose valid YYYY-MM-DD dates, in order, covering at most 366 days')
    records = [unpack(r) for r in c.execute(
        'SELECT * FROM records WHERE clinic_id=? AND kind IN ('+','.join('?' for _ in KINDS)+') ORDER BY created_at,id LIMIT ?',
        (clinic, *KINDS, MAX_RECORDS+1))]
    if len(records) > MAX_RECORDS:
        fail('This clinic exceeds the current financial register limit. A paged ledger migration is required; no partial totals were returned.', 409)
    by_id = {r['id']: r for r in records}
    invoices = {r['id']: r for r in records if r['kind'] == 'invoice'}
    issues, entries = [], []
    voids = defaultdict(list)
    for r in records:
        if r['kind'] == 'invoice_void':
            voids[r['data'].get('invoice_id')].append(r)

    def issue(record_id, message):
        issues.append({'record_id': record_id, 'message': message})

    def append(r, invoice, charge, cash, tax, source='record'):
        timestamp = instant(r['created_at'])
        entries.append({'id': r['id'], 'kind': r['kind'], 'invoice_id': invoice['id'],
                        'invoice_number': invoice['data'].get('number', invoice['id']),
                        'patient_id': invoice['data']['patient_id'], 'recorded_at': timestamp.isoformat(),
                        'local_date': timestamp.astimezone(zone).date().isoformat(),
                        'charge_cents': charge, 'cash_cents': cash, 'tax_cents': tax,
                        'balance_change_cents': charge-cash, 'source': source,
                        'method': r['data'].get('method', ''),
                        'reference': r['data'].get('reference', r['data'].get('provider_refund_id', '')),
                        'reason': r['data'].get('reason', ''),
                        'test_mode': bool(r['data'].get('test_mode', False))})

    for r in records:
        d, kind = r['data'], r['kind']
        invoice = r if kind == 'invoice' else invoices.get(d.get('invoice_id'))
        if not invoice:
            issue(r['id'], 'Missing invoice in this clinic; movement excluded.')
            continue
        try:
            amount = cents(d['total_cents'] if kind == 'invoice' else d['amount_cents'])
            if kind in ('payment', 'refund'):
                if kind == 'refund':
                    payment = by_id.get(d.get('payment_id'))
                    if not payment or payment['kind'] != 'payment' or payment['data']['invoice_id'] != invoice['id']:
                        raise ValueError('Refund payment does not match invoice')
                    r = {**r, 'data': {**d, 'method': payment['data'].get('method', '')}}
                append(r, invoice, 0, amount if kind == 'payment' else -amount, None)
            else:
                tax = cents(d['tax_cents']) if d.get('tax_cents') is not None else None
                if tax is not None and tax > amount:
                    raise ValueError('Tax exceeds movement')
                if kind == 'invoice_void' and (invoice['data']['status'] != 'void' or amount != invoice['data']['total_cents']):
                    raise ValueError('Void does not match invoice')
                if kind == 'credit_note_reversal':
                    credit = by_id.get(d.get('credit_note_id'))
                    if not credit or credit['kind'] != 'credit_note' or credit['data']['invoice_id'] != invoice['id'] or credit['data']['amount_cents'] != amount:
                        raise ValueError('Reversal does not match credit')
                sign = -1 if kind in ('credit_note', 'invoice_void') else 1
                append(r, invoice, sign*amount, 0, sign*tax if tax is not None else None)
        except (KeyError, TypeError, ValueError, OverflowError):
            issue(r['id'], 'Invalid or inconsistent financial amount, reference or timestamp; movement excluded.')

    # Previous releases stored void only on the invoice. The original audit is
    # the only accepted historical date; updated_at is not a void receipt.
    audits = {}
    for row in c.execute("SELECT * FROM audit WHERE clinic_id=? AND action='invoice.void' ORDER BY created_at,id", (clinic,)):
        audits.setdefault(row['resource_id'], dict(row))
    for id, invoice in invoices.items():
        if len(voids[id]) > 1:
            issue(id, 'Multiple void receipts require reconciliation.')
        if invoice['data']['status'] == 'void' and not voids[id]:
            receipt = audits.get(id)
            if not receipt:
                issue(id, 'Historical void has no dated receipt; no void date was invented.')
                continue
            try:
                amount = cents(invoice['data']['total_cents'])
                tax = invoice['data'].get('tax_cents')
                append({'id': receipt['id'], 'kind': 'invoice_void', 'created_at': receipt['created_at'],
                        'data': {'reason': invoice['data'].get('void_reason', '')}}, invoice,
                       -amount, 0, -cents(tax) if tax is not None else None, 'historical_audit')
            except (KeyError, TypeError, ValueError, OverflowError):
                issue(id, 'Historical void receipt is invalid; movement excluded.')

    entries.sort(key=lambda e: (e['recorded_at'], e['id']))
    current_charge, current_cash, opening, closing = (defaultdict(int) for _ in range(4))
    selected = []
    for e in entries:
        id = e['invoice_id']; timestamp = instant(e['recorded_at'])
        current_charge[id] += e['charge_cents']; current_cash[id] += e['cash_cents']
        if timestamp < lower:
            opening[id] += e['balance_change_cents']
        if timestamp < upper:
            closing[id] += e['balance_change_cents']
        if lower <= timestamp < upper:
            selected.append(e)
    mismatches = []
    for id, invoice in invoices.items():
        try:
            d = invoice['data']
            expected_charge = 0 if d['status'] == 'void' else cents(d['total_cents'])-cents(d.get('credited_cents', 0))
            expected_cash = cents(d['paid_cents'])
            if expected_charge != current_charge[id] or expected_cash != current_cash[id]:
                mismatches.append({'invoice_id': id, 'invoice_number': d.get('number', id),
                                   'charge_difference_cents': current_charge[id]-expected_charge,
                                   'cash_difference_cents': current_cash[id]-expected_cash})
        except (KeyError, TypeError, ValueError):
            issue(id, 'Invoice balance is invalid; current reconciliation unavailable.')

    def balances(values):
        return {'net_cents': sum(values.values()), 'receivable_cents': sum(max(0, v) for v in values.values()),
                'refund_due_cents': sum(max(0, -v) for v in values.values())}

    totals = {kind: sum(e['charge_cents'] if kind not in ('payment', 'refund') else e['cash_cents']
                        for e in selected if e['kind'] == kind) for kind in KINDS}
    # JSON numbers are consumed by JavaScript. Do not display rounded financial
    # totals even if individually valid records accumulate beyond its exact range.
    checked = [*totals.values(), *balances(opening).values(), *balances(closing).values(),
               sum(e['charge_cents'] for e in selected), sum(e['cash_cents'] for e in selected),
               sum(e['tax_cents'] for e in selected if e['tax_cents'] is not None)]
    checked += [v for m in mismatches for k, v in m.items() if k.endswith('_cents')]
    if any(abs(v) > 2**53-1 for v in checked):
        fail('Financial totals exceed the exact display range; no rounded totals were returned.', 409)
    return {'clinic_id': clinic, 'currency': 'SGD', 'timezone': str(zone), 'start': start, 'end': end,
            'generated_at': now(), 'basis': 'recorded_at', 'entries': selected, 'total': len(selected),
            'opening': balances(opening), 'closing': balances(closing), 'totals': totals,
            'net_charges_cents': sum(e['charge_cents'] for e in selected),
            'net_cash_cents': sum(e['cash_cents'] for e in selected),
            'known_tax_cents': sum(e['tax_cents'] for e in selected if e['tax_cents'] is not None),
            'unknown_tax_entries': sum(e['tax_cents'] is None for e in selected if e['kind'] not in ('payment', 'refund')),
            'reconciled': not issues and not mismatches, 'issue_count': len(issues), 'issues': issues[:100],
            'mismatch_count': len(mismatches), 'mismatches': mismatches[:100],
            'invoice_count': len(invoices)}


def read(request, start, end):
    from main import identity
    clinic, actor = identity(request)
    with connection() as c:
        c.execute('BEGIN')  # A single SQLite snapshot across movements and audit receipts.
        if owned(c, actor, clinic, 'member')['data']['role'] != 'admin':
            fail('Administrator access required', 403)
        return build(c, clinic, start, end)


@router.get('')
def report(request: Request, start: str, end: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=250)):
    result = read(request, start, end)
    return {**result, 'offset': offset, 'limit': limit, 'entries': result['entries'][offset:offset+limit]}


def safe_text(value):
    value = str(value)
    return "'"+value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


@router.get('/export')
def export(request: Request, start: str, end: str):
    r = read(request, start, end)
    if not r['reconciled']:
        fail('Resolve the financial register reconciliation issues before exporting. The report shows the affected records.', 409)
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(['Record ID', 'Kind', 'Invoice ID', 'Invoice', 'Recorded UTC', 'Clinic date', 'Timezone', 'Currency',
                     'Charge cents', 'Cash cents', 'Balance change cents', 'Tax cents (blank = unknown or cash)',
                     'Method', 'Reference', 'Reason', 'Test mode', 'Source', 'Period start', 'Period end', 'Generated UTC'])
    for e in r['entries']:
        writer.writerow([safe_text(e[k]) for k in ('id', 'kind', 'invoice_id', 'invoice_number', 'recorded_at', 'local_date')]
                        +[safe_text(r['timezone']), r['currency'], e['charge_cents'], e['cash_cents'], e['balance_change_cents'], e['tax_cents']]
                        +[safe_text(e[k]) for k in ('method', 'reference', 'reason')]
                        +[e['test_mode'], e['source'], start, end, r['generated_at']])
    return Response(out.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="broby-financial-register.csv"'})
