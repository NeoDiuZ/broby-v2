"""Explicit, single-recipient WhatsApp trial. Never dispatches patient drafts."""
import hashlib,json,os,re,secrets,time
from datetime import datetime,timezone,timedelta
from urllib.parse import parse_qsl,urlsplit
from fastapi import APIRouter,Request,Response
from starlette.datastructures import FormData
from twilio.rest import Client
from twilio.http.http_client import TwilioHttpClient
from twilio.request_validator import RequestValidator
from twilio.base.exceptions import TwilioRestException
from db import connection,get,record,update,all_records,now,uid,upsert

PERMISSIONS={'twilio.trial_send':{'admin'},'twilio.reconcile':{'admin'}}
router=APIRouter(prefix='/api/integrations/twilio')
STATES={'accepted','scheduled','queued','sending','sent','delivered','read','failed','undelivered','canceled'}
TERMINAL={'read','failed','undelivered','canceled'}


def setup(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS twilio_attempts(id TEXT PRIMARY KEY,resource_id TEXT UNIQUE,token TEXT,lease_until DOUBLE PRECISION DEFAULT 0,next_poll DOUBLE PRECISION DEFAULT 0);
    CREATE TABLE IF NOT EXISTS twilio_callbacks(digest TEXT PRIMARY KEY,message_sid TEXT,kind TEXT,received_at TEXT);
    CREATE TABLE IF NOT EXISTS twilio_optouts(clinic_id TEXT,recipient TEXT,blocked INTEGER,updated_at TEXT,PRIMARY KEY(clinic_id,recipient));
    ''')


def config(clinic=None):
    from actions import fail
    env=os.environ
    origin=env.get('BROBY_PUBLIC_URL','').rstrip('/');url=urlsplit(origin)
    values={k:env.get(k,'') for k in ('TWILIO_ACCOUNT_SID','TWILIO_AUTH_TOKEN','BROBY_TWILIO_CLINIC_ID','BROBY_TWILIO_FROM','BROBY_TWILIO_RECIPIENT','BROBY_TWILIO_CONTENT_SID','BROBY_TWILIO_TEMPLATE_TEXT')}
    if (env.get('BROBY_TWILIO_MODE')!='trial' or not all(values.values()) or
        not re.fullmatch(r'AC[0-9a-fA-F]{32}',values['TWILIO_ACCOUNT_SID']) or
        not re.fullmatch(r'HX[0-9a-fA-F]{32}',values['BROBY_TWILIO_CONTENT_SID']) or
        any(not re.fullmatch(r'whatsapp:\+[1-9][0-9]{7,14}',values[k]) for k in ('BROBY_TWILIO_FROM','BROBY_TWILIO_RECIPIENT')) or
        clinic is not None and clinic!=values['BROBY_TWILIO_CLINIC_ID'] or
        url.scheme!='https' or not url.netloc or url.path or url.query or url.fragment):
        fail('WhatsApp trial is not configured for this clinic',503)
    return {**values,'origin':origin}


def enabled():return os.getenv('BROBY_TWILIO_SEND_ENABLED')=='true'
def blocked(c,cfg):
    r=c.execute('SELECT blocked FROM twilio_optouts WHERE clinic_id=? AND recipient=?',(cfg['BROBY_TWILIO_CLINIC_ID'],cfg['BROBY_TWILIO_RECIPIENT'])).fetchone()
    return bool(r and r[0])

def client(cfg):
    return Client(cfg['TWILIO_ACCOUNT_SID'],cfg['TWILIO_AUTH_TOKEN'],http_client=TwilioHttpClient(timeout=15,max_retries=0))


def dispatch(c,a,p,clinic,actor):
    from actions import fail,require,owned
    cfg=config(clinic)
    if a=='twilio.trial_send':
        if not enabled():fail('WhatsApp trial sending is disabled',409)
        if blocked(c,cfg):fail('This test recipient has opted out',409)
        expected={'recipient':cfg['BROBY_TWILIO_RECIPIENT'],'content_sid':cfg['BROBY_TWILIO_CONTENT_SID'],'template_text':cfg['BROBY_TWILIO_TEMPLATE_TEXT']}
        if any(p.get(k)!=v for k,v in expected.items()):fail('Review the current test recipient and template before sending',409)
        # Includes uncertain and failed attempts. No background campaign or retry creates.
        if len([r for r in all_records(c,clinic,'whatsapp_trial') if r['created_at'][:10]==now()[:10]])>=10:
            fail('The trial is limited to ten requested messages per UTC day',429)
        r=record(c,'whatsapp_trial',clinic,{**expected,'sender':cfg['BROBY_TWILIO_FROM'],'account_sid':cfg['TWILIO_ACCOUNT_SID'],'actor_id':actor,'status':'queued','provider_sid':None,'provider_status':None,'error':None,'test_mode':True})
        c.execute('INSERT INTO twilio_attempts(id,resource_id) VALUES(?,?)',(uid(),r['id']))
        return r
    if a=='twilio.reconcile':
        r=owned(c,require(p,'id'),clinic,'whatsapp_trial')
        if not r['data'].get('provider_sid'):fail('No provider receipt yet. The message will not be resent automatically.',409)
        c.execute('UPDATE twilio_attempts SET next_poll=0 WHERE resource_id=?',(r['id'],))
        return r
    fail('Unknown WhatsApp action',404)


def claim():
    """A send claim is never replayed. A stale claim becomes uncertain."""
    from actions import authorize
    with connection(True) as c:
        cfg=config();clinic=cfg['BROBY_TWILIO_CLINIC_ID']
        for r in all_records(c,clinic,'whatsapp_trial')[::-1]:
            d=r['data'];attempt=c.execute('SELECT * FROM twilio_attempts WHERE resource_id=?',(r['id'],)).fetchone()
            if not attempt or attempt['lease_until']>time.time():continue
            if d['status']=='sending':
                update(c,r,{**d,'status':'uncertain','error':'The provider acknowledgement was interrupted. Waiting for a signed receipt; this message will not be resent.'})
                continue
            sending=d['status']=='queued' and not d.get('provider_sid')
            if not sending and (not d.get('provider_sid') or attempt['next_poll']>time.time() or
                                (d.get('provider_status') in TERMINAL or d['status']=='needs_review' or
                                 datetime.fromisoformat(r['created_at']) < datetime.now(timezone.utc)-timedelta(days=7)) and attempt['next_poll']!=0):continue
            if sending:
                try:
                    authorize(c,clinic,d['actor_id'],'twilio.trial_send')
                    if not enabled() or blocked(c,cfg):raise ValueError()
                    if any(d[k]!=cfg[v] for k,v in {'sender':'BROBY_TWILIO_FROM','recipient':'BROBY_TWILIO_RECIPIENT','content_sid':'BROBY_TWILIO_CONTENT_SID','account_sid':'TWILIO_ACCOUNT_SID','template_text':'BROBY_TWILIO_TEMPLATE_TEXT'}.items()):raise ValueError()
                except Exception:
                    update(c,r,{**d,'status':'blocked','error':'Sending permission, consent or trial configuration changed. No message was sent.'});continue
                update(c,r,{**d,'status':'sending','error':None})
            token=secrets.token_hex(24)
            c.execute('UPDATE twilio_attempts SET token=?,lease_until=?,next_poll=? WHERE id=?',(token,time.time()+90,time.time()+60,attempt['id']))
            return cfg,r,dict(attempt),token,sending


def verify_provider(obj,cfg,d):
    from actions import fail
    if (obj.account_sid!=d['account_sid'] or obj.from_!=d['sender'] or obj.to!=d['recipient'] or
        not re.fullmatch(r'SM[0-9a-fA-F]{32}',obj.sid) or obj.direction!='outbound-api' or obj.status not in STATES):
        fail('Provider identity did not match this message',409)
    return obj


def tick():
    job=claim()
    if not job:return
    cfg,r,attempt,token,sending=job;d=r['data']
    try:
        provider=client(cfg)
        if sending:
            obj=provider.messages.create(from_=d['sender'],to=d['recipient'],content_sid=d['content_sid'],status_callback=cfg['origin']+'/api/integrations/twilio/status/'+attempt['id'])
        else:obj=provider.messages(d['provider_sid']).fetch()
        verify_provider(obj,cfg,d)
        with connection(True) as c:
            current=get(c,r['id'],r['clinic_id']);data=current['data']
            lease=c.execute('SELECT token FROM twilio_attempts WHERE id=?',(attempt['id'],)).fetchone()
            if not lease or lease[0]!=token:return
            if data.get('provider_sid') and data['provider_sid']!=obj.sid:raise ValueError('SID mismatch')
            # Delayed canonical responses must not regress proven delivery/read.
            state=obj.status
            if data.get('provider_status')=='read' or data.get('provider_status')=='delivered' and state!='read':state=data['provider_status']
            update(c,current,{**data,'status':state,'provider_sid':obj.sid,'provider_status':state,'verified_at':now(),'verification_failures':0,'error':'Provider reported delivery failure'+(' ('+str(obj.error_code)+')' if obj.error_code else '') if state in ('failed','undelivered','canceled') else None})
    except Exception as exc:
        # No blind resend, including network failures and 5xx responses after acceptance.
        certain_rejection=sending and isinstance(exc,TwilioRestException) and 400<=exc.status<500
        with connection(True) as c:
            current=get(c,r['id'],r['clinic_id']);data=current['data']
            lease=c.execute('SELECT token FROM twilio_attempts WHERE id=?',(attempt['id'],)).fetchone()
            if lease and lease[0]==token:
                failures=data.get('verification_failures',0)+1
                status='failed' if certain_rejection else 'uncertain' if sending and not data.get('provider_sid') else data['status']
                error='Provider rejected this test request'+(' ('+str(exc.code)+')' if certain_rejection and exc.code else '') if certain_rejection else 'Verification is pending. An uncertain message is never resent automatically.'
                if not sending and failures>=10:status='needs_review';error='Ten provider checks failed. Review the connection before requesting another check.'
                update(c,current,{**data,'status':status,'error':error,'verification_failures':failures})
                c.execute('UPDATE twilio_attempts SET next_poll=? WHERE id=?',(time.time()+min(300,30*2**min(failures,4)),attempt['id']))
    finally:
        with connection(True) as c:c.execute('UPDATE twilio_attempts SET lease_until=0 WHERE id=? AND token=?',(attempt['id'],token))



async def signed(request,path):
    from actions import fail
    cfg=config()
    if request.url.query or not request.headers.get('content-type','').lower().startswith('application/x-www-form-urlencoded'):
        fail('Expected a signed form callback without query parameters',400)
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>1024*1024:fail('Callback exceeds 1 MB',413)
    try:
        pairs=parse_qsl(bytes(raw).decode('utf-8'),keep_blank_values=True,max_num_fields=1000)
        if len(pairs)!=len({k for k,v in pairs}):fail('Ambiguous callback fields',400)
        form=FormData(pairs)
    except (ValueError,UnicodeDecodeError):fail('Invalid callback form',400)
    if not RequestValidator(cfg['TWILIO_AUTH_TOKEN']).validate(cfg['origin']+path,form,request.headers.get('x-twilio-signature','')):
        fail('Invalid Twilio callback signature',403)
    if form.get('AccountSid')!=cfg['TWILIO_ACCOUNT_SID'] or not re.fullmatch(r'SM[0-9a-fA-F]{32}',form.get('MessageSid','')):
        fail('Unexpected Twilio account or message',403)
    digest=hashlib.sha256(json.dumps([path,sorted(pairs)]).encode()).hexdigest()
    return cfg,form,digest


@router.post('/status/{attempt_id}')
async def callback(attempt_id:str,request:Request):
    from actions import fail
    cfg,form,digest=await signed(request,'/api/integrations/twilio/status/'+attempt_id)
    with connection(True) as c:
        attempt=c.execute('SELECT * FROM twilio_attempts WHERE id=?',(attempt_id,)).fetchone()
        if not attempt:fail('Message attempt not found',404)
        r=get(c,attempt['resource_id'],cfg['BROBY_TWILIO_CLINIC_ID'])
        if not r:fail('Message not found',404)
        d=r['data'];sid=form['MessageSid']
        if form.get('From')!=d['sender'] or form.get('To')!=d['recipient'] or form.get('MessageStatus') not in STATES:
            fail('Unexpected callback recipient or status',403)
        if d.get('provider_sid') and d['provider_sid']!=sid:fail('Message receipt does not match',409)
        if d['status']=='queued' and not d.get('provider_sid'):fail('Message has not been dispatched',409)
        if c.execute('SELECT 1 FROM twilio_callbacks WHERE digest=?',(digest,)).fetchone():return {'received':True,'duplicate':True}
        # A verified callback can recover the SID after the create response was lost.
        # Only a canonical API read promotes the user-visible delivery status.
        update(c,r,{**d,'provider_sid':sid,'callback_status':form['MessageStatus'],'callback_at':now()})
        c.execute('INSERT INTO twilio_callbacks VALUES(?,?,?,?)',(digest,sid,'status',now()))
        c.execute('UPDATE twilio_attempts SET next_poll=0 WHERE id=?',(attempt_id,))
    return {'received':True}


@router.post('/inbound')
async def inbound(request:Request):
    from actions import fail
    cfg,form,digest=await signed(request,'/api/integrations/twilio/inbound')
    if form.get('From')!=cfg['BROBY_TWILIO_RECIPIENT'] or form.get('To')!=cfg['BROBY_TWILIO_FROM']:
        fail('This inbox only accepts the configured test recipient',403)
    clinic=cfg['BROBY_TWILIO_CLINIC_ID'];sid=form['MessageSid'];body=form.get('Body','')
    if len(body)>5000:fail('Trial message exceeds 5000 characters',413)
    with connection(True) as c:
        if not c.execute("SELECT 1 FROM twilio_callbacks WHERE message_sid=? AND kind='inbound'",(sid,)).fetchone():
            record(c,'whatsapp_trial_inbound',clinic,{'provider_sid':sid,'body':body,'sender':form['From'],'test_mode':True,'media_count':form.get('NumMedia','0')})
            c.execute('INSERT INTO twilio_callbacks VALUES(?,?,?,?)',(digest,sid,'inbound',now()))
            optout=form.get('OptOutType','').upper()
            if optout in ('STOP','START') or body.strip().upper() in ('STOP','UNSUBSCRIBE','CANCEL','END','QUIT'):
                upsert(c,'twilio_optouts',{'clinic_id':clinic,'recipient':form['From'],'blocked':int(optout!='START'),'updated_at':now()},['clinic_id','recipient'])
    return Response(status_code=204)


@router.get('/status')
def status(request:Request):
    from main import identity
    from actions import authorize
    clinic,actor=identity(request)
    with connection() as c:
        authorize(c,clinic,actor,'twilio.trial_send')
        try:cfg=config(clinic)
        except Exception:return {'configured':False,'sending_enabled':False,'mode':'trial','customer_sending':False}
        return {'configured':True,'mode':'trial','sending_enabled':enabled() and not blocked(c,cfg),'customer_sending':False,
                'recipient':cfg['BROBY_TWILIO_RECIPIENT'],'sender':cfg['BROBY_TWILIO_FROM'],'content_sid':cfg['BROBY_TWILIO_CONTENT_SID'],'template_text':cfg['BROBY_TWILIO_TEMPLATE_TEXT'],
                'opted_out':blocked(c,cfg),'daily_limit':10,'callback_count':c.execute('SELECT COUNT(*) FROM twilio_callbacks').fetchone()[0]}
