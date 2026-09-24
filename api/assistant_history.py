"""Actor-private persistent conversations and exactly-once action confirmation."""
import hashlib
import json
import secrets
import time
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from db import connection, now, uid
from actions import owned, fail

router = APIRouter(prefix='/api/assistant/conversations')


def setup(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS assistant_conversations(
      id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL, actor_id TEXT NOT NULL,
      patient_id TEXT, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS assistant_conversation_owner ON assistant_conversations(clinic_id,actor_id,updated_at);
    CREATE TABLE IF NOT EXISTS assistant_turns(
      id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, clinic_id TEXT NOT NULL, actor_id TEXT NOT NULL,
      request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, message TEXT NOT NULL,
      patient_id TEXT, status TEXT NOT NULL, response TEXT, execution TEXT,
      token TEXT, lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
      UNIQUE(clinic_id,actor_id,request_key));
    CREATE INDEX IF NOT EXISTS assistant_turn_conversation ON assistant_turns(conversation_id,created_at);
    ''')


def conversation(c, id, clinic, actor):
    row = c.execute('SELECT * FROM assistant_conversations WHERE id=? AND clinic_id=? AND actor_id=?', (id,clinic,actor)).fetchone()
    if not row: fail('Conversation not found',404)
    return dict(row)


def present(turn):
    response = json.loads(turn['response']) if turn['response'] else {'text': 'This request was interrupted. Retry it to get a verified answer.', 'sources': []}
    return {**response, 'conversation_id':turn['conversation_id'], 'turn_id':turn['id'],
            'created_at':turn['created_at'], 'execution':json.loads(turn['execution']) if turn['execution'] else None}


def ask(clinic, actor, message, patient_id, conversation_id, key):
    """Persist intent before an external model request, then fence its result."""
    from assistant import answer
    from read_access import require, ALL
    fingerprint = hashlib.sha256(json.dumps([message,patient_id],ensure_ascii=False).encode()).hexdigest()
    with connection(True) as c:
        require(c,clinic,actor,ALL)
        if not owned(c,actor,clinic,'member')['data'].get('active'):fail('Membership is inactive',403)
        if patient_id: owned(c,patient_id,clinic,'patient')
        previous=c.execute('SELECT * FROM assistant_turns WHERE clinic_id=? AND actor_id=? AND request_key=?',(clinic,actor,key)).fetchone()
        if previous:
            if previous['fingerprint']!=fingerprint or conversation_id and conversation_id!=previous['conversation_id']:
                fail('Question retry key does not match its original request',409)
            conversation(c,previous['conversation_id'],clinic,actor)
            if previous['status']=='completed': return present(previous)
            if previous['lease_until']>time.time():fail('This question is still being processed',409)
            turn_id=previous['id'];conversation_id=previous['conversation_id']
        else:
            if conversation_id:
                conversation(c,conversation_id,clinic,actor)
            else:
                conversation_id=uid()
                c.execute('INSERT INTO assistant_conversations VALUES(?,?,?,?,?,?,?)', (conversation_id,clinic,actor,patient_id,message[:80],now(),now()))
            if c.execute("SELECT 1 FROM assistant_turns WHERE conversation_id=? AND status='pending' AND lease_until>?",(conversation_id,time.time())).fetchone():
                fail('Wait for the current question before sending another',409)
            if c.execute('SELECT COUNT(*) FROM assistant_turns WHERE conversation_id=?',(conversation_id,)).fetchone()[0]>=100:
                fail('Start a new conversation after 100 questions',409)
            turn_id=uid()
            c.execute('INSERT INTO assistant_turns(id,conversation_id,clinic_id,actor_id,request_key,fingerprint,message,patient_id,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (turn_id,conversation_id,clinic,actor,key,fingerprint,message,patient_id,'pending',now()))
        if c.execute("SELECT 1 FROM assistant_turns WHERE conversation_id=? AND id<>? AND status='pending' AND lease_until>?",(conversation_id,turn_id,time.time())).fetchone():
            fail('Wait for the current question before retrying another',409)
        token=secrets.token_hex(24)
        c.execute("UPDATE assistant_turns SET status='pending',token=?,lease_until=? WHERE id=?",(token,time.time()+300,turn_id))
        # A factual response is always re-read from current records. Persisted user
        # requests provide conversational context, never authority or medical facts.
        history=[r[0] for r in c.execute("SELECT message FROM assistant_turns WHERE conversation_id=? AND id<>? AND status='completed' ORDER BY created_at DESC LIMIT 5",(conversation_id,turn_id))][::-1]
    try:
        with connection() as c: result=answer(c,clinic,actor,message,patient_id,history)
        with connection(True) as c:
            require(c,clinic,actor,ALL)
            if not owned(c,actor,clinic,'member')['data'].get('active'):fail('Membership is inactive',403)
            changed=c.execute("UPDATE assistant_turns SET response=?,status='completed',lease_until=0 WHERE id=? AND token=?",(json.dumps(result),turn_id,token))
            if changed.rowcount!=1:fail('Another request replaced this response; reload the conversation',409)
            c.execute('UPDATE assistant_conversations SET patient_id=?,updated_at=? WHERE id=?',(patient_id,now(),conversation_id))
            return present(c.execute('SELECT * FROM assistant_turns WHERE id=?',(turn_id,)).fetchone())
    except Exception:
        with connection(True) as c:c.execute("UPDATE assistant_turns SET status='failed',lease_until=0 WHERE id=? AND token=?",(turn_id,token))
        raise


@router.get('')
def listing(request:Request):
    from main import identity
    clinic,actor=identity(request)
    with connection() as c:
        return [dict(r) for r in c.execute('SELECT id,patient_id,title,created_at,updated_at FROM assistant_conversations WHERE clinic_id=? AND actor_id=? ORDER BY updated_at DESC LIMIT 50',(clinic,actor))]


@router.get('/{id}')
def read(id:str,request:Request):
    from main import identity
    clinic,actor=identity(request)
    with connection() as c:
        result=conversation(c,id,clinic,actor)
        turns=[{**present(r),'message':r['message'],'patient_id':r['patient_id'],'status':r['status'],'request_key':r['request_key']} for r in c.execute('SELECT * FROM assistant_turns WHERE conversation_id=? ORDER BY created_at',(id,))]
    return {**result,'turns':turns}


@router.post('/{id}/turns/{turn_id}/confirm')
def confirm(id:str,turn_id:str,request:Request):
    from main import identity
    from actions import execute
    clinic,actor=identity(request)
    with connection() as c:
        conversation(c,id,clinic,actor)
        turn=c.execute("SELECT * FROM assistant_turns WHERE id=? AND conversation_id=? AND status='completed'",(turn_id,id)).fetchone()
        if not turn:fail('Completed question not found',404)
        result=json.loads(turn['response'])
        proposal=result.get('action')
        if not proposal:fail('This answer has no action to confirm',409)
    # The shared action executor rechecks today's permissions and record versions.
    # A retry after a lost response uses the same mutation key, even after reload.
    execution=execute(proposal['action'],proposal['payload'],clinic,actor,'assistant-confirm:'+turn_id)
    with connection(True) as c:c.execute('UPDATE assistant_turns SET execution=? WHERE id=?',(json.dumps(execution),turn_id))
    return execution
