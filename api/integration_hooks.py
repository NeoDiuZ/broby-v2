"""Signed, clinic-bound synthetic callbacks; no production transmission capability."""
import hashlib,hmac,json,secrets,time
from fastapi import APIRouter,Request
from db import connection,uid,now
from actions import fail,owned,execute
router=APIRouter(prefix='/api/integrations/test')

def setup(c):c.execute('CREATE TABLE IF NOT EXISTS test_hook_keys(id TEXT PRIMARY KEY,secret TEXT,clinic_id TEXT,actor_id TEXT,revoked INTEGER DEFAULT 0)')

@router.post('/key')
def create_key(request:Request):
    from main import identity
    clinic,actor=identity(request)
    with connection(True) as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin':fail('Administrator access required',403)
        kid=uid();secret=secrets.token_urlsafe(32)
        c.execute('INSERT INTO test_hook_keys VALUES(?,?,?,?,0)',(kid,secret,clinic,actor))
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),clinic,actor,'test_hook.created',kid,now()))
    return {'id':kid,'secret':secret,'mode':'synthetic','sending_enabled':False}

@router.delete('/key/{id}')
def revoke_key(id:str,request:Request):
    from main import identity
    clinic,actor=identity(request)
    with connection(True) as c:
        if owned(c,actor,clinic,'member')['data']['role']!='admin':fail('Administrator access required',403)
        c.execute('UPDATE test_hook_keys SET revoked=1 WHERE id=? AND clinic_id=?',(id,clinic))
    return {'revoked':True}

@router.post('/events')
async def receive(request:Request):
    raw=await request.body()
    if len(raw)>1024*1024:fail('Callback exceeds 1 MB',413)
    kid=request.headers.get('x-broby-key','');timestamp=request.headers.get('x-broby-timestamp','');signature=request.headers.get('x-broby-signature','')
    try:
        if abs(time.time()-int(timestamp))>300:fail('Callback timestamp expired',401)
    except ValueError:fail('Invalid callback timestamp',401)
    with connection() as c:key=c.execute('SELECT * FROM test_hook_keys WHERE id=? AND revoked=0',(kid,)).fetchone()
    if not key:fail('Invalid callback key',401)
    expected=hmac.new(key['secret'].encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature):fail('Invalid callback signature',401)
    try:body=json.loads(raw)
    except ValueError:fail('Invalid callback JSON')
    if not isinstance(body,dict) or body.get('action') not in ('test.payment.callback','test.message.callback','test.lab.receive'):fail('Unsupported callback')
    event_id=body.get('event_id')
    if not isinstance(event_id,str) or not 1<=len(event_id)<=200 or not isinstance(body.get('payload'),dict):fail('Callback requires event_id and payload')
    dedupe=hashlib.sha256((kid+':'+event_id).encode()).hexdigest()
    return execute(body['action'],body['payload'],key['clinic_id'],key['actor_id'],'callback:'+dedupe)
