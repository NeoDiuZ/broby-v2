"""Prepare a reviewed V1 patient-table export for V2's existing migration preview.

This module never connects to V1. It rejects rows requiring identity or clinical
decisions rather than silently dropping patients or inventing historical visits.
"""
import json
import math
import re
from datetime import date
from uuid import UUID


class MappingError(ValueError):
    pass


SOURCE = 'broby-v1:patients'
FIELDS = frozenset({
    'id', 'clinic_id', 'name', 'species', 'breed', 'age', 'weight', 'sex',
    'microchip_id', 'color', 'date_of_birth', 'owner_name', 'owner_phone',
    'owner_email', 'owner_address', 'status', 'last_visit', 'custom_fields',
    'notes', 'deleted_at', 'created_at', 'updated_at',
})


def _uuid(value, label):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise MappingError(f'Invalid {label} in V1 patient export') from None


def _text(value):
    return str(value).strip() if value is not None else ''


def _weight(value):
    if value is None or _text(value) == '':
        return 0, True
    if isinstance(value, bool):
        raise MappingError('V1 weight requires review')
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        matched = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:kg)?', _text(value), re.I)
        if not matched:
            raise MappingError('V1 weight requires review; only explicit kilograms are accepted')
        number = float(matched.group(1))
    if not math.isfinite(number) or number < 0:
        raise MappingError('V1 weight requires review')
    return number, False


def prepare(rows, *, source_clinic_id):
    clinic = _uuid(source_clinic_id, 'source clinic ID')
    if not isinstance(rows, list) or not rows or len(rows) > 1600:
        raise MappingError('Provide 1–1600 V1 patient rows per preview')
    seen = set()
    records = []
    missing_weights = 0
    for row in rows:
        if not isinstance(row, dict):
            raise MappingError('Every V1 patient row must be an object')
        unknown = set(row) - FIELDS
        if unknown:
            raise MappingError('Unmapped V1 patient columns: ' + ', '.join(sorted(map(str, unknown))))
        patient_id = _uuid(row.get('id'), 'patient ID')
        if patient_id in seen:
            raise MappingError('Duplicate V1 patient ID')
        seen.add(patient_id)
        if _uuid(row.get('clinic_id'), 'patient clinic ID') != clinic:
            raise MappingError('Mixed V1 clinics in patient export')
        if _text(row.get('deleted_at')):
            raise MappingError('Soft-deleted V1 patients require an explicit cutover decision')
        if _text(row.get('status') or 'active') != 'active':
            raise MappingError('Inactive or deceased V1 patients require a reviewed status mapping')
        for field in ('name', 'species', 'owner_name'):
            if not _text(row.get(field)):
                raise MappingError(f'Missing V1 {field}; identity review is required')
        sex = _text(row.get('sex')) or 'Unknown'
        if sex not in ('Male', 'Female', 'Unknown'):
            raise MappingError('V1 sex value requires review')
        weight, missing = _weight(row.get('weight'))
        missing_weights += missing
        dob = row.get('date_of_birth')
        if dob:
            try:
                dob = date.fromisoformat(_text(dob)).isoformat()
            except ValueError:
                raise MappingError('V1 date of birth requires review') from None
        custom = row.get('custom_fields') or {}
        if isinstance(custom, str):
            try:
                custom = json.loads(custom)
            except json.JSONDecodeError:
                raise MappingError('V1 custom fields must be JSON') from None
        if not isinstance(custom, dict):
            raise MappingError('V1 custom fields must be an object')
        if row.get('notes') is not None and not isinstance(row['notes'], str):
            raise MappingError('V1 patient notes must be text')
        owner_id = 'owner:' + patient_id
        records.append({'kind': 'owner', 'id': owner_id, 'data': {
            'name': _text(row['owner_name']), 'phone': _text(row.get('owner_phone')),
            'email': _text(row.get('owner_email')), 'address': _text(row.get('owner_address')),
            'v1_patient_id': patient_id, 'identity_review': 'not_reconciled',
        }})
        data = {
            'name': _text(row['name']), 'species': _text(row['species']),
            'breed': _text(row.get('breed')), 'age': _text(row.get('age')),
            'weight': weight, 'sex': sex, 'owner_id': owner_id,
            'microchip_id': _text(row.get('microchip_id')), 'color': _text(row.get('color')),
            'v1_status': 'active', 'v1_last_visit': _text(row.get('last_visit')),
            'v1_created_at': _text(row.get('created_at')),
            'v1_updated_at': _text(row.get('updated_at')),
            'v1_custom_fields': custom,
        }
        if dob:
            data['date_of_birth'] = dob
        records.append({'kind': 'patient', 'id': patient_id, 'data': data})
        if _text(row.get('notes')):
            records.append({'kind': 'source', 'id': 'note:' + patient_id, 'data': {
                'patient_id': patient_id, 'title': 'V1 patient general notes',
                'text': str(row['notes']), 'section': 'Subjective',
                'category': 'clinical', 'author': 'V1 patient record',
            }})
    if len(records) > 5000:
        raise MappingError('A migration preview can contain at most 5000 records')
    return {
        'source_system': SOURCE, 'source_clinic_id': clinic, 'records': records,
        'review': {'patients': len(rows), 'owners_pending_identity_reconciliation': len(rows),
                   'missing_weights': missing_weights,
                   'notes_as_unapproved_sources': sum(r['kind'] == 'source' for r in records),
                   'visits_imported': 0, 'files_imported': 0,
                   'financial_or_stock_records_imported': 0},
    }
