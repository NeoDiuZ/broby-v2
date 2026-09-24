"""Stable record comparison for concurrent, read-only release verification.

Provider workers may refresh verification timestamps independently of a release.
Only those known metadata fields are exempted; financial data and other records
remain exact comparisons. Keep the original snapshots as evidence.
"""
from copy import deepcopy


def stable_record(row):
    if not isinstance(row, dict) or row.get('kind') not in ('stripe_checkout', 'stripe_refund'):
        return row
    result = deepcopy(row)
    result.pop('version', None)
    result.pop('updated_at', None)
    if result['kind'] == 'stripe_checkout':
        result['data'].pop('verified_at', None)
    return result
