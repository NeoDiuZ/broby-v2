from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import db, main, recalls
from test_integrity import isolated, act, get, rows, err

ADMIN='clinic-east-admin'
FILTER={'start':'2099-01-01','end':'2099-01-31','query':'Synthetic recall'}

def reminder(patient='luna', **kw):
    return act('reminder.create', {'patient_id':patient,'title':'Synthetic recall','due':'2099-01-05',**kw})
def preview(**kw):
    with db.connection() as c: return recalls.preview(c,'clinic-east',{**FILTER,**kw})
def payload(review=None, **kw):
    p=review or preview()
    return {**FILTER,'digest':p['digest'],'title':'Synthetic January recalls','reminder_ids':[x['reminder_id'] for x in p['items'] if not x['blocked_reason']],**kw}
def prepare(**kw):return act('recall.prepare',payload(**kw))
def cancel(c):return act('recall.cancel',{'id':c['id'],'version':c['version'],'reason':'Synthetic cancellation'})
def out(c,index=0):return get(c['data']['items'][index]['outbox_id'])
def progress(c):
    with db.connection() as dbcon: return recalls.progress(dbcon,get(c['id']))
def opt_out(patient='luna',value=True):
    o=get(get(patient)['data']['owner_id'])
    return act('owner.recall_preference',{'id':o['id'],'version':o['version'],'opt_out':value,'reason':'Synthetic owner request'})

def test_preview_read_only_selection_exact_bodies_and_replay():
    a,b=reminder(),reminder('milo');before=rows(None);p=preview();assert rows(None)==before
    data=payload(p,reminder_ids=[a['id']]);result=act('recall.prepare',data,key='recall-once')
    assert act('recall.prepare',data,key='recall-once')==result
    assert len([x for x in rows('outbox') if x['data'].get('campaign_id')==result['id']])==1
    message=next(x for x in rows('outbox') if x['data'].get('campaign_id')==result['id'])
    assert message['data']['body']=='Reminder for Luna: Synthetic recall, due 2099-01-05. Please contact your clinic to arrange this.'
    assert message['data']['channel']=='manual' and message['data']['status']=='pending'
    assert get(a['id'])['data']['outbox_id']==message['id'] and 'outbox_id' not in get(b['id'])['data']
    assert progress(result)['counts']=={'pending':1,'excluded':1}
    err(409,lambda:act('recall.prepare',data))

@pytest.mark.parametrize('change',['reminder','owner','patient','new','optout','automatic'])
def test_review_changes_reject_without_partial_writes(change):
    r=reminder();p=payload()
    if change=='reminder':act('reminder.update',{'id':r['id'],'version':1,'title':'Synthetic recall edited','due':'2099-01-05'})
    if change=='owner':act('owner.update',{'id':'owner-luna','version':1,'name':'New name','phone':'','email':''})
    if change=='patient':act('patient.update',{'id':'luna','version':get('luna')['version'],'name':'Renamed'})
    if change=='new':reminder('milo')
    if change=='optout':opt_out()
    if change=='automatic':
        with db.connection(True) as c:recalls.queue_one(c,get(r['id']),'clinic-east',ADMIN)
    before=rows(None)
    err(409,lambda:act('recall.prepare',p));assert rows(None)==before

@pytest.mark.parametrize('field,value',[('start','invalid'),('end','2098-01-01'),('end','2100-01-02'),('query',[]),('query','x'*121)])
def test_invalid_filter(field,value):
    err(422,lambda:preview(**{field:value}))

@pytest.mark.parametrize('ids',[[],['unknown'],['x','x'],[{}],None])
def test_invalid_selection_rolls_back(ids):
    reminder();before=rows(None)
    err(422,lambda:prepare(reminder_ids=ids));assert rows(None)==before

def test_bounds_include_endpoints_and_limit():
    reminder(due=FILTER['start']);reminder(due=FILTER['end']);reminder(due='2099-02-01')
    assert len(preview()['items'])==2
    with db.connection(True) as c:
        for i in range(99):db.record(c,'reminder','clinic-east',{'patient_id':'luna','title':'Synthetic recall','due':'2099-01-06','status':'due'})
    err(422,lambda:preview());assert rows('recall_campaign')==[]

def test_two_reviews_racing_create_only_one_batch():
    reminder();p=payload();barrier=threading.Barrier(2)
    def run():
        barrier.wait()
        try:return act('recall.prepare',p)['id']
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(2) as executor:results=list(executor.map(lambda _:run(),range(2)))
    assert results.count(409)==1 and len(rows('recall_campaign'))==1
    assert len([x for x in rows('outbox') if x['data'].get('campaign_id')])==1

def test_cancel_keeps_sent_history_cancels_only_own_pending_and_no_retry():
    reminder();reminder('milo');c=prepare();first=out(c)
    manual=act('message.complete',{'id':first['id'],'version':first['version']})
    unrelated=act('message.queue',{'patient_id':'luna','body':'Unrelated care message'})
    cancelled=cancel(c)
    assert get(manual['id'])==manual and get(unrelated['id'])==unrelated
    assert progress(cancelled)['counts']=={'sent_manually':1,'cancelled':1}
    assert all(x['blocked_reason'] for x in preview()['items'])
    err(409,lambda:cancel(c))

def test_owner_optout_cancels_all_pending_recalls_and_blocks_preparation():
    r=reminder();c=prepare();unrelated=act('message.queue',{'patient_id':'luna','body':'Care update'})
    o=opt_out();assert out(c)['data']['status']=='cancelled' and get(unrelated['id'])==unrelated
    assert o['data']['recall_preferences'][0]['cancelled_draft_ids']==[out(c)['id']]
    extra=reminder();p=preview();assert all(x['blocked_reason']=='Owner opted out of recalls' for x in p['items'])
    with db.connection(True) as dbcon:
        from clinic_workflows import queue_due
        from datetime import datetime,timezone
        queue_due(dbcon,'clinic-east',ADMIN,datetime(2099,1,1,tzinfo=timezone.utc))
    assert 'outbox_id' not in get(extra['id'])['data']
    opt_out(value=False)
    assert preview()['items'][0]['blocked_reason'] or preview()['items'][1]['blocked_reason']
    assert len([x for x in preview()['items'] if not x['blocked_reason']])==1

@pytest.mark.parametrize('change',['contact','ownership','name','close','edit'])
def test_recipient_or_reminder_drift_blocks_delivery_and_edit(change):
    r=reminder();c=prepare();o=out(c)
    if change=='contact':act('owner.update',{'id':'owner-luna','version':1,'name':'Marcus Lee','phone':'different','email':''})
    if change=='ownership':act('patient.update',{'id':'luna','version':get('luna')['version'],'owner_id':'owner-milo'})
    if change=='name':act('patient.update',{'id':'luna','version':get('luna')['version'],'name':'Other name'})
    if change=='close':act('reminder.complete',{'id':r['id'],'version':get(r['id'])['version']})
    if change=='edit':act('reminder.update',{'id':r['id'],'version':get(r['id'])['version'],'title':'Changed','due':'2099-01-05'})
    o=get(o['id'])
    err(409,lambda:act('message.complete',{'id':o['id'],'version':o['version']}))
    err(409,lambda:act('message.update',{'id':o['id'],'version':o['version'],'body':'Changed text'}))
    client=TestClient(main.app)
    assert client.get('/api/outbox/'+o['id']+'/delivery-review').status_code==409
    if change in ('contact','ownership','name'):assert progress(c)['counts']=={'needs_review':1}

def test_scoping_permissions_and_delivery_review():
    reminder();c=prepare();o=out(c);client=TestClient(main.app)
    assert client.get('/api/recalls/'+c['id'],headers={'x-clinic-id':'clinic-river'}).status_code==404
    err(404,lambda:act('recall.cancel',{'id':c['id'],'version':c['version'],'reason':'test'},clinic='clinic-river',actor='clinic-river-admin'))
    r=client.get('/api/outbox/'+o['id']+'/delivery-review');assert r.status_code==200 and r.json()['body']==o['data']['body']
    practice=get('clinic-east');act('feature_locks.save',{'version':practice['version'],'actions':['message.queue']},actor=ADMIN)
    assert client.post('/api/recalls/preview',json=FILTER).status_code==403
    err(403,lambda:prepare())

def test_missing_or_legacy_snapshot_never_silently_delivers():
    reminder();c=prepare();o=out(c)
    with db.connection(True) as conn:
        data={k:v for k,v in o['data'].items() if k!='recall_snapshot'};db.update(conn,o,data)
    o=get(o['id']);err(409,lambda:act('message.complete',{'id':o['id'],'version':o['version']}))
    cancel(c);assert out(c)['data']['status']=='cancelled'


def test_owner_merge_preserves_optout_and_cancels_targets_pending_draft():
    opt_out();reminder('milo');c=prepare()
    source=get('owner-luna')
    act('owner.merge',{'id':source['id'],'version':source['version'],'target_id':'owner-milo'},actor=ADMIN)
    target=get('owner-milo')
    assert target['data']['recall_opt_out'] is True
    assert 'owner-luna' in target['data']['recall_preferences'][-1]['reason']
    assert out(c)['data']['status']=='cancelled'
    reminder();assert all(x['blocked_reason']=='Owner opted out of recalls' for x in preview()['items'])


def test_partial_batch_exception_rolls_back_campaign_outbox_and_reminder(monkeypatch):
    reminder();reminder('milo');before=rows(None);original=recalls.queue_one;calls=[]
    def interrupted(*a,**kw):
        if calls:raise RuntimeError('Synthetic write failure')
        calls.append(1);return original(*a,**kw)
    monkeypatch.setattr(recalls,'queue_one',interrupted)
    with pytest.raises(RuntimeError):prepare()
    assert rows(None)==before
