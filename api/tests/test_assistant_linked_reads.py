"""Bounded factual breadth with current owner links and exact medication names."""
import pytest
from fastapi.testclient import TestClient
import assistant
import db
import main
import record_queries
from test_integrity import isolated, act, get, err
from test_record_queries import ask, query


def household():
    owner = act('owner.create', {'name': 'SYNTHETIC Read Household'})
    primary = act('patient.create', {'name': 'SYNTHETIC Linked Cat', 'species': 'Cat', 'owner_id': owner['id']})
    extra = act('patient.create', {'name': 'SYNTHETIC Linked Dog', 'species': 'Dog', 'owner_name': 'SYNTHETIC Other Household'})
    extra = act('patient.owners', {'id': extra['id'], 'version': extra['version'], 'owner_id': extra['data']['owner_id'], 'additional_owner_ids': [owner['id']]})
    return owner, primary, extra


def fact(c, kind, patient, **extra):
    data = {'patient_id': patient, 'status': 'issued' if kind == 'invoice' else 'due',
            'date': '2098-10-11', 'due': '2098-10-11', 'title': 'SYNTHETIC current-link read',
            'total_cents': 100, 'paid_cents': 0, **extra}
    return db.record(c, kind, 'clinic-east', data)


@pytest.mark.parametrize('kind', ['invoice', 'reminder'])
def test_owner_linked_finance_and_reminders_share_exact_filters_and_current_saved_view(monkeypatch, kind):
    owner, primary, extra = household()
    with db.connection(True) as c:
        first = fact(c, kind, primary['id']); second = fact(c, kind, extra['id'])
        fact(c, kind, 'luna', owner_id=owner['id'])  # Child-stored owner is not authority.
        fact(c, kind, primary['id'], date='2098-10-12', due='2098-10-12')
        fact(c, kind, primary['id'], status='void' if kind == 'invoice' else 'completed')
        foreign = db.record(c, 'patient', 'clinic-river', {'name': 'SYNTHETIC foreign pet', 'owner_id': owner['id']})
        for invalid in (foreign['id'], 'absent-patient', None, ['malformed']): fact(c, kind, invalid)
        malformed = db.record(c, 'patient', 'clinic-east', {'name': 'SYNTHETIC malformed link', 'additional_owner_ids': owner['id']})
        fact(c, kind, malformed['id'])
    status = 'issued' if kind == 'invoice' else 'due'
    planned = {'kind': kind, 'scope': 'clinic', 'owner_id': owner['id'], 'status': status, 'start': '2098-10-11', 'end': '2098-10-11', 'group_by': 'day'}
    if kind == 'invoice': planned['outstanding'] = True
    answer = ask(monkeypatch, f"Show {kind}s for patients currently linked to owner ID {owner['id']} whose status equals {status} on 2098-10-11", {'read': planned})
    assert {r['id'] for r in answer['sources']} == {first['id'], second['id']}
    assert 'current patient-owner links' in answer['text']
    view = act('dashboard.save', {'name': 'SYNTHETIC linked ' + kind, 'query': answer['dashboard']['query']})
    client = TestClient(main.app)
    saved = client.get('/api/dashboards/' + view['id']).json()['result']
    assert saved['query'] == answer['dashboard']['query'] and saved['count'] == 2
    assert saved['groups'] == [{'label': '2098-10-11', 'count': 2}]
    act('patient.owners', {'id': extra['id'], 'version': extra['version'], 'owner_id': extra['data']['owner_id'], 'additional_owner_ids': []})
    current = client.get('/api/dashboards/' + view['id']).json()['result']
    assert [r['id'] for r in current['records']] == [first['id']]
    assert answer['dashboard']['count'] == 2  # Saved answer remains a dated snapshot.
    with db.connection(True) as c: foreign_owner = db.record(c, 'owner', 'clinic-river', {'name': 'SYNTHETIC foreign owner'})
    err(404, lambda: query({'kind': kind, 'owner_id': foreign_owner['id']}))


@pytest.mark.parametrize('kind', ['invoice', 'reminder'])
def test_owner_linked_saved_views_resolve_reviewed_owner_merge(kind):
    owner, primary, _ = household()
    current = act('owner.create', {'name': 'SYNTHETIC Merged Household'})
    with db.connection(True) as c: row = fact(c, kind, primary['id'])
    view = act('dashboard.save', {'name': 'SYNTHETIC merge parity', 'query': {'kind': kind, 'owner_id': owner['id']}})
    act('owner.merge', {'id': owner['id'], 'version': owner['version'], 'target_id': current['id']}, actor='clinic-east-admin')
    direct = query({'kind': kind, 'owner_id': owner['id']})
    saved = TestClient(main.app).get('/api/dashboards/' + view['id']).json()['result']
    for result in (direct, saved):
        assert result['query']['owner_id'] == current['id'] and [r['id'] for r in result['records']] == [row['id']]
        assert 'SYNTHETIC Merged Household' in result['filter_summary']


@pytest.mark.parametrize('kind', ['invoice', 'reminder'])
@pytest.mark.parametrize('bad', ['omitted', 'substituted', 'unsupported_kind'])
def test_new_owner_queries_refuse_dropped_or_substituted_owner(monkeypatch, kind, bad):
    owner, _, _ = household()
    planned = {'kind': kind, 'owner_id': owner['id']}
    if bad == 'omitted': planned.pop('owner_id')
    if bad == 'substituted': planned['owner_id'] = 'owner-luna'
    if bad == 'unsupported_kind': planned['kind'] = 'payment'
    answer = ask(monkeypatch, f"Show {kind}s linked to owner ID {owner['id']}", {'read': planned})
    assert not answer.get('dashboard') and not answer['sources'] and not answer.get('action')


@pytest.mark.parametrize('kind', ['invoice', 'reminder'])
def test_owner_query_intersects_selected_patient_instead_of_widening(monkeypatch, kind):
    owner, primary, extra = household()
    with db.connection(True) as c:
        wanted = fact(c, kind, primary['id']); fact(c, kind, extra['id'])
    message = f"Show {kind}s for this patient linked to owner ID {owner['id']}"
    result = ask(monkeypatch, message, {'read': {'kind': kind, 'owner_id': owner['id']}}, primary['id'])
    assert result['dashboard']['source_ids'] == [wanted['id']]
    assert result['dashboard']['query']['patient_id'] == primary['id']
    dropped = ask(monkeypatch, message, {'read': {'kind': kind, 'owner_id': owner['id'], 'scope': 'clinic'}}, primary['id'])
    assert not dropped.get('dashboard') and not dropped['sources']


def test_invoice_owner_lookup_batches_more_than_sqlite_bind_limit_without_patient_scan(monkeypatch):
    owner = act('owner.create', {'name': 'SYNTHETIC Batch Owner'})
    with db.connection(True) as c:
        for number in range(501):
            patient = db.record(c, 'patient', 'clinic-east', {'name': f'SYNTHETIC Linked {number}', 'owner_id': owner['id']})
            fact(c, 'invoice', patient['id'])
    original = record_queries.all_records
    def bounded(c, clinic, kind=None):
        assert kind != 'patient', 'Join must fetch referenced clinic patients only.'
        return original(c, clinic, kind)
    monkeypatch.setattr(record_queries, 'all_records', bounded)
    result = query({'kind': 'invoice', 'owner_id': owner['id']})
    assert result['count'] == 501 and result['truncated'] and len(result['records']) == 100


def medication_rows():
    with db.connection(True) as c:
        records = {}
        for kind in ('medication', 'medication_history'):
            for name in ('SYNTHETIC Compound 5mg', 'SYNTHETIC Compound 50mg', 'SYNTHETIC Brand Alias'):
                records[kind, name] = db.record(c, kind, 'clinic-east', {'patient_id': 'luna', 'name': name, 'dose': 'Source-authored synthetic dose', 'frequency': 'Source frequency', 'instructions': 'SYNTHETIC only'})
            db.record(c, kind, 'clinic-river', {'patient_id': 'luna', 'name': 'SYNTHETIC Compound 5mg'})
            db.record(c, kind, 'clinic-east', {'patient_id': 'milo', 'name': 'SYNTHETIC Compound 5mg'})
    return records


@pytest.mark.parametrize('kind,label', [('medication', 'local prescriptions'), ('medication_history', 'imported medication history')])
def test_exact_medication_names_remain_kind_and_patient_scoped_with_saved_parity(monkeypatch, kind, label):
    records = medication_rows()
    planned = {'kind': kind, 'name': 'synthetic compound 5mg', 'group_by': 'name'}
    result = ask(monkeypatch, f'Show {label} whose recorded medication name equals "SYNTHETIC Compound 5mg" for this patient', {'read': planned}, 'luna')
    assert result['dashboard']['source_ids'] == [records[kind, 'SYNTHETIC Compound 5mg']['id']]
    assert ('local prescriptions' if kind == 'medication' else 'not a local prescription') in result['text']
    view = act('dashboard.save', {'name': 'SYNTHETIC exact medication', 'query': result['dashboard']['query']})
    saved = TestClient(main.app).get('/api/dashboards/' + view['id']).json()['result']
    assert saved['query'] == result['dashboard']['query'] and saved['count'] == 1
    assert saved['groups'] == [{'label': 'SYNTHETIC Compound 5mg', 'count': 1}]
    assert query({'kind': kind, 'name': 'SYNTHETIC Compound', 'patient_id': 'luna'})['count'] == 0


@pytest.mark.parametrize('kind,label', [('medication', 'local prescriptions'), ('medication_history', 'imported medication history')])
@pytest.mark.parametrize('bad', ['omitted', 'substituted_name', 'substituted_kind', 'unknown_name'])
def test_explicit_medication_selection_is_not_dropped_or_equated_by_model(monkeypatch, kind, label, bad):
    medication_rows()
    name = 'SYNTHETIC Unknown Drug' if bad == 'unknown_name' else 'SYNTHETIC Compound 5mg'
    planned = {'kind': kind, 'name': name}
    if bad == 'omitted': planned.pop('name')
    if bad == 'substituted_name': planned['name'] = 'SYNTHETIC Brand Alias'
    if bad == 'substituted_kind': planned['kind'] = 'medication_history' if kind == 'medication' else 'medication'
    result = ask(monkeypatch, f'Show {label} whose medication name equals "{name}"', {'read': planned}, 'luna')
    assert not result.get('dashboard') and not result['sources'] and not result.get('action')


def test_request_for_both_local_and_imported_medications_requires_separate_reads(monkeypatch):
    medication_rows()
    result = ask(monkeypatch, 'Show local prescriptions and imported medication history', {'read': {'kind': 'medication'}}, 'luna')
    assert not result.get('dashboard') and not result['sources']
