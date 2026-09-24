"""Two-sided consent for attaching an independent clinic without moving records."""
import hashlib,json
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Request
from db import connection,get,all_records,record,update,now,uid
from organizations import account,policy,master

router=APIRouter()
PERMISSIONS={a:{'admin'} for a in ('organization.join_request','organization.join_cancel','organization.join_review')}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def organization(c,oid):
    from actions import fail
    if not isinstance(oid,str) or not 1<=len(oid)<=100:fail('Enter a valid organization ID')
    org=c.execute('SELECT * FROM organizations WHERE id=?',(oid,)).fetchone()
    if not org:fail('Organization not found',404)
    if org['master_account'].startswith('member:') or not c.execute('SELECT 1 FROM credentials WHERE username=?',(org['master_account'],)).fetchone():
        fail('The organization master needs a password account before accepting existing clinics',409)
    return dict(org)


def consent(c,clinic,oid):
    from actions import owned,fail
    if policy(c,clinic):fail('This clinic already belongs to an organization',409)
    org=organization(c,oid);practice=owned(c,clinic,clinic,'clinic')
    return {'organization_id':org['id'],'organization_name':org['name'],
            'locked_actions':json.loads(org['locked_actions']),'organization_digest':digest(org),
            'clinic_id':clinic,'clinic_name':practice['data']['name'],'clinic_version':practice['version'],
            'timezone':practice['data'].get('timezone'),'currency':practice['data'].get('currency','SGD'),
            'access':'Organization master receives administrator access to all existing and future clinic records. Inherited restrictions apply to other clinic staff, including administrators.'}


def summary(c,row):
    # This is the exact administrative information the requester agrees to share.
    counts=dict(c.execute('SELECT kind,COUNT(*) FROM records WHERE clinic_id=? GROUP BY kind',(row['clinic_id'],)).fetchall())
    return {**row,'record_counts':counts}


def review(c,clinic,actor,p):
    from actions import fail,version
    org=policy(c,clinic)
    if not org or not master(c,org,actor):fail('Organization master access required',403)
    if not isinstance(p.get('id'),str):fail('Enter a valid adoption request ID')
    r=get(c,p.get('id'))
    if not r or r['kind']!='organization_adoption' or r['data']['consent']['organization_id']!=org['id']:fail('Adoption request not found',404)
    version(r,p)
    if r['data']['status']!='pending':fail('Only a pending request can be reviewed',409)
    return r,org


def acceptance(c,r):
    from actions import fail
    d=r['data']
    if d['expires_at']<=now():fail('Request expired. Ask the clinic administrator to submit a fresh request.',409)
    current=consent(c,r['clinic_id'],d['consent']['organization_id'])
    if current!=d['consent']:fail('The clinic or organization policies changed. Ask the clinic administrator to review a fresh request.',409)
    requester=get(c,d['requested_by'],r['clinic_id'])
    if not requester or not requester['data'].get('active') or requester['data']['role']!='admin' or account(c,requester['id'])!=d['requested_account']:
        fail('The requesting administrator no longer has authority. A current administrator must submit a fresh request.',409)
    org=organization(c,current['organization_id'])
    membership=c.execute('SELECT member_id FROM auth_memberships WHERE username=? AND clinic_id=?',(org['master_account'],r['clinic_id'])).fetchone()
    if membership:
        member=get(c,membership[0],r['clinic_id'])
        if not member or not member['data'].get('active') or member['data']['role']!='admin':
            fail('The master already has a restricted or inactive clinic membership. The clinic administrator must resolve that membership first.',409)
    result=summary(c,r)
    result['digest']=digest(result)
    return result,org,membership


@router.post('/api/organization/join-preview')
def preview_route(payload:dict,request:Request):
    from main import identity
    from actions import authorize
    clinic,actor=identity(request)
    with connection() as c:
        authorize(c,clinic,actor,'organization.join_request')
        result=consent(c,clinic,payload.get('organization_id'));return {**result,'digest':digest(result)}


@router.get('/api/organization/adoptions')
def list_route(request:Request):
    from main import identity
    from actions import owned,fail
    clinic,actor=identity(request)
    with connection() as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin':fail('Administrator access required',403)
        org=policy(c,clinic)
        # No global clinic directory or patient/owner data is exposed.
        if org and master(c,org,actor):
            from db import json_text
            ids=[r[0] for r in c.execute("SELECT id FROM records WHERE kind='organization_adoption' AND "+json_text(c,'data','consent','organization_id')+"=? ORDER BY created_at DESC LIMIT 100",(org['id'],))]
            return [summary(c,get(c,id)) for id in ids]
        return [summary(c,r) for r in all_records(c,clinic,'organization_adoption')][:100]


@router.post('/api/organization/adoption-preview')
def acceptance_route(payload:dict,request:Request):
    from main import identity
    from actions import authorize
    clinic,actor=identity(request)
    with connection() as c:
        authorize(c,clinic,actor,'organization.join_review');r,_=review(c,clinic,actor,payload)
        return acceptance(c,r)[0]


def dispatch(c,a,p,clinic,actor):
    from actions import owned,version,fail
    from recalls import text
    reason=text(p.get('reason'),'Administrative reason',500)
    if a=='organization.join_request':
        current=consent(c,clinic,p.get('organization_id'))
        if p.get('digest')!=digest(current) or p.get('accept_access') is not True:fail('Review and explicitly accept the organization access and restrictions before requesting.',409)
        if any(r['data']['status']=='pending' and r['data']['expires_at']>now() for r in all_records(c,clinic,'organization_adoption')):
            fail('Withdraw the pending request before requesting another organization.',409)
        return record(c,'organization_adoption',clinic,{'status':'pending','consent':current,'requested_by':actor,
            'requested_account':account(c,actor),'reason':reason,'requested_at':now(),
            'expires_at':(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()})
    if a=='organization.join_cancel':
        r=owned(c,p.get('id'),clinic,'organization_adoption');version(r,p)
        if r['data']['status']!='pending':fail('Only pending requests can be withdrawn',409)
        return update(c,r,{**r['data'],'status':'withdrawn','closed_by':actor,'closed_at':now(),'decision_reason':reason})
    r,org=review(c,clinic,actor,p)
    decision=p.get('decision')
    if decision not in ('accepted','declined'):fail('Choose accepted or declined')
    mid=None
    if decision=='accepted':
        result,org,membership=acceptance(c,r)
        if p.get('digest')!=result['digest'] or p.get('accept_access') is not True:fail('Review current clinic counts, access and restrictions before accepting.',409)
        target=r['clinic_id']
        if membership:mid=membership[0]
        else:
            mid=target+'-org-master-'+uid()
            actor_record=owned(c,actor,clinic,'member')
            record(c,'member',target,{'name':actor_record['data']['name'],'role':'admin','active':True},mid)
            c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',(org['master_account'],mid,target))
        c.execute('INSERT INTO organization_clinics VALUES(?,?)',(target,org['id']))
    result=update(c,r,{**r['data'],'status':decision,'closed_by':actor,'closed_at':now(),
        'decision_reason':reason,'master_member_id':mid,'review_digest':p.get('digest') if decision=='accepted' else None})
    # Shared executor records the master-side audit; the receiving clinic gets its own.
    c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),r['clinic_id'],actor,a,r['id'],now()))
    return result
