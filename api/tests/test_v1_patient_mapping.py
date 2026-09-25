"""V1 patient identity prep is read-only, fail-closed and replayable in V2."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import db
from test_integrity import act, isolated, rows
from v1_patient_mapping import MappingError, prepare

CLINIC = '11111111-1111-4111-8111-111111111111'


def patient(identifier, name, *, notes='', weight='4.6 kg'):
    return {
        'id': identifier, 'clinic_id': CLINIC, 'name': name, 'species': 'Cat',
        'breed': 'Domestic', 'sex': 'Female', 'weight': weight,
        'owner_name': 'SYNTHETIC Same Name', 'owner_phone': '+65 8000 1234',
        'owner_email': 'synthetic@example.test', 'date_of_birth': '2022-04-03',
        'notes': notes, 'status': 'active', 'custom_fields': {'legacy': 'exact'},
    }


def test_v1_rows_rehearse_replay_without_false_owner_merge_or_public_note():
    first = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    second = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    prepared = prepare([patient(first, 'SYNTHETIC Miso', notes='Exact V1 general note.'),
                        patient(second, 'SYNTHETIC Nori')], source_clinic_id=CLINIC)
    assert prepared['review']['owners_pending_identity_reconciliation'] == 2
    payload = {'source_system': prepared['source_system'], 'records': prepared['records']}
    preview = act('migration.preview', payload, actor='clinic-east-admin')
    assert preview['counts'] == {'owner': 2, 'patient': 2, 'source': 1}
    assert preview['new_count'] == 5
    applied = act('migration.apply', {**payload, 'expected_digest': preview['digest']},
                  actor='clinic-east-admin')
    assert applied['applied'] and applied['new_count'] == 5
    imported = [r for r in rows('patient') if r['data'].get('migration_origin', {}).get('source_system') == prepared['source_system']]
    assert len(imported) == 2
    assert len({p['data']['owner_id'] for p in imported}) == 2
    assert {p['data']['migration_origin']['source_id'] for p in imported} == {first, second}
    source = next(r for r in rows('source') if r['data'].get('migration_origin', {}).get('source_id') == 'note:' + first)
    assert source['data']['text'] == 'Exact V1 general note.'
    assert source['data']['patient_id'] in {p['id'] for p in imported}
    assert act('migration.preview', payload, actor='clinic-east-admin')['unchanged_count'] == 5


@pytest.mark.parametrize('change', [
    {'clinic_id': '22222222-2222-4222-8222-222222222222'},
    {'owner_name': ''}, {'status': 'deceased'}, {'deleted_at': '2025-01-01'},
    {'weight': '10 lb'}, {'notes': {'not': 'text'}},
    {'unexpected_medical_field': 'must not disappear'},
])
def test_unreviewed_v1_rows_cannot_generate_a_partial_import(change):
    row = patient('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'SYNTHETIC Miso')
    with pytest.raises(MappingError):
        prepare([{**row, **change}], source_clinic_id=CLINIC)
    assert not [r for r in rows('patient') if r['data'].get('migration_origin', {}).get('source_system') == 'broby-v1:patients']


def test_converter_writes_private_preview_and_refuses_overwrite(tmp_path):
    path = tmp_path / 'approved-synthetic-export.json'
    target = tmp_path / 'private-preview.json'
    path.write_text(json.dumps([patient('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'SYNTHETIC Miso')]))
    script = Path(__file__).resolve().parents[2] / 'scripts/prepare-v1-patients.py'
    command = [sys.executable, str(script), str(path), str(target), '--source-clinic-id', CLINIC]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())['review']['patients'] == 1
    assert subprocess.run(command, capture_output=True, text=True).returncode != 0
