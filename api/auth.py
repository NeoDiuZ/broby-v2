"""Optional local password sessions; demo actor headers are disabled in password mode."""
import hashlib,hmac,secrets,os,json,getpass,argparse
from datetime import datetime,timezone,timedelta
from db import connection,get,now,init,upsert
from fastapi import HTTPException

def enabled():return os.getenv('BROBY_AUTH_MODE','demo')=='password'
def digest(token):return hashlib.sha256(token.encode()).hexdigest()
def password_hash(password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=64).hex()
def setup_tables():
    with connection(True) as c:c.execute('CREATE TABLE IF NOT EXISTS auth_memberships(username TEXT,member_id TEXT,clinic_id TEXT,PRIMARY KEY(username,clinic_id))')
def session(request):
    token=request.cookies.get('broby_session','')
    with connection() as c:
        r=c.execute('SELECT * FROM sessions WHERE token_hash=? AND expires_at>?',(digest(token),now())).fetchone()
        return dict(r) if r else None

def resolve(request):
    sess=session(request)
    if not sess:raise HTTPException(401,'Sign in to continue')
    with connection() as c:
        memberships=[dict(r) for r in c.execute('SELECT * FROM auth_memberships WHERE username=?',(sess['username'],))]
        clinic=request.headers.get('x-clinic-id') or (memberships[0]['clinic_id'] if memberships else '')
        m=next((r for r in memberships if r['clinic_id']==clinic),None)
        if not m:raise HTTPException(403,'This account has no access to the selected clinic')
        member=get(c,m['member_id'],clinic)
        if not member or not member['data'].get('active'):raise HTTPException(403,'Membership is inactive')
        return clinic,m['member_id']

def login(username,password,address,code=''):
    if not enabled():raise HTTPException(409,'Password authentication is not enabled')
    key=digest(address+':'+username)
    with connection(True) as c:
        attempt=c.execute('SELECT * FROM login_attempts WHERE address=?',(key,)).fetchone()
        if attempt and attempt['blocked_until']>now():raise HTTPException(429,'Too many attempts. Try again in five minutes.')
        row=c.execute('SELECT * FROM credentials WHERE username=?',(username,)).fetchone()
        # Do the same expensive hash for unknown usernames to reduce timing differences.
        salt=row['salt'] if row else '00'*16
        valid=row and hmac.compare_digest(password_hash(password,salt),row['password_hash'])
        if not row:password_hash(password,salt)
        if valid:
            from accounts import verify_code
            mfa=c.execute('SELECT * FROM account_mfa WHERE username=?',(username,)).fetchone()
            if mfa and mfa['enabled']:
                counter=verify_code(mfa['secret'],code,mfa['last_counter'])
                valid=counter is not None
                if not valid and len(code)==10:
                    recovery=c.execute('UPDATE mfa_recovery SET used_at=? WHERE username=? AND code_hash=? AND used_at IS NULL',(now(),username,digest(code))).rowcount
                    valid=recovery==1
                if counter is not None:c.execute('UPDATE account_mfa SET last_counter=? WHERE username=?',(counter,username))
        if not valid:
            failures=(attempt['failures'] if attempt and attempt['failures']<5 else 0)+1
            until=(datetime.now(timezone.utc)+timedelta(minutes=5 if failures>=5 else 0)).isoformat()
            upsert(c,'login_attempts',{'address':key,'failures':failures,'blocked_until':until},['address'])
            failed=True
        else:
            c.execute('DELETE FROM login_attempts WHERE address=?',(key,));token=secrets.token_urlsafe(32)
            expiry=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat()
            c.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),username,expiry));failed=False
    if failed:raise HTTPException(401,'Username or password is incorrect')
    return token

def provision(username,member_id,clinic,password):
    if len(password)<12:raise ValueError('Use at least 12 characters')
    salt=secrets.token_hex(16)
    with connection(True) as c:
        member=get(c,member_id,clinic)
        if not member or member['kind']!='member':raise ValueError('Membership not found')
        if c.execute('SELECT 1 FROM credentials WHERE username=?',(username,)).fetchone():raise ValueError('Username already exists; use link to add a clinic')
        c.execute('INSERT INTO credentials VALUES(?,?,?,?,?)',(username,member_id,clinic,salt,password_hash(password,salt)))
        c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',(username,member_id,clinic))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['create','link']);parser.add_argument('--username',required=True);parser.add_argument('--member',required=True);parser.add_argument('--clinic',required=True);args=parser.parse_args()
    init();setup_tables()
    if args.action=='create':
        password=getpass.getpass('New password (12+ characters): ')
        if password!=getpass.getpass('Repeat password: '):raise SystemExit('Passwords did not match')
        provision(args.username,args.member,args.clinic,password)
    else:
        with connection(True) as c:
            if not c.execute('SELECT 1 FROM credentials WHERE username=?',(args.username,)).fetchone():raise SystemExit('Account not found')
            member=get(c,args.member,args.clinic)
            if not member or member['kind']!='member':raise SystemExit('Membership not found')
            upsert(c,'auth_memberships',{'username':args.username,'member_id':args.member,'clinic_id':args.clinic},['username','clinic_id'])
    print('Account membership configured.')
