"""Prepare V1 consultation text for reviewed, private V2 migration.

No V1 database or service is opened. Patient grouping is supplied by a human
crosswalk because legacy consultation.patient_id may be NULL or a thread UUID
unrelated to the V1 patients table. Media must be migrated separately.
"""
import json
import re
from datetime import datetime

from v1_patient_mapping import MappingError, _text, _uuid


FIELDS = frozenset({
    'id', 'clinic_id', 'veterinarian_id', 'patient_id', 'ezyvet_animal_id',
    'patient_name', 'patient_species', 'patient_breed', 'patient_gender',
    'patient_age', 'patient_weight', 'patient_time', 'chief_complaint',
    'owner_name', 'owner_phone', 'owner_message_sent_at',
    'owner_message_sent_method', 'physical_exam', 'diagnosis',
    'treatment_plan', 'notes', 'ai_summary', 'ai_diagnosis_suggestions',
    'summary_language', 'recording_session_id', 'recording_session_ids',
    'recording_count', 'status', 'consultation_date', 'template_id',
    'custom_fields', 'consultation_metadata', 'created_at', 'updated_at',
    'deleted_at',
})
TEXT_FIELDS = (
    ('chief_complaint', 'Chief complaint'),
    ('physical_exam', 'Physical examination'),
    ('diagnosis', 'Recorded diagnosis'),
    ('treatment_plan', 'Recorded treatment plan'),
    ('notes', 'Additional notes'),
    ('ai_summary', 'Historical AI summary (unreviewed)'),
    ('ai_diagnosis_suggestions', 'Historical AI suggestions (not a V2 clinical conclusion)'),
)
STATUSES = {'draft', 'in_progress', 'completed', 'reviewed', 'archived'}
LANGUAGES = {'en', 'ja', 'zh', 'ko', 'th', 'vi'}


def _timestamp(value, label):
    raw = _text(value)
    try:
        result = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        raise MappingError(f'Invalid {label}; use a timezone-aware ISO timestamp') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise MappingError(f'Invalid {label}; a timezone is required')
    return result.isoformat()


def _json_field(value, label, expected):
    if value is None or value == '':
        return expected()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise MappingError(f'V1 {label} must be valid JSON') from None
    if not isinstance(value, expected):
        raise MappingError(f'V1 {label} must be a {"list" if expected is list else "JSON object"}')
    return value


def _reason(value, label):
    if not isinstance(value, str) or not 10 <= len(value.strip()) <= 1000:
        raise MappingError(f'{label} needs a 10–1000 character staff review reason')
    return value.strip()


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,100}', value):
        raise MappingError('Patient crosswalk keys must be stable 1–100 character references')
    return value


def _patient_mapping(row):
    if not isinstance(row, dict):
        raise MappingError('Every patient crosswalk entry must be an object')
    common = {'key', 'reason', 'confirm_thread_merge', 'confirm_species_conflict'}
    existing = {'target_patient_id', 'target_name', 'target_species', 'target_version'}
    fresh = {'name', 'species', 'owner_name', 'owner_phone', 'owner_email', 'reviewed_status'}
    key = _key(row.get('key'))
    reason = _reason(row.get('reason'), 'Patient identity mapping')
    if any(type(row.get(flag, False)) is not bool for flag in ('confirm_thread_merge', 'confirm_species_conflict')):
        raise MappingError('Identity-conflict acknowledgements must be true or false')
    if row.get('target_patient_id'):
        if set(row) - common - existing or set(row) & fresh:
            raise MappingError('Existing-patient mappings cannot create a second patient or owner')
        if not all(isinstance(row.get(name), str) and row[name].strip() for name in ('target_patient_id', 'target_name', 'target_species')):
            raise MappingError('Existing V2 patient ID, name and species must be reviewed')
        if type(row.get('target_version')) is not int or row['target_version'] < 1:
            raise MappingError('Existing V2 patient version must be reviewed')
    else:
        if set(row) - common - fresh or set(row) & existing:
            raise MappingError('New-patient mapping has unsupported or mixed target fields')
        if not all(isinstance(row.get(name), str) and row[name].strip() for name in ('name', 'species', 'owner_name')):
            raise MappingError('A new provisional patient needs reviewed patient and owner identity')
        if row.get('reviewed_status') != 'active':
            raise MappingError('A new provisional patient needs verified active status; other statuses require a separate mapping')
    return key, {**row, 'reason': reason}


def prepare(rows, crosswalk):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2400:
        raise MappingError('Provide 1–2400 V1 consultation rows per preview batch')
    if not isinstance(crosswalk, dict) or set(crosswalk) != {
        'source_clinic_id', 'target_clinic_id', 'reviewer', 'reviewed_at', 'patients', 'consultations'
    }:
        raise MappingError('Use a complete reviewed consultation crosswalk')
    source_clinic = _uuid(crosswalk['source_clinic_id'], 'source clinic ID')
    target_clinic = crosswalk['target_clinic_id']
    reviewer = crosswalk['reviewer']
    if (not isinstance(target_clinic,str) or not isinstance(reviewer,str) or
            not target_clinic.strip() or not reviewer.strip() or len(target_clinic) > 200 or len(reviewer) > 200):
        raise MappingError('Target V2 clinic and reviewer are required')
    target_clinic, reviewer = target_clinic.strip(), reviewer.strip()
    reviewed_at = _timestamp(crosswalk['reviewed_at'], 'crosswalk review time')
    if not isinstance(crosswalk['patients'], list) or not isinstance(crosswalk['consultations'], list):
        raise MappingError('Patient and consultation crosswalks must be lists')
    patients = dict(_patient_mapping(item) for item in crosswalk['patients'])
    if len(patients) != len(crosswalk['patients']):
        raise MappingError('Duplicate patient crosswalk key')
    assignments = {}
    for item in crosswalk['consultations']:
        if not isinstance(item, dict) or set(item) != {'id', 'patient_key', 'reason'}:
            raise MappingError('Every consultation needs an exact patient assignment and reason')
        id = _uuid(item['id'], 'consultation ID')
        if id in assignments:
            raise MappingError('Duplicate consultation crosswalk ID')
        key = _key(item['patient_key'])
        if key not in patients:
            raise MappingError('Consultation crosswalk names an unknown patient key')
        assignments[id] = (key, _reason(item['reason'], 'Consultation assignment'))
    originals = {}
    threads = {key: set() for key in patients}
    missing_threads = 0
    historical_ai = 0
    for row in rows:
        if not isinstance(row, dict):
            raise MappingError('Every V1 consultation row must be an object')
        unknown = set(row) - FIELDS
        if unknown:
            raise MappingError('Unmapped V1 consultation columns: ' + ', '.join(sorted(map(str, unknown))))
        missing = FIELDS - set(row)
        if missing:
            raise MappingError('Incomplete V1 consultation export columns: ' + ', '.join(sorted(missing)))
        id = _uuid(row.get('id'), 'consultation ID')
        if id in originals:
            raise MappingError('Duplicate V1 consultation ID')
        if _uuid(row.get('clinic_id'), 'consultation clinic ID') != source_clinic:
            raise MappingError('Mixed V1 clinics in consultation export')
        if id not in assignments:
            raise MappingError('Every consultation needs an explicit reviewed patient assignment')
        if _text(row.get('deleted_at')):
            raise MappingError('Soft-deleted consultations need a separate retention decision')
        if _text(row.get('status')) not in STATUSES:
            raise MappingError('V1 consultation status requires review')
        if _text(row.get('summary_language')) not in LANGUAGES:
            raise MappingError('V1 summary language requires review')
        _uuid(row.get('veterinarian_id'), 'veterinarian ID')
        for field in ('patient_name', 'patient_species'):
            if not _text(row.get(field)):
                raise MappingError(f'Missing V1 {field}; identity review is required')
        when = _timestamp(row.get('consultation_date'), 'consultation date')
        created_at = _timestamp(row.get('created_at'), 'V1 creation time')
        updated_at = _timestamp(row.get('updated_at'), 'V1 update time')
        sent_at = _timestamp(row['owner_message_sent_at'], 'owner-message marker') if row.get('owner_message_sent_at') else None
        sessions = _json_field(row.get('recording_session_ids'), 'recording_session_ids', list)
        count = row.get('recording_count')
        if isinstance(count, bool):
            raise MappingError('V1 recording count requires review')
        try:
            count = int(count or 0)
        except (ValueError, TypeError):
            raise MappingError('V1 recording count requires review') from None
        if count < 0 or _text(count) != _text(row.get('recording_count') or 0):
            raise MappingError('V1 recording count requires review')
        metadata = _json_field(row.get('consultation_metadata'), 'consultation_metadata', dict)
        if _text(row.get('recording_session_id')) or sessions or count or metadata:
            raise MappingError('Linked V1 audio/files/metadata need a reviewed media export before this consultation can be prepared')
        custom = _json_field(row.get('custom_fields'), 'custom_fields', dict)
        for field, _ in TEXT_FIELDS:
            if row.get(field) is not None and not isinstance(row[field], str):
                raise MappingError(f'V1 {field} must be text')
        key, _ = assignments[id]
        expected_species = patients[key].get('target_species') or patients[key].get('species')
        if (_text(row['patient_species']).casefold() != _text(expected_species).casefold() and
                not patients[key].get('confirm_species_conflict')):
            raise MappingError('V1 consultation and reviewed target species differ; acknowledge the conflict or correct the assignment')
        if row.get('patient_id'):
            threads[key].add(_uuid(row['patient_id'], 'consultation patient thread ID'))
        else:
            missing_threads += 1
        historical_ai += bool(_text(row.get('ai_diagnosis_suggestions')))
        originals[id] = {**row, 'id': id, 'clinic_id': source_clinic,
                         'consultation_date': when, 'recording_session_ids': sessions,
                         'recording_count': count, 'custom_fields': custom,
                         'consultation_metadata': metadata, 'created_at':created_at,
                         'updated_at':updated_at, 'owner_message_sent_at':sent_at}
    if set(assignments) != set(originals) or set(patients) != {key for key, _ in assignments.values()}:
        raise MappingError('Crosswalk must cover exactly these consultations and used patients')
    for key, ids in threads.items():
        if len(ids) > 1 and not patients[key].get('confirm_thread_merge'):
            raise MappingError('Multiple V1 patient threads need explicit merge acknowledgement')
    source_system = 'broby-v1:consultations-text:' + source_clinic
    records = []
    assertions = []
    for key, mapping in sorted(patients.items()):
        if mapping.get('target_patient_id'):
            assertions.append({'id':mapping['target_patient_id'], 'kind':'patient',
                               'version':mapping['target_version'], 'name':mapping['target_name'],
                               'species':mapping['target_species']})
        else:
            owner_id = 'owner:' + key
            records.append({'kind':'owner', 'id':owner_id, 'data':{
                'name':_text(mapping['owner_name']), 'phone':_text(mapping.get('owner_phone')),
                'email':_text(mapping.get('owner_email')), 'identity_review':'provisional_from_v1_consultations',
                'v1_patient_key':key, 'reviewed_by':reviewer, 'reviewed_at':reviewed_at,
                'mapping_reason':mapping['reason']}})
            records.append({'kind':'patient', 'id':'patient:' + key, 'data':{
                'name':_text(mapping['name']), 'species':_text(mapping['species']),
                'owner_id':owner_id, 'v1_patient_key':key, 'reviewed_by':reviewer,
                'reviewed_at':reviewed_at, 'mapping_reason':mapping['reason'],
                'v1_status_review':'active', 'identity_review':'provisional_from_v1_consultations',
                'thread_merge_acknowledged':mapping.get('confirm_thread_merge',False),
                'species_conflict_acknowledged':mapping.get('confirm_species_conflict',False)}})
    if len({a['id'] for a in assertions}) != len(assertions):
        raise MappingError('Two patient crosswalk keys cannot silently target the same V2 patient')
    for id, row in sorted(originals.items()):
        key, reason = assignments[id]
        patient_id = patients[key].get('target_patient_id') or 'patient:' + key
        title = 'Historical V1 consultation · ' + row['consultation_date'][:10]
        lines = ['Historical V1 consultation text, private and unapproved in V2.',
                 'Original consultation ID: ' + id,
                 'Original status: ' + row['status'],
                 'Original date: ' + row['consultation_date'],
                 'Original patient: ' + _text(row['patient_name']) + ' · ' + _text(row['patient_species']),
                 'Original owner: ' + (_text(row.get('owner_name')) or 'not recorded'),
                 'V1 patient thread ID: ' + (_text(row.get('patient_id')) or 'not recorded'),
                 'Staff patient assignment: ' + key + ' · ' + reason]
        if row.get('ezyvet_animal_id'):
            lines.append('Original ezyVet animal ID: ' + _text(row['ezyvet_animal_id']))
        if row.get('veterinarian_id'):
            lines.append('Original veterinarian ID: ' + _text(row['veterinarian_id']))
        if row.get('owner_message_sent_at'):
            lines.append('V1 owner-message marker (delivery unverified): ' + _text(row['owner_message_sent_at']) +
                         ' · ' + _text(row.get('owner_message_sent_method')))
        for field, label in TEXT_FIELDS:
            if row.get(field):
                lines.extend(('', label + ':', row[field]))
        if row['custom_fields']:
            lines.extend(('', 'Original custom fields (JSON):',
                          json.dumps(row['custom_fields'], sort_keys=True, ensure_ascii=False)))
        source_id = 'source:' + id
        records.append({'kind':'source', 'id':source_id, 'data':{
            'patient_id':patient_id, 'title':title, 'text':'\n'.join(lines),
            'section':'Subjective', 'category':'consultation', 'author':'V1 consultation export',
            'v1_consultation_id':id, 'v1_original':row, 'reviewed_by':reviewer,
            'reviewed_at':reviewed_at, 'assignment_reason':reason,
            'patient_mapping_reason':patients[key]['reason'],
            'thread_merge_acknowledged':patients[key].get('confirm_thread_merge',False),
            'species_conflict_acknowledged':patients[key].get('confirm_species_conflict',False)}})
        records.append({'kind':'event', 'id':'event:' + id, 'data':{
            'patient_id':patient_id, 'category':'consultation', 'title':title,
            'body':'Historical consultation text is linked as an unapproved staff source. Review before owner sharing.',
            'occurred_at':row['consultation_date'], 'source_ids':[source_id], 'approved':False,
            'v1_consultation_id':id}})
    if len(records) > 5000:
        raise MappingError('This batch exceeds V2 migration preview capacity; split it without changing patient keys')
    return {'source_system':source_system, 'target_clinic_id':target_clinic,
            'reference_assertions':assertions, 'records':records,
            'review':{'consultations':len(originals), 'new_provisional_patients':sum(not p.get('target_patient_id') for p in patients.values()),
                      'existing_patient_links':len(assertions), 'missing_v1_thread_ids':missing_threads,
                      'historical_ai_suggestions_for_review':historical_ai, 'media_imported':0,
                      'reviewer':reviewer, 'reviewed_at':reviewed_at}}
