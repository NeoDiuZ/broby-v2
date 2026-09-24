"""A live-provider refresh must not conceal genuine release regressions."""
import importlib.util
from pathlib import Path
from copy import deepcopy
spec=importlib.util.spec_from_file_location('verification_records', Path(__file__).parents[2]/'scripts/verification_records.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
stable=mod.stable_record

def row(kind='stripe_checkout'):
    return {'id':'synthetic','kind':kind,'version':1,'created_at':'same','updated_at':'old','data':{'verified_at':'old','status':'succeeded','amount_cents':100,'invoice_id':'invoice-one'}}

def test_only_known_stripe_poll_metadata_is_ignored_without_mutating_receipts():
    before=row();after=deepcopy(before);after.update(version=2,updated_at='new');after['data']['verified_at']='new'
    assert stable(before)==stable(after)
    assert before['version']==1 and before['data']['verified_at']=='old' and after['version']==2
    before=row('stripe_refund');after=deepcopy(before);after.update(version=2,updated_at='new');assert stable(before)==stable(after)
    after['data']['verified_at']='different';assert stable(before)!=stable(after)

def test_financial_changes_missing_receipts_and_unrelated_edits_still_fail():
    before=row()
    for key,value in [('amount_cents',99),('status','failed'),('invoice_id','invoice-two')]:
        after=deepcopy(before);after['data'][key]=value;assert stable(before)!=stable(after)
    assert stable(before)!=stable(None)
    after=deepcopy(before);after['created_at']='changed';assert stable(before)!=stable(after)
    for kind in ['invoice','payment','source','staff_leave','patient']:
        before=row(kind);after=deepcopy(before);after['version']+=1;assert stable(before)!=stable(after)
