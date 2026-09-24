"""Clinic-scoped read models. Assistant and UI share these projections."""
from datetime import datetime,timedelta,date
from zoneinfo import ZoneInfo
import json,re
from db import all_records,get,unpack
from actions import owned,fail

def period(query,timezone='Asia/Singapore'):
    today=datetime.now(ZoneInfo(timezone)).date();q=query.lower()
    if 'yesterday' in q:return today-timedelta(days=1),today-timedelta(days=1)
    if 'last month' in q:
        end=today.replace(day=1)-timedelta(days=1);return end.replace(day=1),end
    if 'this month' in q:return today.replace(day=1),today
    if 'last week' in q:
        end=today-timedelta(days=today.weekday()+1);return end-timedelta(days=6),end
    if 'this week' in q:return today-timedelta(days=today.weekday()),today
    m=re.search(r'last\s+(\d+)\s+days?',q)
    if m:
        days=int(m[1])
        if not 1<=days<=3660:fail('Choose a date range of 1–3660 days')
        return today-timedelta(days=days-1),today
    if 'today' in q:return today,today
    return None,None

def handover(c,clinic,instant=None):
    from owner_conversations import handover_rows
    records=all_records(c,clinic);tz=get(c,clinic,clinic)['data'].get('timezone','Asia/Singapore');today=(instant or datetime.now(ZoneInfo(tz))).astimezone(ZoneInfo(tz)).date().isoformat()
    return {'date':today,'owner_conversations':handover_rows(c,clinic),'appointments':[r for r in records if r['kind']=='appointment' and r['data']['date']==today],
       'intakes':[r for r in records if r['kind']=='intake' and r['data']['status']=='new'],
       'reminders':[r for r in records if r['kind']=='reminder' and r['data']['status']=='due' and r['data']['due']<=today],
       'messages':[r for r in records if r['kind']=='outbox' and r['data']['status']=='pending'],
       'low_stock':[r for r in records if r['kind']=='inventory' and r['data']['unit']!='service' and r['data']['stock']<=r['data']['reorder']],
       'unfinished':[r for r in records if r['kind']=='consultation' and r['data']['status']!='reviewed' and not r['data'].get('archived')]}

def patient_records(c,clinic,patient_id,kind=None,category=None,start=None,end=None,query=''):
    owned(c,patient_id,clinic,'patient')
    from spine.reader import native_records
    records=all_records(c,clinic,kind)+[r for r in native_records(clinic,patient_id) if not kind or r['kind']==kind]
    rows=[r for r in records if r['data'].get('patient_id')==patient_id]
    def match(r):
        d=r['data'];when=d.get('occurred_at',r['created_at'])[:10]
        return (not category or d.get('category','').lower()==category.lower()) and (not start or when>=start) and (not end or when<=end) and (not query or query.lower() in json.dumps(d,ensure_ascii=False).lower())
    return [r for r in rows if match(r)]
