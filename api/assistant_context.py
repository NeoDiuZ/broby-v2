"""Bounded selection metadata for intent planning, never a factual read limit.

Exact IDs/names and their references outrank recent records. Counts and answers
still use the complete deterministic read executor after intent interpretation.
"""
import json
import re

MAX_RECORDS = 250
MAX_CHARACTERS = 140000
MAX_FIELD_CHARACTERS = 4000


def select(records, message, patient_id=None):
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
    return chosen, {'selection_only': True, 'available_records': len(records), 'included_records': len(chosen),
                    'omitted_records': len(records) - len(chosen), 'omitted_large_fields': omitted_fields,
                    'characters': size, 'limit': MAX_RECORDS}
