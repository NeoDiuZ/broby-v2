"""Explicit, versioned member restrictions; active masters keep recovery access."""
import hashlib
import json
from fastapi import APIRouter, Request
from db import connection, update
from read_access import READS, allowed_reads

router = APIRouter()
PERMISSIONS = {'access.member': {'admin'}}

def review(c, clinic, actor, p):
    """Read-only current and proposed effective access for one exact member."""
    from actions import owned, version, require, fail
    from organizations import account, blocked, policy, master
    target = owned(c, require(p, 'id'), clinic, 'member')
    version(target, p)
    values = p.get('restrictions')
    if not isinstance(values, list) or any(not isinstance(v, str) or v not in READS for v in values):
        fail('Choose valid read restrictions')
    if target['id'] == actor: fail('Another administrator must review your own read restrictions', 409)
    org = policy(c, clinic)
    if org and master(c, org, target['id']): fail('The organization master retains recovery access', 409)
    reason = require(p, 'reason')
    if len(reason) > 500: fail('Use a reason of at most 500 characters')
    practice = owned(c, clinic, clinic, 'clinic')
    inherited = blocked(c, clinic, target['id']) & set(READS)
    if target['data']['role'] != 'admin':
        inherited |= set(practice['data'].get('locked_features', [])) & set(READS)
    proposed = set(READS) - inherited - set(values) if target['data'].get('active') else set()
    # Organization policy and account/master relationships live outside records;
    # pin those too so an assistant cannot confirm a stale effective-access view.
    state = {'clinic_id': clinic, 'member_id': target['id'], 'actor_id': actor,
             'clinic_version': practice['version'], 'member_version': target['version'],
             'organization': org, 'member_account': account(c, target['id']),
             'actor_account': account(c, actor)}
    digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    return {'member': target, 'clinic': practice, 'organization_name': org['name'] if org else None,
            'restrictions': sorted(set(values)), 'inherited_restrictions': sorted(inherited),
            'current_allowed': sorted(allowed_reads(c, clinic, target['id'])),
            'proposed_allowed': sorted(proposed), 'digest': digest, 'reason': reason}


def dispatch(c, action, p, clinic, actor):
    from actions import fail
    checked = review(c, clinic, actor, p)
    if 'expected_access_digest' in p and p['expected_access_digest'] != checked['digest']:
        fail('Clinic or organization access changed. Review the current member access before confirming.', 409)
    target, values, reason = checked['member'], checked['restrictions'], checked['reason']
    return update(c, target, {**target['data'], 'read_restrictions': sorted(set(values)),
                              'access_review': {'reason': reason, 'actor': actor}})

@router.get('/api/access')
def access(request: Request):
    from main import identity
    clinic, actor = identity(request)
    with connection() as c:
        return {'capabilities': READS, 'allowed': sorted(allowed_reads(c, clinic, actor)),
                'offline_max_hours': 12}
