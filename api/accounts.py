"""Single-use account enrollment and replay-resistant authenticator MFA."""
import secrets,hashlib,hmac,base64,struct,time
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Request
from pydantic import BaseModel,Field
import auth
from db import connection,get,now,uid,upsert
from actions import owned,fail
router=APIRouter(prefix='/api/account')

def setup(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS auth_memberships(username TEXT,member_id TEXT,clinic_id TEXT,PRIMARY KEY(username,clinic_id));
    CREATE TABLE IF NOT EXISTS invitations(token_hash TEXT PRIMARY KEY,clinic_id TEXT,member_id TEXT,expires_at TEXT,used_at TEXT);
    CREATE TABLE IF NOT EXISTS mfa_recovery(username TEXT,code_hash TEXT,used_at TEXT,PRIMARY KEY(username,code_hash));
    CREATE TABLE IF NOT EXISTS account_mfa(username TEXT PRIMARY KEY,secret TEXT,pending_secret TEXT,last_counter INTEGER DEFAULT -1,enabled INTEGER DEFAULT 0);
    ''')

def totp(secret,counter):
    digest=hmac.new(base64.b32decode(secret),struct.pack('>Q',counter),hashlib.sha1).digest();offset=digest[-1]&15
    return str((struct.unpack('>I',digest[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)

def verify_code(secret,code,last=-1):
    counter=int(time.time()//30)
    for step in (counter,counter-1,counter+1):
        if step>last and hmac.compare_digest(totp(secret,step),code):return step
    return None

def account(request):
    sess=auth.session(request)
    if not sess:fail('Sign in to manage your account',401)
    auth.resolve(request)
    return sess['username']

def rate_limit(subject):
    # Count attempts in their own transaction, including failed validations.
    key=auth.digest('account-challenge:'+subject)
    with connection(True) as c:
        row=c.execute('SELECT * FROM login_attempts WHERE address=?',(key,)).fetchone()
        active=row and row['blocked_until']>now()
        if active and row['failures']>=10:fail('Too many account verification attempts. Try again in five minutes.',429)
        expiry=row['blocked_until'] if active else (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
        upsert(c,'login_attempts',{'address':key,'failures':row['failures']+1 if active else 1,'blocked_until':expiry},['address'])

class Enrollment(BaseModel):
    token:str=Field(min_length=20,max_length=200)
    username:str=Field(min_length=3,max_length=100,pattern=r'^[a-zA-Z0-9_.@-]+$')
    password:str=Field(min_length=12,max_length=1000)
    code:str=Field(default='',max_length=10)

@router.post('/invitations')
def invite(p:dict,request:Request):
    from main import identity
    clinic,actor=identity(request)
    with connection(True) as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin':fail('Administrator access required',403)
        member=owned(c,p.get('member_id'),clinic,'member')
        if not member['data'].get('active'):fail('Activate the membership first')
        secret=secrets.token_urlsafe(32);expiry=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()
        c.execute('DELETE FROM invitations WHERE member_id=? AND used_at IS NULL',(member['id'],))
        c.execute('INSERT INTO invitations VALUES(?,?,?,?,NULL)',(auth.digest(secret),clinic,member['id'],expiry))
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),clinic,actor,'account.invite',member['id'],now()))
        return {'token':secret,'expires_at':expiry,'delivery':'manual'}

@router.post('/invitations/accept')
def accept(p:Enrollment):
    rate_limit('enroll:'+p.username)
    with connection(True) as c:
        invitation=c.execute('SELECT * FROM invitations WHERE token_hash=? AND used_at IS NULL AND expires_at>?',(auth.digest(p.token),now())).fetchone()
        if not invitation:fail('Invitation expired or already used',404)
        member=owned(c,invitation['member_id'],invitation['clinic_id'],'member')
        if not member['data'].get('active'):fail('Membership is inactive',403)
        existing=c.execute('SELECT * FROM credentials WHERE username=?',(p.username,)).fetchone()
        if existing:
            if not hmac.compare_digest(auth.password_hash(p.password,existing['salt']),existing['password_hash']):fail('Existing account credentials are incorrect',401)
            mfa=c.execute('SELECT * FROM account_mfa WHERE username=?',(p.username,)).fetchone()
            if mfa and mfa['enabled']:
                counter=verify_code(mfa['secret'],p.code,mfa['last_counter'])
                if counter is None:fail('Authenticator code required',401)
                c.execute('UPDATE account_mfa SET last_counter=? WHERE username=?',(counter,p.username))
        else:
            salt=secrets.token_hex(16)
            c.execute('INSERT INTO credentials VALUES(?,?,?,?,?)',(p.username,member['id'],invitation['clinic_id'],salt,auth.password_hash(p.password,salt)))
        if c.execute('SELECT 1 FROM auth_memberships WHERE username=? AND clinic_id=?',(p.username,invitation['clinic_id'])).fetchone():fail('Account already belongs to this clinic',409)
        if c.execute('SELECT 1 FROM auth_memberships WHERE member_id=?',(member['id'],)).fetchone():fail('Membership already has an account',409)
        c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',(p.username,member['id'],invitation['clinic_id']))
        c.execute('UPDATE invitations SET used_at=? WHERE token_hash=?',(now(),auth.digest(p.token)))
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),invitation['clinic_id'],member['id'],'account.enrolled',member['id'],now()))
    return {'enrolled':True}

class PasswordCheck(BaseModel):
    password:str=Field(min_length=1,max_length=1000)
class MfaConfirm(BaseModel):code:str=Field(pattern=r'^\d{6}$')

@router.post('/mfa/setup')
def mfa_setup(p:PasswordCheck,request:Request):
    username=account(request)
    rate_limit(username)
    with connection(True) as c:
        credential=c.execute('SELECT * FROM credentials WHERE username=?',(username,)).fetchone()
        if not hmac.compare_digest(auth.password_hash(p.password,credential['salt']),credential['password_hash']):fail('Password is incorrect',401)
        old=c.execute('SELECT * FROM account_mfa WHERE username=?',(username,)).fetchone()
        if old and old['enabled']:fail('MFA is already enabled',409)
        secret=base64.b32encode(secrets.token_bytes(20)).decode()
        upsert(c,'account_mfa',{'username':username,'secret':'','pending_secret':secret,'last_counter':-1,'enabled':0},['username'])
    return {'secret':secret,'issuer':'Broby','account':username}

@router.post('/mfa/confirm')
def mfa_confirm(p:MfaConfirm,request:Request):
    username=account(request)
    rate_limit(username)
    with connection(True) as c:
        pending=c.execute('SELECT * FROM account_mfa WHERE username=?',(username,)).fetchone()
        if not pending or not pending['pending_secret']:fail('Start authenticator setup first')
        counter=verify_code(pending['pending_secret'],p.code)
        if counter is None:fail('Authenticator code is incorrect',401)
        c.execute("UPDATE account_mfa SET secret=pending_secret,pending_secret='',last_counter=?,enabled=1 WHERE username=?",(counter,username))
        # Other sessions must reauthenticate with MFA; this session just proved possession.
        c.execute('DELETE FROM sessions WHERE username=? AND token_hash<>?',(username,auth.digest(request.cookies.get('broby_session',''))))
        recovery=[secrets.token_hex(5) for _ in range(10)]
        c.execute('DELETE FROM mfa_recovery WHERE username=?',(username,))
        c.executemany('INSERT INTO mfa_recovery VALUES(?,?,NULL)',[(username,auth.digest(code)) for code in recovery])
    return {'enabled':True,'recovery_codes':recovery}

class PasswordChange(PasswordCheck):
    new_password:str=Field(min_length=12,max_length=1000)
    code:str=Field(default='',max_length=10)
@router.post('/password')
def password_change(p:PasswordChange,request:Request):
    username=account(request)
    rate_limit(username)
    with connection(True) as c:
        r=c.execute('SELECT * FROM credentials WHERE username=?',(username,)).fetchone()
        if not hmac.compare_digest(auth.password_hash(p.password,r['salt']),r['password_hash']):fail('Current password is incorrect',401)
        mfa=c.execute('SELECT * FROM account_mfa WHERE username=?',(username,)).fetchone()
        if mfa and mfa['enabled']:
            counter=verify_code(mfa['secret'],p.code,mfa['last_counter'])
            if counter is None:fail('Authenticator code is incorrect',401)
            c.execute('UPDATE account_mfa SET last_counter=? WHERE username=?',(counter,username))
        salt=secrets.token_hex(16)
        c.execute('UPDATE credentials SET salt=?,password_hash=? WHERE username=?',(salt,auth.password_hash(p.new_password,salt),username))
        c.execute('DELETE FROM sessions WHERE username=?',(username,))
    return {'changed':True,'sign_in_required':True}
