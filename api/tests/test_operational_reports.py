"""Full-clinic operational counts, calendar boundaries and private export."""
import csv
import io
from datetime import date

from fastapi.testclient import TestClient

import db
import main
import operational_reports as reports
from test_integrity import isolated


def built():
    with db.connection(snapshot=True) as c:
        return reports.build(c, 'clinic-east', 1, as_of=date(2026, 9, 25))


def by_status(result, kind, status):
    return next((row['count'] for row in result[kind]['by_status'] if row['label'] == status), 0)


def test_full_clinic_report_respects_clinic_zone_and_foreign_records():
    before = built()
    with db.connection(True) as c:
        owner = db.record(c, 'owner', 'clinic-east', {'name': 'SYNTHETIC report owner'})
        db.record(c, 'patient', 'clinic-east', {'name': 'SYNTHETIC report patient', 'species': 'Dog',
                                                'owner_id': owner['id']})
        db.record(c, 'patient', 'clinic-east', {'name': 'SYNTHETIC orphan', 'species': 'Bird',
                                                'owner_id': 'missing-owner'})
        db.record(c, 'patient', 'clinic-river', {'name': 'SYNTHETIC foreign', 'species': 'Dog'})
        for timestamp, status in [('2026-09-24T15:59:59+00:00', 'reviewed'),
                                  ('2026-09-24T16:00:00+00:00', 'reviewed'),
                                  ('2026-09-25T15:59:59+00:00', 'in_progress'),
                                  ('2026-09-25T16:00:00+00:00', 'reviewed')]:
            row = db.record(c, 'consultation', 'clinic-east', {'status': status})
            c.execute('UPDATE records SET created_at=? WHERE id=?', (timestamp, row['id']))
        db.record(c, 'appointment', 'clinic-east', {'date': '2026-09-25', 'status': 'completed'})
        db.record(c, 'appointment', 'clinic-east', {'date': '2026-09-24', 'status': 'cancelled'})
        db.record(c, 'reminder', 'clinic-east', {'due': '2026-09-25', 'status': 'due'})
        row = db.record(c, 'outbox', 'clinic-east', {'status': 'pending'})
        c.execute('UPDATE records SET created_at=? WHERE id=?', ('2026-09-24T16:00:00+00:00', row['id']))
        db.record(c, 'intake', 'clinic-east', {'status': 'new'})
        db.record(c, 'inventory', 'clinic-east', {'unit': 'pack', 'stock': 1, 'reorder': 2})
        db.record(c, 'inventory', 'clinic-east', {'unit': 'pack', 'stock': 'bad', 'reorder': 2})
        c.execute('INSERT INTO jobs(id,clinic_id,consultation_id,status,payload,created_at,updated_at) '
                  'VALUES(?,?,?,?,?,?,?)', ('report-job', 'clinic-east', '', 'failed', '{}', db.now(), db.now()))
    after = built()
    assert (after['start'], after['end'], after['timezone']) == ('2026-09-25', '2026-09-25', 'Asia/Singapore')
    assert after['patients']['total'] == before['patients']['total'] + 2
    assert after['patients']['linked_to_owner'] == before['patients']['linked_to_owner'] + 1
    assert after['owners_total'] == before['owners_total'] + 1
    assert after['consultations']['total'] == before['consultations']['total'] + 2
    assert by_status(after, 'consultations', 'reviewed') == by_status(before, 'consultations', 'reviewed') + 1
    assert by_status(after, 'consultations', 'in_progress') == by_status(before, 'consultations', 'in_progress') + 1
    assert by_status(after, 'appointments', 'completed') == by_status(before, 'appointments', 'completed') + 1
    assert by_status(after, 'appointments', 'cancelled') == by_status(before, 'appointments', 'cancelled')
    assert by_status(after, 'reminders', 'due') == by_status(before, 'reminders', 'due') + 1
    assert by_status(after, 'messages', 'pending') == by_status(before, 'messages', 'pending') + 1
    assert after['open_intakes'] == before['open_intakes'] + 1
    assert after['failed_or_conflicting_jobs'] == before['failed_or_conflicting_jobs'] + 1
    assert after['stock']['low'] == before['stock']['low'] + 1
    assert after['stock']['invalid'] == before['stock']['invalid'] + 1


def test_api_and_csv_export_share_full_clinic_counts_and_require_all_reads():
    with TestClient(main.app, headers={'x-actor-id': 'clinic-east-admin'}) as client:
        response = client.get('/api/reports/operations?days=7')
        assert response.status_code == 200
        report = response.json()
        exported = client.get('/api/reports/operations/export?days=7')
        assert exported.status_code == 200
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        assert next(row['Value'] for row in rows if row['Metric'] == 'Patients registered, all time') == str(report['patients']['total'])
        assert next(row['Value'] for row in rows if row['Metric'] == 'Appointments scheduled, period') == str(report['appointments']['total'])
        assert all(row['Period start'] == report['start'] and row['Period end'] == report['end'] for row in rows)
    with db.connection(True) as c:
        member = db.get(c, 'clinic-east-vet')
        db.update(c, member, {**member['data'], 'read_restrictions': ['read.billing']})
    with TestClient(main.app, headers={'x-actor-id': 'clinic-east-vet'}) as client:
        assert client.get('/api/reports/operations?days=7').status_code == 403
        assert client.get('/api/reports/operations/export?days=7').status_code == 403


def test_malformed_legacy_values_are_counted_without_breaking_the_report():
    with db.connection(True) as c:
        db.record(c, 'patient', 'clinic-east', {'name': 'SYNTHETIC malformed legacy',
                                               'species': 0, 'owner_id': 'unknown'})
        db.record(c, 'consultation', 'clinic-east', {'status': 0})
        c.execute("INSERT INTO records(id,kind,clinic_id,data,version,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?)", ('malformed-report-stock', 'inventory', 'clinic-east',
                                              '[]', 1, db.now(), db.now()))
    report = built()
    assert any(group == {'label': '0', 'count': 1} for group in report['patients']['by_species'])
    assert any(group == {'label': '0', 'count': 1} for group in report['consultations']['by_status'])
    assert report['stock']['invalid'] >= 1


def test_invalid_clinic_timezone_is_an_actionable_configuration_error():
    with db.connection(True) as c:
        clinic = db.get(c, 'clinic-east')
        db.update(c, clinic, {**clinic['data'], 'timezone': None})
    with TestClient(main.app, headers={'x-actor-id': 'clinic-east-admin'}) as client:
        response = client.get('/api/reports/operations?days=7')
        assert response.status_code == 409
        assert 'timezone' in response.json()['detail']
