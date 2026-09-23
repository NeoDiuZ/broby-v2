"""One validated, deterministic read contract for assistant answers and saved views."""
import math
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError, model_validator
from db import all_records, get, now
from billing import outstanding

RecordKind = Literal['patient','event','observation','medication','medication_history','invoice','payment','inventory','appointment','reminder','intake','outbox','consultation']
READ_KINDS = set(RecordKind.__args__)


class RecordQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: RecordKind
    patient_id: StrictStr | None = Field(default=None, max_length=100)
    start: StrictStr | None = None
    end: StrictStr | None = None
    category: StrictStr | None = Field(default=None, max_length=120)
    name: StrictStr | None = Field(default=None, max_length=200, description='Exact recorded name, ignoring case. No substring match.')
    code: StrictStr | None = Field(default=None, max_length=120, description='Exact recorded observation concept code.')
    unit: StrictStr | None = Field(default=None, max_length=80, description='Exact recorded unit; no conversion.')
    status: StrictStr | None = Field(default=None, max_length=80, description='Exact recorded workflow status.')
    low_stock: StrictBool = False
    outstanding: StrictBool = False
    value_min: StrictFloat | StrictInt | None = Field(default=None, allow_inf_nan=False)
    value_max: StrictFloat | StrictInt | None = Field(default=None, allow_inf_nan=False)
    value_equals: StrictBool | StrictFloat | StrictInt | StrictStr | None = None
    group_by: Literal['auto','category','status','species','name','day'] = 'auto'

    @model_validator(mode='after')
    def meaningful_filters(self):
        if isinstance(self.value_equals,float) and not math.isfinite(self.value_equals):
            raise ValueError('Equality values must be finite')
        if isinstance(self.value_equals,str) and len(self.value_equals)>300:
            raise ValueError('Equality text must not exceed 300 characters')
        for field in ('start','end'):
            value=getattr(self,field)
            if value:
                if len(value)!=10 or date.fromisoformat(value).isoformat()!=value:
                    raise ValueError('Use YYYY-MM-DD calendar dates')
        if self.start and self.end and self.start>self.end:
            raise ValueError('Start date must not follow end date')
        if self.low_stock and self.kind!='inventory':raise ValueError('Low stock requires inventory')
        if self.outstanding and self.kind!='invoice':raise ValueError('Outstanding balance requires invoices')
        if self.code or self.unit or any(v is not None for v in (self.value_min,self.value_max,self.value_equals)):
            if self.kind!='observation':raise ValueError('Value, code and unit filters require observations')
        if any(v is not None for v in (self.value_min,self.value_max,self.value_equals)) and not self.code:
            raise ValueError('Choose an exact observation code before filtering values')
        if (self.value_min is not None or self.value_max is not None) and not self.unit:
            raise ValueError('Numeric comparisons require an exact recorded unit')
        if self.value_min is not None and self.value_max is not None and self.value_min>self.value_max:
            raise ValueError('Minimum must not exceed maximum')
        if self.value_equals is not None and (self.value_min is not None or self.value_max is not None):
            raise ValueError('Use equality or a range, not both')
        if self.status and self.kind not in {'invoice','appointment','reminder','intake','outbox','consultation'}:
            raise ValueError('Status does not apply to this record kind')
        if self.name and self.kind not in {'patient','observation','inventory'}:
            raise ValueError('Name does not apply to this record kind')
        if self.group_by=='species' and self.kind!='patient':raise ValueError('Species grouping requires patients')
        if self.group_by=='name' and self.kind not in {'patient','observation','inventory'}:
            raise ValueError('Name grouping does not apply to this record kind')
        return self


def validate_query(c, query, clinic):
    from actions import fail, owned
    try:
        parsed=RecordQuery.model_validate(query)
    except ValidationError as exc:
        # Never echo model-supplied payloads or record contents in validation errors.
        details='; '.join(str(e['msg']) for e in exc.errors(include_input=False))
        fail('Invalid record query: '+details)
    if parsed.patient_id:owned(c,parsed.patient_id,clinic,'patient')
    return parsed.model_dump(exclude_none=True,exclude_defaults=True)


def record_day(row, tz):
    data=row['data']
    # Scheduling/due dates are clinic calendar dates, not ingestion timestamps.
    value=(data.get('due') if row['kind']=='reminder' else None) or data.get('date') or data.get('occurred_at') or row['created_at']
    if len(value)==10:return value
    try:
        instant=datetime.fromisoformat(value.replace('Z','+00:00'))
        if instant.tzinfo is None:instant=instant.replace(tzinfo=timezone.utc)
        return instant.astimezone(ZoneInfo(tz)).date().isoformat()
    except (ValueError,TypeError):
        return row['created_at'][:10]


def query_summary(query, patient=None):
    parts=[patient['data']['name'] if patient else 'Whole clinic']
    if query.get('start') or query.get('end'):parts.append(f"{query.get('start') or 'earliest'} to {query.get('end') or 'latest'}")
    for key in ('category','name','code','unit','status'):
        if query.get(key):parts.append(f"{key.replace('_',' ')}: {query[key]}")
    if query.get('low_stock'):parts.append('stock at or below reorder level')
    if query.get('outstanding'):parts.append('positive outstanding balance, excluding void invoices')
    for key,label in [('value_min','value at least'),('value_max','value at most'),('value_equals','value equals')]:
        if key in query:parts.append(f'{label}: {query[key]}')
    if query.get('group_by'):parts.append('grouped by '+query['group_by'])
    return ' · '.join(parts)


def select_records(c, clinic, query, records=None):
    from spine.reader import native_records
    query=validate_query(c,query,clinic)
    if records is None:
        records=all_records(c,clinic,query['kind'])
        if query['kind'] in {'event','observation'}:
            records+=native_records(clinic,query.get('patient_id'))
    tz=get(c,clinic,clinic)['data'].get('timezone','Asia/Singapore')
    selected=[]
    for r in records:
        if r['clinic_id']!=clinic or r['kind']!=query['kind']:continue
        d=r['data'];day=record_day(r,tz)
        if query.get('patient_id') and r['id']!=query['patient_id'] and d.get('patient_id')!=query['patient_id']:continue
        if any(query.get(k) and str(d.get(k,'')).casefold()!=query[k].casefold() for k in ('category','name','code','status')):continue
        if query.get('unit') and d.get('unit')!=query['unit']:continue
        if query.get('start') and day<query['start'] or query.get('end') and day>query['end']:continue
        if query.get('low_stock') and (d.get('unit')=='service' or d.get('stock',0)>d.get('reorder',0)):continue
        if query.get('outstanding') and not outstanding(d):continue
        value=d.get('value')
        if 'value_equals' in query:
            expected=query['value_equals']
            if isinstance(value,bool)!=isinstance(expected,bool) or value!=expected:continue
        if 'value_min' in query or 'value_max' in query:
            if isinstance(value,bool) or not isinstance(value,(int,float)):continue
            if 'value_min' in query and value<query['value_min'] or 'value_max' in query and value>query['value_max']:continue
        selected.append(r)
    selected.sort(key=lambda r:(record_day(r,tz),r['created_at'],r['id']),reverse=True)
    groups={}
    for r in selected:
        d=r['data'];group=query.get('group_by','auto')
        label=record_day(r,tz) if group=='day' else d.get(group) if group!='auto' else d.get('category') or d.get('status') or d.get('species') or query['kind']
        label=str(label) if label not in (None,'') else 'Not recorded'
        groups[label]=groups.get(label,0)+1
    patient=get(c,query['patient_id'],clinic) if query.get('patient_id') else None
    return {'query':query,'count':len(selected),'groups':[{'label':k,'count':v} for k,v in sorted(groups.items())],
            'records':selected,'filter_summary':query_summary(query,patient),'timezone':tz,'refreshed_at':now()}


def dashboard(c,clinic,query):
    result=select_records(c,clinic,query)
    return {**result,'records':result['records'][:100],'record_limit':100,'truncated':result['count']>100}
