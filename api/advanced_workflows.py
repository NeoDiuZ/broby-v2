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
        from scheduling import configure
        return configure(c,clinic,p)
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


# Assistant and saved dashboards deliberately share the same validated executor.
from record_queries import validate_query, dashboard
