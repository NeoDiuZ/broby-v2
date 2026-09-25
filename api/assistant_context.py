"""Bounded selection metadata for intent planning, never a factual read limit.

Exact IDs/names and their references outrank recent records. Counts and answers
still use the complete deterministic read executor after intent interpretation.
"""
import json
import re
from db import json_text, unpack

MAX_RECORDS = 250
MAX_CHARACTERS = 140000
MAX_FIELD_CHARACTERS = 4000

MODEL_KINDS = ('patient','owner','member','inventory','template','invoice','payment',
               'consultation','appointment','reminder','outbox','intake','recording',
               'settings','clinic','purchase_order','credit_note',
               'credit_note_reversal','source','dashboard','staff_leave','schedule',
               'attachment','recall_campaign','handover','owner_thread')


def candidates(c, clinic, message, patient_id=None, identified=()):
    """Fetch bounded planning metadata plus exact targets, never clinical history.

    The final factual query is separate and must read the complete requested kind.
    Exact matches are found in the clinic database so an old target is not lost
    merely because the clinic has more than MAX_RECORDS recent records.
    """
    placeholders=','.join('?' for _ in MODEL_KINDS)
    scope=(clinic,*MODEL_KINDS)
    rows={}
    def add(found):
        for row in found:
            item=unpack(row)
            rows[item['id']]=item
    base=f'FROM records WHERE clinic_id=? AND kind IN ({placeholders})'
    add(c.execute('SELECT * '+base+' ORDER BY created_at DESC LIMIT ?',(*scope,MAX_RECORDS)))
    add(c.execute('SELECT * '+base+" AND kind IN ('clinic','settings','member','template')",scope))
    for item in identified:
        if item:rows[item['id']]=item
    if patient_id:
        patient_field=json_text(c,'data','patient_id')
        add(c.execute('SELECT * '+base+f' AND {patient_field}=? ORDER BY created_at DESC LIMIT ?',
                      (*scope,patient_id,MAX_RECORDS)))
    # Exact names/IDs are checked again with token boundaries by select().
    # This database search only removes rows which cannot possibly match.
    needle=message.casefold()
    substring='strpos' if c.dialect=='postgres' else 'instr'
    expressions=['id',*(json_text(c,'data',field) for field in ('name','title','number'))]
    where=' OR '.join(f'{substring}(?,lower({field}))>0' for field in expressions)
    add(c.execute('SELECT * '+base+f' AND ({where})',(*scope,*(needle for _ in expressions))))
    # Include referenced records in the bounded model candidate set. This does
    # not authorize access: all lookups retain the same clinic predicate.
    for _ in range(2):
        referenced={value for row in rows.values() for key,value in row['data'].items()
                    if key.endswith('_id') and isinstance(value,str) and value not in rows}
        if not referenced:break
        for ids in (list(referenced)[i:i+400] for i in range(0,len(referenced),400)):
            slots=','.join('?' for _ in ids)
            add(c.execute('SELECT * '+base+f' AND id IN ({slots})',(*scope,*ids)))
    total=c.execute('SELECT count(*) '+base,scope).fetchone()[0]
    return list(rows.values()),total


def select(records, message, patient_id=None, available_records=None):
    by_id = {r['id']: r for r in records}
    explicit, related = set(), set()
    request = message.casefold()
    for r in records:
        candidates = [r['id'], *[r['data'].get(k, '') for k in ('name', 'title', 'number')]]
        if any(isinstance(value, str) and len(value) >= 3 and re.search(r'(?<!\w)' + re.escape(value.casefold()) + r'(?!\w)', request) for value in candidates):
            explicit.add(r['id'])
        if patient_id and (r['id'] == patient_id or r['data'].get('patient_id') == patient_id):
            related.add(r['id'])
    preferred = explicit | related
    # Include exact referenced owners, patients, stock and consultations before
    # unrelated recent rows. Never search another clinic's records here.
    for _ in range(3):
        for id in list(preferred):
            row = by_id.get(id)
            if not row: continue
            for key, value in row['data'].items():
                if key.endswith('_id') and isinstance(value, str) and value in by_id: preferred.add(value)
    def rank(r):
        if r['id'] in explicit: return 0
        if r['id'] == patient_id: return 1
        if r['id'] in preferred and r['id'] not in related: return 2
        if r['kind'] in ('clinic', 'settings', 'member', 'template'): return 3
        if r['id'] in related: return 4
        return 5
    chosen, size, omitted_fields = [], 0, 0
    for r in sorted(records, key=rank):
        data, omitted = {}, []
        for key, value in r['data'].items():
            if len(json.dumps(value, ensure_ascii=False)) > MAX_FIELD_CHARACTERS:
                omitted.append(key)
            else: data[key] = value
        row = {'id': r['id'], 'kind': r['kind'], 'version': r['version'], 'data': data}
        if omitted: row['omitted_fields'] = omitted
        length = len(json.dumps(row, ensure_ascii=False))
        if len(chosen) >= MAX_RECORDS or size + length > MAX_CHARACTERS: continue
        chosen.append(row); size += length; omitted_fields += len(omitted)
    total=available_records if available_records is not None else len(records)
    return chosen, {'selection_only': True, 'available_records': total, 'included_records': len(chosen),
                    'omitted_records': max(0,total - len(chosen)), 'omitted_large_fields': omitted_fields,
                    'characters': size, 'limit': MAX_RECORDS}
