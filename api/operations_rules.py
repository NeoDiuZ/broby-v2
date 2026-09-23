"""Deterministic stock, scheduling and billing rules; no inferred clinic policy."""
from datetime import datetime,timedelta
from db import all_records,record,update,get

def lots(c,clinic,item):
    return [r for r in all_records(c,clinic,'stock_lot') if r['data']['inventory_id']==item['id']]

def ensure_lots(c,clinic,item):
    existing=lots(c,clinic,item)
    if not existing and item['data']['stock']:
        existing=[record(c,'stock_lot',clinic,{'inventory_id':item['id'],'batch':'Opening balance — no supplied lot','expiry':'','supplier':'Opening balance','remaining':item['data']['stock'],'opening':True})]
    return existing

def receive(c,clinic,actor,item,p,quantity):
    from actions import require,fail,owned
    from clinic_workflows import calendar_date
    ensure_lots(c,clinic,item)
    expiry=calendar_date(p.get('expiry'),'Expiry',optional=True) or ''
    batch=require(p,'batch');supplier=require(p,'supplier')
    po=None
    if p.get('purchase_order_id'):
        po=owned(c,p['purchase_order_id'],clinic,'purchase_order')
        if po['data']['inventory_id']!=item['id'] or po['data']['status']=='cancelled':fail('Purchase order does not match this delivery')
        if quantity>po['data']['quantity']-po['data'].get('received',0):fail('Delivery exceeds purchase order balance')
    existing=next((r for r in lots(c,clinic,item) if (r['data']['batch'],r['data']['expiry'],r['data']['supplier'])==(batch,expiry,supplier)),None)
    lot=update(c,existing,{**existing['data'],'remaining':existing['data']['remaining']+quantity}) if existing else record(c,'stock_lot',clinic,{'inventory_id':item['id'],'batch':batch,'expiry':expiry,'supplier':supplier,'remaining':quantity})
    if po:
        received=po['data'].get('received',0)+quantity
        update(c,po,{**po['data'],'received':received,'status':'received' if received==po['data']['quantity'] else 'partial'})
    return lot

def dispense(c,clinic,item,quantity):
    from actions import fail
    from clinic_workflows import clinic_today
    today=clinic_today(c,clinic).date().isoformat();available=ensure_lots(c,clinic,item)
    eligible=[r for r in available if r['data']['remaining']>0 and (not r['data']['expiry'] or r['data']['expiry']>=today)]
    eligible.sort(key=lambda r:(r['data']['expiry'] or '9999-12-31',r['created_at'],r['id']))
    if sum(r['data']['remaining'] for r in eligible)<quantity:fail('Insufficient unexpired stock; expired lots cannot be dispensed',409)
    allocations=[];needed=quantity
    for r in eligible:
        take=min(needed,r['data']['remaining'])
        if not take:break
        update(c,r,{**r['data'],'remaining':r['data']['remaining']-take})
        allocations.append({'lot_id':r['id'],'batch':r['data']['batch'],'expiry':r['data']['expiry'],'quantity':take})
        needed-=take
    return allocations

def adjust(c,clinic,actor,item,p,stock):
    from actions import fail,require,owned,integer
    current=ensure_lots(c,clinic,item)
    if len(current)>1 and not p.get('lot_id'):fail('Select a lot for a stocktake; total stock spans multiple lots')
    if p.get('lot_id'):
        lot=owned(c,p['lot_id'],clinic,'stock_lot')
        if lot['data']['inventory_id']!=item['id']:fail('Lot belongs to another stock item')
        count=integer(p.get('lot_count'),'Lot count')
        stock=item['data']['stock']-lot['data']['remaining']+count
        update(c,lot,{**lot['data'],'remaining':count})
    elif current:update(c,current[0],{**current[0]['data'],'remaining':stock})
    elif stock:record(c,'stock_lot',clinic,{'inventory_id':item['id'],'batch':'Stocktake — no supplied lot','expiry':'','supplier':'Stocktake','remaining':stock,'opening':True})
    record(c,'stock_adjustment',clinic,{'inventory_id':item['id'],'lot_id':p.get('lot_id'),'old_stock':item['data']['stock'],'new_stock':stock,'reason':require(p,'reason'),'actor':actor})
    return stock

def schedule(c,clinic,clinician,start,duration,room=''):
    from actions import owned,fail
    member=owned(c,clinician,clinic,'member')
    if not member['data'].get('active'):fail('Choose an active clinician')
    end=start+timedelta(minutes=duration)
    if start.date()!=end.date() or duration>1440:fail('Appointment must fit within one clinic day')
    config=get(c,'schedule-'+clinic,clinic)
    if not config:
        if room:fail('Configure rooms before assigning one')
        return
    data=config['data']
    if room and room not in data.get('rooms',[]):fail('Choose a configured room')
    rota=data.get('availability',{}).get(clinician)
    if rota is not None:
        windows=rota.get(str(start.weekday()),[])
        if not any(start.strftime('%H:%M')>=w['start'] and end.strftime('%H:%M')<=w['end'] for w in windows):fail('Appointment falls outside configured staff availability',409)
    for other in all_records(c,clinic,'appointment'):
        d=other['data']
        if not room or d.get('room')!=room or d['status'] in ('cancelled','completed'):continue
        other_start=datetime.fromisoformat(d['date']+'T'+d['time'])
        if start<other_start+timedelta(minutes=d['duration']) and other_start<end:fail('Room is already booked at this time',409)

def totals(items,p):
    from actions import integer,fail
    subtotal=sum(x['quantity']*x['price_cents'] for x in items)
    discount=integer(p.get('discount_cents',0),'Discount')
    tax_bps=integer(p.get('tax_bps',0),'Tax rate in basis points')
    if discount>subtotal:fail('Discount exceeds subtotal')
    if tax_bps>10000:fail('Tax rate must be at most 100 percent')
    taxable=subtotal-discount;tax=(taxable*tax_bps+5000)//10000
    return {'subtotal_cents':subtotal,'discount_cents':discount,'tax_bps':tax_bps,'tax_cents':tax,'total_cents':taxable+tax}
