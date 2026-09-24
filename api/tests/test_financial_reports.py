import csv
import io
import json

import pytest
from fastapi.testclient import TestClient
import db
import main
import financial_reports as reports
from test_integrity import isolated, act, get, rows, err


def stamp(r, timestamp):
    with db.connection(True) as c:
        c.execute('UPDATE records SET created_at=? WHERE id=?', (timestamp, r['id']))
    return get(r['id'])


def invoice(at='2026-05-01T02:00:00+00:00'):
    return stamp(act('invoice.create', {'patient_id':'luna', 'items':[{'name':'Synthetic', 'quantity':1, 'price_cents':1000}], 'tax_bps':900}), at)


def report(start='2026-05-01', end='2026-05-31', clinic='clinic-east'):
    with db.connection() as c:
        return reports.build(c, clinic, start, end)


def credit(inv, at='2026-05-02T02:00:00+00:00'):
    return stamp(act('credit_note.create', {'id':inv['id'], 'version':get(inv['id'])['version'], 'net_cents':300, 'tax_cents':27, 'reason':'Synthetic correction'}), at)


def test_charges_cash_credits_refunds_and_reversal_reconcile_in_separate_periods():
    inv=invoice(); note=credit(inv)
    payment=stamp(act('payment.record', {'id':inv['id'], 'version':get(inv['id'])['version'], 'amount_cents':763, 'method':'cash'}), '2026-05-03T02:00:00+00:00')
    stamp(act('credit_note.reverse', {'id':note['id'], 'version':get(inv['id'])['version'], 'reason':'Reverse correction'}), '2026-06-01T02:00:00+00:00')
    stamp(act('payment.refund', {'id':payment['id'], 'version':get(inv['id'])['version'], 'amount_cents':100, 'reason':'External refund completed'}), '2026-06-02T02:00:00+00:00')
    may=report(); june=report('2026-06-01','2026-06-30')
    assert may['reconciled'] and june['reconciled']
    assert (may['net_charges_cents'], may['net_cash_cents'], may['known_tax_cents']) == (763,763,63)
    assert may['closing']['net_cents'] == june['opening']['net_cents'] == 0
    assert (june['net_charges_cents'], june['net_cash_cents'], june['closing']['receivable_cents']) == (327,-100,427)
    assert len(may['entries']) == 3 and len(june['entries']) == 2
    assert june['opening']['net_cents']+june['net_charges_cents']-june['net_cash_cents']==june['closing']['net_cents']


def test_paid_credit_is_refund_liability_not_cash_or_negative_receivable():
    inv=invoice(); stamp(act('payment.record', {'id':inv['id'],'version':inv['version'],'amount_cents':1090,'method':'bank_external'}),'2026-05-01T03:00:00+00:00')
    credit(inv)
    r=report()
    assert r['closing'] == {'net_cents':-327,'receivable_cents':0,'refund_due_cents':327}
    assert r['net_cash_cents']==1090 and r['reconciled']


def test_void_preserves_original_period_and_is_appended_once():
    inv=invoice(); p={'id':inv['id'],'version':1,'reason':'Synthetic void'}
    result=act('invoice.void',p,key='void-financial-once')
    assert act('invoice.void',p,key='void-financial-once')==result
    assert len(rows('invoice_void'))==1
    stamp(rows('invoice_void')[0],'2026-06-01T02:00:00+00:00')
    err(409,lambda:act('invoice.void',{**p,'version':get(inv['id'])['version']}))
    may=report(); june=report('2026-06-01','2026-06-30')
    assert may['net_charges_cents']==1090 and may['closing']['receivable_cents']==1090
    assert june['opening']['receivable_cents']==1090 and june['net_charges_cents']==-1090
    assert june['closing']['net_cents']==0 and june['known_tax_cents']==-90 and june['reconciled']


def test_historical_void_uses_first_audit_receipt_and_no_guessed_updated_date():
    inv=invoice(); act('invoice.void',{'id':inv['id'],'version':1,'reason':'Legacy void'})
    with db.connection(True) as c:
        c.execute("DELETE FROM records WHERE kind='invoice_void'")
        c.execute("UPDATE audit SET created_at='2026-06-01T02:00:00+00:00' WHERE action='invoice.void'")
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',('duplicate-old-void','clinic-east','clinic-east-admin','invoice.void',inv['id'],'2026-07-01T00:00:00+00:00'))
    r=report('2026-06-01','2026-06-30')
    assert r['reconciled'] and r['total']==1 and r['entries'][0]['source']=='historical_audit'
    with db.connection(True) as c:c.execute("DELETE FROM audit WHERE action='invoice.void'")
    r=report()
    assert not r['reconciled'] and r['issue_count']==1 and r['mismatch_count']==1
    assert 'no dated receipt' in r['issues'][0]['message']


def test_clinic_midnight_is_inclusive_start_exclusive_next_day():
    before=invoice('2026-04-30T15:59:59+00:00')
    inside=invoice('2026-04-30T16:00:00+00:00')
    after=invoice('2026-05-31T16:00:00+00:00')
    r=report()
    assert [e['id'] for e in r['entries']]==[inside['id']]
    assert r['opening']['net_cents']==1090 and r['closing']['net_cents']==2180


@pytest.mark.parametrize('start,end', [('2026-05-00','2026-05-31'),('20260501','2026-05-31'),('2026-05-02','2026-05-01'),('2025-01-01','2026-05-31'),('2026-05-01T00:00','2026-05-31')])
def test_invalid_period_rejected(start,end):
    err(422,lambda:report(start,end))


def test_legacy_tax_is_unknown_and_pending_provider_requests_are_not_cash():
    inv=stamp(rows('invoice')[0],'2026-05-01T00:00:00+00:00')
    with db.connection(True) as c:
        db.record(c,'stripe_checkout','clinic-east',{'invoice_id':inv['id'],'amount_cents':13000,'status':'open'})
        db.record(c,'stripe_refund','clinic-east',{'invoice_id':inv['id'],'amount_cents':100,'status':'queued'})
    r=report()
    assert r['unknown_tax_entries']==1 and r['known_tax_cents']==0 and r['net_cash_cents']==0 and r['reconciled']


def test_incomplete_import_balance_is_detected_and_export_blocked():
    inv=invoice()
    with db.connection(True) as c:db.update(c,get(inv['id']),{**inv['data'],'paid_cents':100,'status':'partial'})
    r=report()
    assert not r['reconciled'] and r['mismatches'][0]['cash_difference_cents']==-100
    client=TestClient(main.app)
    assert client.get('/api/reports/financial/export?start=2026-05-01&end=2026-05-31',headers={'x-actor-id':'clinic-east-admin'}).status_code==409


def test_invalid_or_foreign_references_never_leak_other_clinic():
    inv=invoice()
    with db.connection(True) as c:
        db.record(c,'payment','clinic-river',{'invoice_id':inv['id'],'amount_cents':987654,'reference':'OTHER-CLINIC-SECRET'})
        db.record(c,'refund','clinic-east',{'invoice_id':inv['id'],'payment_id':'missing','amount_cents':100})
        db.record(c,'payment','clinic-east',{'invoice_id':'foreign-invoice','amount_cents':111})
    r=report()
    assert not r['reconciled'] and r['issue_count']==2 and 'OTHER-CLINIC' not in json.dumps(r)
    assert report(clinic='clinic-river')['total']==0


def test_api_roles_pagination_csv_and_formula_safety():
    inv=invoice(); credit(inv)
    with db.connection(True) as c:
        db.update(c,get(inv['id']),{**get(inv['id'])['data'],'number':'=HYPERLINK("bad")'})
    client=TestClient(main.app); path='/api/reports/financial?start=2026-05-01&end=2026-05-31'
    assert client.get(path).status_code==403
    assert client.get(path,headers={'x-actor-id':'clinic-east-nurse'}).status_code==403
    headers={'x-actor-id':'clinic-east-admin'}
    first=client.get(path+'&limit=1',headers=headers).json(); second=client.get(path+'&limit=1&offset=1',headers=headers).json()
    assert first['total']==2 and first['net_charges_cents']==second['net_charges_cents']==763
    assert first['entries'][0]['id']!=second['entries'][0]['id']
    response=client.get('/api/reports/financial/export?start=2026-05-01&end=2026-05-31',headers=headers)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    parsed=list(csv.DictReader(io.StringIO(response.text)))
    assert parsed[0]['Invoice'].startswith("'=HYPERLINK")
    assert parsed[1]['Charge cents']=='-327' and parsed[1]['Tax cents (blank = unknown or cash)']=='-27'


def test_limit_returns_failure_instead_of_partial_totals(monkeypatch):
    invoice();monkeypatch.setattr(reports,'MAX_RECORDS',1)
    err(409,lambda:report())


def test_currency_and_bad_data_are_not_silently_coerced():
    inv=invoice()
    with db.connection(True) as c:
        db.record(c,'payment','clinic-east',{'invoice_id':inv['id'],'amount_cents':True})
    assert report()['issue_count']==1
    with db.connection(True) as c:
        practice=get('clinic-east');db.update(c,practice,{**practice['data'],'currency':'USD'})
    err(409,lambda:report())


def test_aggregate_never_crosses_javascript_exact_integer_range():
    with db.connection(True) as c:
        for n in range(91):
            r=db.record(c,'invoice','clinic-east',{'patient_id':'luna','number':str(n),'total_cents':10**14,'tax_cents':0,'paid_cents':0,'status':'issued'})
            c.execute("UPDATE records SET created_at='2026-05-01T00:00:00+00:00' WHERE id=?",(r['id'],))
    err(409,lambda:report())
