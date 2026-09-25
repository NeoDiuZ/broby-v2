"""Synthetic end-to-end proposals for reviewed recall batches and internal alerts."""
import uuid

import pytest
from fastapi.testclient import TestClient

import assistant
import assistant_history
import db
import main
import owner_conversations
from test_integrity import isolated, act, get, rows
from test_assistant_operations import proposal, confirm, snapshot


def recall_fixture(patient='luna', count=2):
    reminders = [act('reminder.create', {'patient_id': patient, 'title': f'SYNTHETIC recall {i}', 'due': '2098-09-03'}) for i in range(count)]
    payload = {'title': 'SYNTHETIC reviewed recalls', 'start': '2098-09-01', 'end': '2098-09-30',
               'reminder_ids': [r['id'] for r in reminders]}
    return payload


def recall_command(p):
    return f"Prepare recall campaign {p['title']} from {p['start']} to {p['end']} reminders: {', '.join(p['reminder_ids'])}"


def alert_fixture(conversation=False):
    with db.connection(True) as c:
        if conversation:
            tid = db.uid()
            turn = db.record(c, 'owner_turn', 'clinic-east', {'patient_id': 'luna', 'thread_id': tid,
                'speaker': 'owner', 'message': 'SYNTHETIC urgent owner message. Exact words only.', 'state': 'completed'})
            source = db.record(c, 'owner_thread', 'clinic-east', {'patient_id': 'luna', 'owner_access': 'synthetic-private-digest',
                'status': 'needs_attention', 'urgent': True, 'last_owner_turn': turn['id']}, tid)
            alert = owner_conversations.attention(c, source, 'SYNTHETIC owner requested urgent review')
        else:
            source = db.record(c, 'intake', 'clinic-east', {'patient_id': 'luna', 'text': 'SYNTHETIC exact owner intake.', 'status': 'new'})
            alert = db.record(c, 'escalation', 'clinic-east', {'patient_id': 'luna', 'intake_id': source['id'], 'status': 'needs_attention', 'delivery': 'disabled'})
    return alert, source


def ask_alert(monkeypatch, alert, **kwargs):
    return proposal(monkeypatch, 'escalation.acknowledge', {'id': alert['id'], 'version': alert['version']},
                    message='Acknowledge escalation ' + alert['id'], **kwargs)


def test_recall_review_persists_exact_recipients_and_drafts_then_confirms_once(monkeypatch):
    p = recall_fixture()
    # An unselected eligible reminder and an opted-out owner remain untouched.
    excluded = act('reminder.create', {'patient_id': 'milo', 'title': 'SYNTHETIC excluded', 'due': '2098-09-03'})
    owner = get(get('milo')['data']['owner_id'])
    act('owner.recall_preference', {'id': owner['id'], 'version': owner['version'], 'opt_out': True, 'reason': 'SYNTHETIC owner preference'})
    before = snapshot()
    # The model's allowed fields are ignored in favour of the current command.
    candidate = {**p, 'title': 'Model substituted title', 'reminder_ids': [excluded['id']], 'start': '2000-01-01'}
    turn = proposal(monkeypatch, 'recall.prepare', candidate, message=recall_command(p))
    assert snapshot() == before
    assert {k: v for k, v in turn['action']['payload'].items() if k != 'digest'} == p
    review = {f['label']: f['value'] for f in turn['review']['fields']}
    assert review['Drafts to prepare'] == '2' and review['Other reminders in date preview'] == '1'
    assert get('owner-luna')['data']['phone'] in review['Recipient 1']
    assert 'Recorded recall opt-out: No' in review['Recipient 1']
    assert 'No WhatsApp or email' in turn['review']['effects'][0]
    assert len(turn['action']['payload']['digest']) == 64
    campaign = confirm(turn)
    assert campaign['data']['delivery'] == 'manual'
    for i, rid in enumerate(p['reminder_ids'], 1):
        out = get(get(rid)['data']['outbox_id'])
        assert out['data']['body'] == review[f'Exact draft {i}'] and out['data']['status'] == 'pending'
        assert out['data']['owner_id'] == 'owner-luna'
    assert 'outbox_id' not in get(excluded['id'])['data']
    after = snapshot()
    assert confirm(turn) == campaign and snapshot() == after
    saved = TestClient(main.app).get('/api/assistant/conversations/' + turn['conversation_id'], headers={'x-actor-id': 'clinic-east-admin'}).json()['turns'][0]
    assert saved['review'] == turn['review'] and saved['execution'] == campaign
    assert len(rows('recall_campaign')) == 1 and len(rows('outbox')) == 2


@pytest.mark.parametrize('change', ['contact', 'opt_out', 'patient', 'reminder', 'new_matching_reminder', 'other_draft'])
def test_recall_confirmation_rechecks_all_dependencies_and_entire_preview(monkeypatch, change):
    p = recall_fixture(count=1)
    turn = proposal(monkeypatch, 'recall.prepare', p, message=recall_command(p))
    owner = get('owner-luna'); patient = get('luna'); reminder = get(p['reminder_ids'][0])
    if change == 'contact':
        act('owner.update', {'id': owner['id'], 'version': owner['version'], 'name': owner['data']['name'], 'phone': '+6500000001', 'email': ''})
    elif change == 'opt_out':
        act('owner.recall_preference', {'id': owner['id'], 'version': owner['version'], 'opt_out': True, 'reason': 'SYNTHETIC changed preference'})
    elif change == 'patient':
        act('patient.update', {'id': patient['id'], 'version': patient['version'], 'name': 'SYNTHETIC changed name'})
    elif change == 'reminder':
        act('reminder.update', {'id': reminder['id'], 'version': reminder['version'], 'title': 'SYNTHETIC revised title', 'due': reminder['data']['due']})
    elif change == 'new_matching_reminder':
        act('reminder.create', {'patient_id': 'milo', 'title': 'SYNTHETIC new preview member', 'due': '2098-09-04'})
    else:
        from recalls import preview
        with db.connection() as c: digest = preview(c, 'clinic-east', p)['digest']
        act('recall.prepare', {**p, 'digest': digest})
    before = snapshot()
    confirm(turn, 409)
    assert snapshot() == before
    assert len(rows('recall_campaign')) == (1 if change == 'other_draft' else 0)


@pytest.mark.parametrize('invalid', ['generic', 'unknown_field', 'duplicate', 'bad_date', 'long_period', 'outside_period', 'wrong_kind', 'foreign_clinic', 'opt_out', 'closed', 'existing_draft', 'patient_scope', 'too_many'])
def test_unsafe_recall_proposals_become_clarifications(monkeypatch, invalid):
    p = recall_fixture(count=21 if invalid == 'too_many' else 1)
    command = None; patient = None; candidate = None
    if invalid == 'generic': command = 'Prepare all due recalls'
    if invalid == 'unknown_field': candidate = {**p, 'digest': 'model-supplied-digest'}
    if invalid == 'duplicate': p['reminder_ids'] *= 2
    if invalid == 'bad_date': p['start'] = '2098-02-30'
    if invalid == 'long_period': p['end'] = '2100-01-01'
    if invalid == 'outside_period': p['end'] = '2098-09-02'
    if invalid == 'wrong_kind': p['reminder_ids'] = ['luna']
    if invalid == 'foreign_clinic':
        with db.connection(True) as c: foreign = db.record(c, 'reminder', 'clinic-river', {'patient_id': 'luna', 'title': 'SYNTHETIC foreign', 'due': '2098-09-03', 'status': 'due'})
        p['reminder_ids'] = [foreign['id']]
    if invalid == 'opt_out':
        owner = get('owner-luna')
        act('owner.recall_preference', {'id': owner['id'], 'version': owner['version'], 'opt_out': True, 'reason': 'SYNTHETIC owner preference'})
    if invalid == 'closed': act('reminder.complete', {'id': p['reminder_ids'][0], 'version': 1})
    if invalid == 'existing_draft':
        from recalls import preview
        with db.connection() as c: digest = preview(c, 'clinic-east', p)['digest']
        act('recall.prepare', {**p, 'digest': digest})
    if invalid == 'patient_scope': patient = 'milo'
    before = snapshot()
    turn = proposal(monkeypatch, 'recall.prepare', candidate or p, patient=patient, message=command or recall_command(p))
    assert 'action' not in turn and snapshot() == before
    confirm(turn, 409)


def test_recall_dependency_lock_and_replay_after_recipient_change(monkeypatch):
    p = recall_fixture(count=1)
    turn = proposal(monkeypatch, 'recall.prepare', p, actor='clinic-east-nurse', message=recall_command(p))
    practice = get('clinic-east')
    act('feature_locks.save', {'version': practice['version'], 'actions': ['message.queue']}, actor='clinic-east-admin')
    before = snapshot(); confirm(turn, 403, actor='clinic-east-nurse'); assert snapshot() == before
    practice = get('clinic-east')
    act('feature_locks.save', {'version': practice['version'], 'actions': []}, actor='clinic-east-admin')
    result = confirm(turn, actor='clinic-east-nurse')
    owner = get('owner-luna')
    act('owner.recall_preference', {'id': owner['id'], 'version': owner['version'], 'opt_out': True, 'reason': 'SYNTHETIC later preference'})
    before = snapshot(); assert confirm(turn, actor='clinic-east-nurse') == result and snapshot() == before


@pytest.mark.parametrize('conversation', [False, True])
def test_alert_review_acknowledges_internal_queue_only_and_replays(monkeypatch, conversation):
    alert, source = alert_fixture(conversation)
    before = snapshot()
    turn = ask_alert(monkeypatch, alert)
    assert snapshot() == before
    fields = {f['label']: f['value'] for f in turn['review']['fields']}
    assert 'SYNTHETIC' in fields['Exact human conversation' if conversation else 'Exact owner intake']
    assert fields['External notification delivery'] == 'disabled'
    assert 'Does not contact anyone' in turn['review']['effects'][0]
    assert source['id'] in turn['review_versions'] and 'luna' in turn['review_versions']
    result = confirm(turn)
    assert result['data']['status'] == 'acknowledged' and result['data']['delivery'] == 'disabled'
    assert get(source['id']) == source and not rows('outbox')
    after = snapshot(); assert confirm(turn) == result and snapshot() == after
    saved = TestClient(main.app).get('/api/assistant/conversations/' + turn['conversation_id'], headers={'x-actor-id': 'clinic-east-admin'}).json()['turns'][0]
    assert saved['review'] == turn['review'] and saved['execution'] == result


@pytest.mark.parametrize('conversation', [False, True])
def test_alert_new_source_information_invalidates_confirmation(monkeypatch, conversation):
    alert, source = alert_fixture(conversation)
    turn = ask_alert(monkeypatch, alert)
    with db.connection(True) as c:
        if conversation:
            owner_turn = db.record(c, 'owner_turn', 'clinic-east', {'patient_id': 'luna', 'thread_id': source['id'], 'speaker': 'owner', 'message': 'SYNTHETIC newer urgent information.', 'state': 'completed'})
            db.update(c, source, {**source['data'], 'last_owner_turn': owner_turn['id']})
        else: db.update(c, source, {**source['data'], 'text': 'SYNTHETIC edited intake.'})
    before = snapshot(); confirm(turn, 409); assert snapshot() == before
    assert get(alert['id'])['data']['status'] == 'needs_attention'


@pytest.mark.parametrize('invalid', ['generic', 'unknown_field', 'foreign_clinic', 'wrong_kind', 'patient_scope', 'missing_source', 'cross_patient_source', 'acknowledged', 'pending', 'long_conversation', 'invalid_latest'])
def test_unsafe_alerts_never_become_confirmable(monkeypatch, invalid):
    alert, source = alert_fixture(conversation=invalid in ('pending', 'long_conversation', 'invalid_latest'))
    command = 'Acknowledge escalation ' + alert['id']; patient = None
    candidate = {'id': alert['id'], 'version': alert['version']}
    if invalid == 'generic': command = 'Acknowledge all urgent alerts'
    if invalid == 'unknown_field': candidate['reason'] = 'Model-invented resolution'
    if invalid == 'patient_scope': patient = 'milo'
    if invalid == 'wrong_kind': command = 'Acknowledge escalation luna'
    with db.connection(True) as c:
        if invalid == 'foreign_clinic':
            foreign = db.record(c, 'escalation', 'clinic-river', alert['data']); command = 'Acknowledge escalation ' + foreign['id']
        if invalid == 'missing_source': db.update(c, alert, {**alert['data'], 'intake_id': 'missing'})
        if invalid == 'cross_patient_source': db.update(c, source, {**source['data'], 'patient_id': 'milo'})
        if invalid == 'acknowledged': db.update(c, alert, {**alert['data'], 'status': 'acknowledged'})
        if invalid == 'pending':
            row = db.get(c, source['data']['last_owner_turn']); db.update(c, row, {**row['data'], 'state': 'pending'})
        if invalid == 'long_conversation':
            for i in range(20): db.record(c, 'owner_turn', 'clinic-east', {'patient_id': 'luna', 'thread_id': source['id'], 'speaker': 'owner', 'message': f'SYNTHETIC extra turn {i}', 'state': 'completed'})
        if invalid == 'invalid_latest': db.update(c, source, {**source['data'], 'last_owner_turn': 'missing'})
    before = snapshot()
    turn = proposal(monkeypatch, 'escalation.acknowledge', candidate, patient=patient, message=command)
    assert 'action' not in turn and snapshot() == before


def test_exact_alert_context_has_metadata_and_no_owner_message(monkeypatch):
    alert, source = alert_fixture(conversation=True)
    seen = []
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    monkeypatch.setattr(assistant.providers, 'model_json', lambda _, p: seen.append(p) or {'action': {'action': 'escalation.acknowledge', 'payload': {'id': 'model-wrong-id', 'version': 999}}})
    turn = assistant_history.ask('clinic-east', 'clinic-east-admin', 'Acknowledge escalation ' + alert['id'], None, None, str(uuid.uuid4()))
    assert turn['action']['payload'] == {'id': alert['id'], 'version': alert['version']}
    metadata = next(r for r in seen[0]['records'] if r['id'] == alert['id'])
    assert metadata['data'] == {'patient_id': 'luna', 'status': 'needs_attention', 'delivery': 'disabled'}
    assert 'SYNTHETIC urgent owner message.' not in str(seen[0]) and 'synthetic-private-digest' not in str(seen[0])


def test_alert_permission_revocation_prevents_confirmation(monkeypatch):
    alert, _ = alert_fixture()
    turn = ask_alert(monkeypatch, alert, actor='clinic-east-vet')
    practice = get('clinic-east')
    act('feature_locks.save', {'version': practice['version'], 'actions': ['escalation.acknowledge']}, actor='clinic-east-admin')
    before = snapshot(); confirm(turn, 403, actor='clinic-east-vet'); assert snapshot() == before
