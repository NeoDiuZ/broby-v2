"""One validated, deterministic read contract for assistant answers and saved views."""
import math
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError, model_validator
from db import all_records, get, now, unpack
from billing import outstanding

RecordKind = Literal['patient','event','observation','medication','medication_history','invoice','payment','inventory','appointment','reminder','intake','outbox','consultation']
READ_KINDS = set(RecordKind.__args__)
OWNER_LINK_KINDS = {'patient', 'appointment', 'invoice', 'reminder'}
NAMED_KINDS = {'patient', 'observation', 'inventory', 'medication', 'medication_history'}


class RecordQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: RecordKind
    record_id: StrictStr | None = Field(default=None, min_length=1, max_length=100, description='One exact record ID supplied by the operator. Intersects clinic, kind, patient and all other filters; never broadens a missing or foreign ID into a list.')
    text_contains: StrictStr | None = Field(default=None, min_length=1, max_length=500, description='Literal case-insensitive substring in an event title or recorded body. Events only; no synonyms, semantic search, regular expressions or clinical inference.')
    patient_id: StrictStr | None = Field(default=None, max_length=100)
    owner_id: StrictStr | None = Field(default=None, min_length=1, max_length=100, description='Exact clinic owner ID; matches current same-clinic primary or additional patient links for patients, appointments, invoices and reminders. This is a current relationship filter, not historical invoice ownership or payment liability.')
    start: StrictStr | None = None
    end: StrictStr | None = None
    category: StrictStr | None = Field(default=None, max_length=120)
    name: StrictStr | None = Field(default=None, max_length=200, description='Exact recorded patient, observation, inventory or medication name, ignoring case. Local medication and imported medication_history remain separate kinds. No substring, synonym, brand/generic or drug-equivalence match.')
    species: StrictStr | None = Field(default=None, min_length=1, max_length=120, description='Exact recorded patient species, ignoring case.')
    clinician: StrictStr | None = Field(default=None, min_length=1, max_length=100, description='Exact recorded appointment clinician ID.')
    code: StrictStr | None = Field(default=None, max_length=120, description='Exact recorded observation concept code.')
    unit: StrictStr | None = Field(default=None, max_length=80, description='Exact recorded unit; no conversion.')
    status: StrictStr | None = Field(default=None, max_length=80, description='Exact recorded workflow status.')
    low_stock: StrictBool = False
    outstanding: StrictBool = False
    value_min: StrictFloat | StrictInt | None = Field(default=None, allow_inf_nan=False)
    value_max: StrictFloat | StrictInt | None = Field(default=None, allow_inf_nan=False)
    value_equals: StrictBool | StrictFloat | StrictInt | StrictStr | None = None
    group_by: Literal['auto','category','status','species','name','clinician','day'] = 'auto'

    @model_validator(mode='after')
    def meaningful_filters(self):
        if self.text_contains is not None and (self.kind!='event' or not self.text_contains.strip()):
            raise ValueError('Literal text search requires events and a nonblank phrase')
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
        if self.name and self.kind not in NAMED_KINDS:
            raise ValueError('Name does not apply to this record kind')
        if self.species and self.kind not in {'patient','appointment'}:raise ValueError('Species requires patients or appointments')
        if self.owner_id and self.kind not in OWNER_LINK_KINDS:raise ValueError('Owner links require patients, appointments, invoices or reminders')
        if self.clinician and self.kind!='appointment':raise ValueError('Clinician requires appointments')
        if self.group_by=='species' and self.kind not in {'patient','appointment'}:raise ValueError('Species grouping requires patients or appointments')
        if self.group_by=='clinician' and self.kind!='appointment':raise ValueError('Clinician grouping requires appointments')
        if self.group_by=='name' and self.kind not in NAMED_KINDS:
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
    if parsed.owner_id:
        owner=owned(c,parsed.owner_id,clinic,'owner')
        merged_into=owner['data'].get('merged_into')
        if merged_into:
            current=owned(c,merged_into,clinic,'owner')
            if current['id']==owner['id'] or current['data'].get('merged_into'):
                fail('Owner merge chain needs review before querying linked records',409)
            parsed.owner_id=current['id']
    return parsed.model_dump(exclude_none=True,exclude_defaults=True)


def record_day(row, tz):
    data=row['data']
    # Scheduling/due dates are clinic calendar dates, not ingestion timestamps.
    value=(data.get('due') if row['kind']=='reminder' else None) or data.get('date') or data.get('occurred_at') or row['created_at']
    if isinstance(value,str) and len(value)==10:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return row['created_at'][:10]
    try:
        instant=datetime.fromisoformat(value.replace('Z','+00:00'))
        if instant.tzinfo is None:instant=instant.replace(tzinfo=timezone.utc)
        return instant.astimezone(ZoneInfo(tz)).date().isoformat()
    except (ValueError,TypeError,AttributeError):
        return row['created_at'][:10]


def query_summary(query, patient=None, owner=None):
    parts=[patient['data']['name'] if patient else 'Whole clinic']
    if query.get('start') or query.get('end'):parts.append(f"{query.get('start') or 'earliest'} to {query.get('end') or 'latest'}")
    for key in ('category','name','species','clinician','code','unit','status'):
        if query.get(key):parts.append(f"{key.replace('_',' ')}: {query[key]}")
    if query.get('record_id'):parts.append('record ID: '+query['record_id'])
    if query.get('text_contains'):parts.append('event title/body contains literal text: '+repr(query['text_contains']))
    if query.get('owner_id'):
        parts.append('owner: '+(owner['data']['name'] if owner else query['owner_id']))
        if query['kind'] in {'invoice', 'reminder'}:parts.append('current patient-owner links')
    if query['kind'] in {'medication', 'medication_history'}:
        parts.append('local prescriptions' if query['kind']=='medication' else 'externally recorded medication history; not a local prescription')
    if query.get('low_stock'):parts.append('stock at or below reorder level')
    if query.get('outstanding'):parts.append('positive outstanding balance, excluding void invoices')
    for key,label in [('value_min','value at least'),('value_max','value at most'),('value_equals','value equals')]:
        if key in query:parts.append(f'{label}: {query[key]}')
    if query.get('group_by'):parts.append('grouped by '+query['group_by'])
    return ' · '.join(parts)


def _linked_patients(c, clinic, records):
    """Fetch only referenced same-clinic patients, bounded by SQLite's bind limit."""
    ids=sorted({patient_id for row in records
                if row['clinic_id']==clinic and row['kind'] in OWNER_LINK_KINDS-{'patient'}
                for patient_id in [row['data'].get('patient_id')]
                if isinstance(patient_id,str) and patient_id})
    linked={}
    for offset in range(0,len(ids),500):
        batch=ids[offset:offset+500]
        sql='SELECT * FROM records WHERE clinic_id=? AND kind=? AND id IN ('+','.join('?' for _ in batch)+')'
        for row in c.execute(sql,(clinic,'patient',*batch)):
            patient=unpack(row)
            linked[patient['id']]=patient['data']
    return linked


def select_records(c, clinic, query, records=None):
    from spine.reader import native_records
    query=validate_query(c,query,clinic)
    if records is None:
        records=all_records(c,clinic,query['kind'])
        if query['kind'] in {'event','observation'}:
            records+=native_records(clinic,query.get('patient_id'))
    from clinical_reconciliation import current_records
    records=current_records(c,clinic,records,clinical_use=True)
    needs_patient_links=(query['kind'] in OWNER_LINK_KINDS-{'patient'} and query.get('owner_id')) or (query['kind']=='appointment' and (query.get('species') or query.get('group_by')=='species'))
    linked_patients=_linked_patients(c,clinic,records) if needs_patient_links else {}
    def linked_patient(data):
        patient_id=data.get('patient_id')
        return linked_patients.get(patient_id) if isinstance(patient_id,str) else None
    def linked_species(data):
        patient=linked_patient(data)
        return patient.get('species') if patient else None
    def linked_to_owner(data):
        additional=data.get('additional_owner_ids')
        return data.get('owner_id')==query['owner_id'] or isinstance(additional,list) and query['owner_id'] in additional
    tz=get(c,clinic,clinic)['data'].get('timezone','Asia/Singapore')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        from actions import fail
        fail('The clinic timezone must be configured before querying records',409)
    selected=[]
    for r in records:
        if r['clinic_id']!=clinic or r['kind']!=query['kind']:continue
        if query.get('record_id') and r['id']!=query['record_id']:continue
        d=r['data'];day=record_day(r,tz)
        if query.get('text_contains') and not any(isinstance(d.get(field),str) and query['text_contains'].casefold() in d[field].casefold() for field in ('title','body')):continue
        if query.get('patient_id') and r['id']!=query['patient_id'] and d.get('patient_id')!=query['patient_id']:continue
        if query.get('owner_id'):
            owner_patient=d if query['kind']=='patient' else linked_patient(d)
            if not owner_patient or not linked_to_owner(owner_patient):continue
        if any(query.get(k) and str(d.get(k,'')).casefold()!=query[k].casefold() for k in ('category','name','code','status')):continue
        if query.get('species'):
            species=d.get('species') if query['kind']=='patient' else linked_species(d)
            if not isinstance(species,str) or species.casefold()!=query['species'].casefold():continue
        if query.get('clinician') and d.get('clinician')!=query['clinician']:continue
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
        if group=='day':label=record_day(r,tz)
        elif group=='species' and query['kind']=='appointment':label=linked_species(d)
        elif group!='auto':label=d.get(group)
        else:label=d.get('category') or d.get('status') or d.get('species') or query['kind']
        label=str(label) if label not in (None,'') else 'Not recorded'
        groups[label]=groups.get(label,0)+1
    patient=get(c,query['patient_id'],clinic) if query.get('patient_id') else None
    owner=get(c,query['owner_id'],clinic) if query.get('owner_id') else None
    return {'query':query,'count':len(selected),'groups':[{'label':k,'count':v} for k,v in sorted(groups.items())],
            'records':selected,'filter_summary':query_summary(query,patient,owner),'timezone':tz,'refreshed_at':now()}


def dashboard(c,clinic,query):
    result=select_records(c,clinic,query)
    return {**result,'records':result['records'][:100],'record_limit':100,'truncated':result['count']>100}
