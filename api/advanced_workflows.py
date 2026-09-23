"""Hard workflows use the same authorization, transaction and audit boundary as UI actions."""
import json,hashlib
from datetime import datetime,timezone,timedelta,date
from db import record,get,update,all_records,now,uid
PERMISSIONS={
 'clinical.ingest':{'vet','nurse','admin'},'clinical.approve':{'vet','admin'},
 'schedule.configure':{'admin'},'purchase_order.create':{'admin'},'purchase_order.cancel':{'admin'},
 'dashboard.save':{'vet','nurse','admin'},'dashboard.delete':{'vet','nurse','admin'},
}

def dispatch(c,a,p,clinic,actor):
    from actions import owned,require,version,fail
    if a=='clinical.ingest':
        from spine import database,projection,service
        from spine.contracts import EventInput
        from pydantic import ValidationError
        try:payload=EventInput.model_validate(p)
        except ValidationError as e:fail(str(e))
        # Ingest owns the PostgreSQL transaction and its clinic-wide unique dedupe key.
        # If local audit acknowledgement fails, replay returns the same event.
        projection.sync(clinic)
        with database.session() as s,s.begin():return service.ingest(s,clinic,payload,payload.event_type)
    if a=='clinical.approve':
        from spine import database
        from spine.models import Event
        from sqlalchemy import select
        with database.session() as s,s.begin():
            e=s.scalar(select(Event).where(Event.id==require(p,'id'),Event.clinic_id==clinic).with_for_update())
            if not e:fail('Clinical event not found',404)
            if e.payload_hash=='legacy':fail('Approve the originating consultation or attachment')
            e.body={**e.body,'owner_approved':p.get('approved') is True,'approved_by':actor,'approved_at':now()}
        return {'id':p['id'],'approved':p.get('approved') is True}
    if a=='purchase_order.create':
        from actions import integer
        item=owned(c,require(p,'inventory_id'),clinic,'inventory')
        return record(c,'purchase_order',clinic,{'inventory_id':item['id'],'supplier':require(p,'supplier'),'quantity':integer(p.get('quantity'),'Quantity',1),'received':0,'status':'ordered','ordered_by':actor})
    if a=='purchase_order.cancel':
        r=owned(c,p['id'],clinic,'purchase_order');version(r,p)
        if r['data']['status']=='received':fail('A fully received order cannot be cancelled')
        return update(c,r,{**r['data'],'status':'cancelled','reason':require(p,'reason')})
    if a=='schedule.configure':
        rooms=p.get('rooms',[]);availability=p.get('availability',{})
        if not isinstance(rooms,list) or len(rooms)>100 or any(not isinstance(x,str) or not x.strip() for x in rooms) or len(set(rooms))!=len(rooms):fail('Provide unique room names')
        if not isinstance(availability,dict):fail('Invalid staff availability')
        for member,days in availability.items():
            owned(c,member,clinic,'member')
            if not isinstance(days,dict):fail('Availability must map weekdays 0–6 to time windows')
            for day,windows in days.items():
                if day not in list('0123456') or not isinstance(windows,list):fail('Invalid weekday or windows')
                for window in windows:
                    try:
                        start=datetime.strptime(window['start'],'%H:%M');end=datetime.strptime(window['end'],'%H:%M')
                    except (ValueError,TypeError,KeyError):fail('Use HH:MM start and end times')
                    if start>=end:fail('Availability start must precede end')
                    window['start']=start.strftime('%H:%M');window['end']=end.strftime('%H:%M')
        r=get(c,'schedule-'+clinic,clinic);data={'rooms':rooms,'availability':availability}
        if r:version(r,p);return update(c,r,data)
        return record(c,'schedule',clinic,data,'schedule-'+clinic)
    if a=='dashboard.save':
        query=validate_query(c,p.get('query'),clinic)
        data={'name':require(p,'name'),'query':query,'created_by':actor}
        if p.get('id'):
            r=owned(c,p['id'],clinic,'dashboard');version(r,p)
            return update(c,r,data)
        return record(c,'dashboard',clinic,data)
    if a=='dashboard.delete':
        r=owned(c,p['id'],clinic,'dashboard');version(r,p)
        return update(c,r,{**r['data'],'archived':True})
    fail('Unknown advanced action',404)

def validate_query(c,query,clinic):
    from actions import fail,owned
    from assistant import READ_KINDS
    if not isinstance(query,dict) or set(query)-{'kind','patient_id','start','end','category'}:fail('Invalid saved query')
    if query.get('kind') not in READ_KINDS:fail('Unsupported query kind')
    if query.get('patient_id'):owned(c,query['patient_id'],clinic,'patient')
    for key in ('start','end'):
        if query.get(key):
            try:date.fromisoformat(query[key])
            except (TypeError,ValueError):fail('Invalid query date')
    if query.get('start') and query.get('end') and query['start']>query['end']:fail('Invalid query date range')
    if not isinstance(query.get('category',''),str):fail('Invalid category')
    return query

def dashboard(c,clinic,query):
    from spine.reader import native_records
    query=validate_query(c,query,clinic);kind=query['kind']
    rows=[r for r in all_records(c,clinic,kind)+native_records(clinic,query.get('patient_id')) if r['kind']==kind]
    selected=[]
    for r in rows:
        d=r['data'];when=(d.get('occurred_at') or d.get('date') or r['created_at'])[:10]
        if query.get('patient_id') and r['id']!=query['patient_id'] and d.get('patient_id')!=query['patient_id']:continue
        if query.get('category') and d.get('category','').lower()!=query['category'].lower():continue
        if query.get('start') and when<query['start'] or query.get('end') and when>query['end']:continue
        selected.append(r)
    groups={}
    for r in selected:
        label=r['data'].get('category') or r['data'].get('status') or r['data'].get('species') or kind
        groups[label]=groups.get(label,0)+1
    return {'count':len(selected),'groups':[{'label':k,'count':v} for k,v in sorted(groups.items())],'records':selected[:100],'record_limit':100,'refreshed_at':now()}
