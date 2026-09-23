import uuid

import pytest
from fastapi.testclient import TestClient

import assistant
import assistant_history
import assistant_operations
import db
import main
from test_integrity import isolated, act, get, rows, err


def proposal(monkeypatch, name, payload, patient=None, actor='clinic-east-admin'):
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    monkeypatch.setattr(assistant.providers, 'model_json', lambda *a: {'action': {'action': name, 'payload': payload}})
    return assistant_history.ask('clinic-east', actor, 'Synthetic explicit operator request', patient, None, str(uuid.uuid4()))


def confirm(turn, expected=200, actor='clinic-east-admin'):
    response = TestClient(main.app).post(f"/api/assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm", headers={'x-actor-id': actor})
    assert response.status_code == expected, response.text
    return response.json()


def fixtures():
    reminder = act('reminder.create', {'patient_id': 'luna', 'title': 'Synthetic recall', 'due': '2098-07-10'})
    recording = act('recording.create', {'patient_id': 'luna', 'consultation_id': 'consult-luna'})
    item = rows('inventory')[0]
    order = act('purchase_order.create', {'inventory_id': item['id'], 'supplier': 'Synthetic supplier', 'quantity': 10}, actor='clinic-east-admin')
    handover = act('handover.prepare', {})
    patient = get('luna')
    owner = act('owner.create', {'name': 'Synthetic second owner'})
    return reminder, recording, item, order, handover, patient, owner


def snapshot():
    with db.connection() as c:
        return [tuple(r) for r in c.execute('SELECT * FROM records ORDER BY id')], c.execute('SELECT count(*) FROM audit').fetchone()[0]


@pytest.mark.parametrize('name', list(assistant_operations.CONTRACTS))
def test_typed_proposals_do_not_write_until_saved_confirmation_and_replay_once(monkeypatch, name):
    reminder, recording, item, order, handover, patient, owner = fixtures()
    target = lambda r: {'id': r['id'], 'version': r['version']}
    payloads = {
        'reminder.create': {'patient_id': 'luna', 'title': 'New recall', 'due': '2098-07-11'},
        'reminder.update': {**target(reminder), 'title': 'Edited recall', 'due': '2098-07-12'},
        'reminder.cancel': target(reminder), 'reminder.complete': target(reminder),
        'purchase_order.create': {'inventory_id': item['id'], 'supplier': 'Explicit supplier', 'quantity': 12},
        'purchase_order.cancel': {**target(order), 'reason': 'Duplicate order'},
        'recording.rename': {**target(recording), 'title': 'Owner follow-up'},
        'patient.owners': {**target(patient), 'owner_id': patient['data']['owner_id'], 'additional_owner_ids': [owner['id']]},
        'handover.prepare': {}, 'handover.acknowledge': {'id': handover['id']},
    }
    before = snapshot()
    turn = proposal(monkeypatch, name, payloads[name])
    assert snapshot() == before
    expected_payload = payloads[name] if name != 'handover.prepare' else {'expected_date': handover['data']['date']}
    assert turn['action'] == {'action': name, 'payload': expected_payload}
    assert turn['review']['title'] and turn['review']['fields'] and turn['review']['effects']
    first = confirm(turn)
    data = first['data']
    expected = {
        'reminder.create': {'title': 'New recall', 'due': '2098-07-11', 'status': 'due'},
        'reminder.update': {'title': 'Edited recall', 'due': '2098-07-12'},
        'reminder.cancel': {'status': 'cancelled'}, 'reminder.complete': {'status': 'completed'},
        'purchase_order.create': {'supplier': 'Explicit supplier', 'quantity': 12, 'received': 0},
        'purchase_order.cancel': {'status': 'cancelled', 'reason': 'Duplicate order'},
        'recording.rename': {'title': 'Owner follow-up'},
        'patient.owners': {'additional_owner_ids': [owner['id']]},
        'handover.prepare': {'date': handover['data']['date']},
    }
    for key, value in expected.get(name, {}).items():
        assert data[key] == value
    if name == 'handover.acknowledge':
        assert [a['actor_id'] for a in data['acknowledged_by']] == ['clinic-east-admin']
    after = snapshot()
    assert confirm(turn) == first and snapshot() == after
    with db.connection() as c:
        saved = assistant_history.present(c.execute('SELECT * FROM assistant_turns WHERE id=?', (turn['turn_id'],)).fetchone())
        assert saved['review'] == turn['review'] and saved['execution'] == first
        assert c.execute('SELECT count(*) FROM mutations WHERE key=?', ('assistant-confirm:' + turn['turn_id'],)).fetchone()[0] == 1


@pytest.mark.parametrize('name,payload', [
    ('purchase_order.create', {'inventory_id': 'missing', 'supplier': 'Supplier', 'quantity': value})
    for value in [True, 1.5, '2', 0, -1]
] + [
    ('reminder.create', {'patient_id': 'luna', 'title': 'Recall', 'due': '2098-02-30'}),
    ('reminder.create', {'patient_id': 'luna', 'title': ' ', 'due': '2098-02-28'}),
    ('reminder.create', {'patient_id': 'luna', 'title': 'Recall', 'due': '2098-02-28', 'send_now': True}),
    ('reminder.cancel', {'id': 'luna', 'version': True}),
    ('reminder.update', {'id': 'luna', 'version': 1, 'title': 'Incomplete'}),
    ('patient.owners', {'id': 'luna', 'version': 1, 'owner_id': 'someone'}),
    ('patient.owners', {'id': 'luna', 'version': 1, 'owner_id': 'someone', 'additional_owner_ids': ['same', 'same']}),
    ('recording.rename', {'id': 'luna', 'version': 1, 'title': 'x' * 161}),
    ('handover.prepare', {'acknowledged': True}),
])
def test_invalid_model_fields_become_clarification_without_confirmable_action(monkeypatch, name, payload):
    before = snapshot()
    turn = proposal(monkeypatch, name, payload)
    assert 'action' not in turn and 'required fields and types' in turn['text']
    assert snapshot() == before
    confirm(turn, 409)


def test_reference_scope_kind_patient_and_current_version_are_checked(monkeypatch):
    reminder, recording, item, order, handover, patient, owner = fixtures()
    foreign = act('reminder.create', {'patient_id': 'milo', 'title': 'Foreign patient', 'due': '2098-01-01'})
    with db.connection(True) as c:
        other = db.record(c, 'reminder', 'clinic-river', {'patient_id': 'luna', 'title': 'Foreign clinic', 'due': '2098-01-01', 'status': 'due'})
    for name, payload, patient_context in [
        ('reminder.cancel', {'id': other['id'], 'version': 1}, None),
        ('reminder.cancel', {'id': 'luna', 'version': 1}, None),
        ('reminder.cancel', {'id': foreign['id'], 'version': 1}, 'luna'),
        ('reminder.cancel', {'id': reminder['id'], 'version': 999}, None),
        ('recording.rename', {'id': recording['id'], 'version': 1, 'title': 'Wrong patient'}, 'milo'),
        ('patient.owners', {'id': 'luna', 'version': 1, 'owner_id': 'missing', 'additional_owner_ids': []}, None),
    ]:
        turn = proposal(monkeypatch, name, payload, patient_context)
        assert 'action' not in turn
    act('reminder.complete', {'id': reminder['id'], 'version': 1})
    assert 'action' not in proposal(monkeypatch, 'reminder.cancel', {'id': reminder['id'], 'version': 2})


def test_reminder_change_cancels_old_draft_and_confirmation_rechecks_version(monkeypatch):
    reminder = act('reminder.create', {'patient_id': 'luna', 'title': 'Synthetic due recall', 'due': '2000-01-01'})
    act('reminder.queue_due', {})
    reminder = get(reminder['id']); outbox = get(reminder['data']['outbox_id'])
    payload = {'id': reminder['id'], 'version': reminder['version'], 'title': 'Moved recall', 'due': '2098-07-10'}
    turn = proposal(monkeypatch, 'reminder.update', payload, 'luna')
    assert 'No message will be sent.' in turn['review']['effects']
    assert get(outbox['id'])['data']['status'] == 'pending'
    changed = confirm(turn)
    assert changed['data']['due'] == '2098-07-10' and 'outbox_id' not in changed['data']
    assert get(outbox['id'])['data']['status'] == 'cancelled'
    next_turn = proposal(monkeypatch, 'reminder.cancel', {'id': changed['id'], 'version': changed['version']})
    act('reminder.complete', {'id': changed['id'], 'version': changed['version']})
    confirm(next_turn, 409)
    assert get(changed['id'])['data']['status'] == 'completed'


def test_partial_order_cancellation_does_not_undo_received_stock(monkeypatch):
    item = rows('inventory')[0]
    order = act('purchase_order.create', {'inventory_id': item['id'], 'supplier': 'Synthetic supplier', 'quantity': 10}, actor='clinic-east-admin')
    act('inventory.receive', {'id': item['id'], 'version': item['version'], 'quantity': 3, 'batch': 'Synthetic batch', 'supplier': 'Synthetic supplier', 'purchase_order_id': order['id']}, actor='clinic-east-admin')
    order = get(order['id']); stock = get(item['id'])
    turn = proposal(monkeypatch, 'purchase_order.cancel', {'id': order['id'], 'version': order['version'], 'reason': 'Cancel remaining seven'})
    assert {'label': 'Already received', 'value': '3'} in turn['review']['fields']
    assert confirm(turn)['data']['status'] == 'cancelled'
    assert get(item['id']) == stock
    assert 'action' not in proposal(monkeypatch, 'purchase_order.cancel', {'id': order['id'], 'version': order['version'] + 1, 'reason': 'Again'})


def test_owner_review_is_complete_and_revokes_only_on_confirmation(monkeypatch):
    patient = get('luna'); owner = act('owner.create', {'name': 'Synthetic additional owner'})
    grant = act('share.create', {'patient_id': 'luna'})
    payload = {'id': 'luna', 'version': patient['version'], 'owner_id': patient['data']['owner_id'], 'additional_owner_ids': [owner['id']]}
    turn = proposal(monkeypatch, 'patient.owners', payload, 'luna')
    assert 'revokes' in turn['review']['effects'][0]
    assert TestClient(main.app).get('/api/owner/' + grant['id']).status_code == 200
    confirm(turn)
    assert get('luna')['data']['additional_owner_ids'] == [owner['id']]
    assert TestClient(main.app).get('/api/owner/' + grant['id']).status_code == 404


def test_catalog_and_confirmation_follow_roles_locks_and_current_context(monkeypatch):
    reminder, recording, item, order, handover, patient, owner = fixtures()
    seen = []
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    monkeypatch.setattr(assistant.providers, 'model_json', lambda _, p: seen.append(p) or {'clarify': True})
    with db.connection() as c:
        assistant.answer(c, 'clinic-east', 'clinic-east-nurse', 'What can I do?')
    catalog = seen[0]['allowed_actions']
    assert 'purchase_order.create' not in catalog and 'patient.owners' in catalog
    assert catalog['reminder.update']['payload_schema']['additionalProperties'] is False
    assert any(r['id'] == order['id'] for r in seen[0]['records'])
    entry = next(r for r in seen[0]['records'] if r['id'] == handover['id'])
    assert 'snapshot' not in entry['data']
    turn = proposal(monkeypatch, 'recording.rename', {'id': recording['id'], 'version': recording['version'], 'title': 'Reviewed title'}, actor='clinic-east-nurse')
    practice = get('clinic-east')
    act('feature_locks.save', {'version': practice['version'], 'actions': ['source.add']}, actor='clinic-east-admin')
    confirm(turn, 403, actor='clinic-east-nurse')
    assert get(recording['id'])['data'].get('title') != 'Reviewed title'


def test_handover_confirmation_cannot_silently_move_to_the_next_clinic_date(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import clinic_workflows
    original = clinic_workflows.clinic_today
    first_day = datetime(2098, 7, 10, 23, 59, tzinfo=ZoneInfo('Asia/Singapore'))
    next_day = datetime(2098, 7, 11, 0, 1, tzinfo=ZoneInfo('Asia/Singapore'))
    monkeypatch.setattr(clinic_workflows, 'clinic_today', lambda c, clinic, instant=None: original(c, clinic, instant or first_day))
    turn = proposal(monkeypatch, 'handover.prepare', {})
    assert turn['action']['payload']['expected_date'] == '2098-07-10'
    monkeypatch.setattr(clinic_workflows, 'clinic_today', lambda c, clinic, instant=None: original(c, clinic, instant or next_day))
    confirm(turn, 409)
    assert not rows('handover')
