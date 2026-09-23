"""Organizations own newly provisioned clinics; existing clinics require their own administrator."""
import json
from db import record,get,uid,all_records
PERMISSIONS={'organization.create':{'admin'},'organization.clinic_create':{'admin'},'organization.policy':{'admin'}}

def setup(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS organizations(id TEXT PRIMARY KEY,name TEXT,master_account TEXT,locked_actions TEXT);
    CREATE TABLE IF NOT EXISTS organization_clinics(clinic_id TEXT PRIMARY KEY,organization_id TEXT);
    ''')
def account(c,actor):
    row=c.execute('SELECT username FROM auth_memberships WHERE member_id=?',(actor,)).fetchone()
    return row[0] if row else 'member:'+actor

def policy(c,clinic):
    row=c.execute('SELECT o.* FROM organizations o JOIN organization_clinics oc ON oc.organization_id=o.id WHERE oc.clinic_id=?',(clinic,)).fetchone()
    return dict(row) if row else None

def master(c,organization,actor):return organization['master_account']==account(c,actor)

def blocked(c,clinic,actor):
    org=policy(c,clinic)
    return set(json.loads(org['locked_actions'])) if org and not master(c,org,actor) else set()

def dispatch(c,a,p,clinic,actor):
    from actions import owned,require,fail,PERMISSIONS as permissions
    org=policy(c,clinic)
    if a=='organization.create':
        if org:fail('This clinic already belongs to an organization',409)
        oid=uid();name=require(p,'name')
        c.execute('INSERT INTO organizations VALUES(?,?,?,?)',(oid,name,account(c,actor),'[]'))
        c.execute('INSERT INTO organization_clinics VALUES(?,?)',(clinic,oid))
        return {'id':oid,'name':name}
    if not org or not master(c,org,actor):fail('Organization master access required',403)
    if a=='organization.policy':
        locks=p.get('actions',[])
        if not isinstance(locks,list) or any(x not in permissions or x.startswith('organization.') for x in locks):fail('Invalid organization locks')
        c.execute('UPDATE organizations SET locked_actions=? WHERE id=?',(json.dumps(sorted(set(locks))),org['id']))
        return {'id':org['id'],'locked_actions':locks}
    if a=='organization.clinic_create':
        from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
        timezone=p.get('timezone','Asia/Singapore')
        try:ZoneInfo(timezone)
        except (ZoneInfoNotFoundError,ValueError):fail('Unknown clinic timezone')
        cid='clinic-'+uid();member=owned(c,actor,clinic,'member');mid=cid+'-admin'
        record(c,'clinic',cid,{'name':require(p,'name'),'timezone':timezone,'locked_features':[]},cid)
        record(c,'member',cid,{'name':member['data']['name'],'role':'admin','active':True},mid)
        record(c,'settings',cid,{'retention':'medical','language':'en','emergency_phone':'','reminder_days':7,'auto_reminders':False,'auto_handover':False,'handover_at':'07:00'},'settings-'+cid)
        record(c,'template',cid,{'name':'SOAP','description':'Source-backed clinical notes','sections':['Subjective','Objective','Assessment','Plan']},'soap-'+cid)
        c.execute('INSERT INTO organization_clinics VALUES(?,?)',(cid,org['id']))
        if not org['master_account'].startswith('member:'):c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',(org['master_account'],mid,cid))
        return {'id':cid,'member_id':mid}
    fail('Unknown organization action',404)
