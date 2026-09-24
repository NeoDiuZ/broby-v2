"""Explicit, versioned member restrictions; active masters keep recovery access."""
from fastapi import APIRouter, Request
from db import connection, update
from read_access import READS, allowed_reads

router = APIRouter()
PERMISSIONS = {'access.member': {'admin'}}

def dispatch(c, action, p, clinic, actor):
    from actions import owned, version, require, fail
    from organizations import policy, master
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
    return update(c, target, {**target['data'], 'read_restrictions': sorted(set(values)),
                              'access_review': {'reason': reason, 'actor': actor}})

@router.get('/api/access')
def access(request: Request):
    from main import identity
    clinic, actor = identity(request)
    with connection() as c:
        return {'capabilities': READS, 'allowed': sorted(allowed_reads(c, clinic, actor)),
                'offline_max_hours': 12}
