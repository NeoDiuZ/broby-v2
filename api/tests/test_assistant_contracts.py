"""Complete contract acceptance through persisted ask, confirmation and replay."""
import json
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import actions
import assistant
import assistant_contracts as contracts
import assistant_history
import assistant_operations
import db
import main
import owner_conversations
from test_integrity import isolated, act, get, rows
from test_assistant_operations import proposal, confirm, snapshot


def fixtures(monkeypatch):
    monkeypatch.setattr('providers.available', lambda: {'ai': True, 'transcription': True})
    admin = 'clinic-east-admin'
    do = lambda a, p: act(a, p, actor=admin)
    target = lambda r: {'id': r['id'], 'version': r['version']}
    patient = get('luna'); owner = get(patient['data']['owner_id'])
    extra = do('owner.create', {'name': 'Synthetic destination'})
    source = do('source.add', {'patient_id': 'luna', 'consultation_id': 'consult-luna', 'text': 'Exact supplied synthetic finding.'})
    with db.connection(True) as c:
        source = db.update(c, db.get(c, source['id']), {**source['data'], 'utterances': [{'speaker': 0, 'text': 'Exact supplied synthetic finding.'}]})
    consult = get('consult-luna')
    consult = do('summary.save', {**target(consult), 'summary': [{'name': 'Subjective', 'text': source['data']['text'], 'source_ids': [source['id']]}]})
    item = do('inventory.create', {'name': 'Synthetic stock', 'unit': 'pack', 'stock': 10, 'reorder': 2, 'price_cents': 100})
    invoice = do('invoice.create', {'patient_id': 'luna', 'items': [{'name': 'Synthetic service', 'quantity': 1, 'price_cents': 1000}]})
    paid = do('invoice.create', {'patient_id': 'luna', 'items': [{'name': 'Synthetic paid service', 'quantity': 1, 'price_cents': 1000}]})
    payment = do('payment.record', {**target(paid), 'amount_cents': 500, 'method': 'cash'})
    template = do('template.save', {'name': 'Synthetic template', 'sections': ['Subjective']})
    appointment = do('appointment.create', {'patient_id': 'luna', 'date': '2098-06-01', 'time': '10:00', 'duration': 30, 'reason': 'Synthetic check', 'clinician': 'clinic-east-vet'})
    message = do('message.queue', {'patient_id': 'luna', 'body': 'Exact supplied synthetic message.'})
    recording = do('recording.create', {'patient_id': 'luna', 'consultation_id': 'consult-luna'})
    grant = do('share.create', {'patient_id': 'luna'})
    leave = do('leave.request', {'member_id': 'clinic-east-vet', 'start': '2098-07-01', 'end': '2098-07-02', 'reason': 'Synthetic leave request'})
    dashboard = do('dashboard.save', {'name': 'Synthetic view', 'query': {'kind': 'patient'}})
    with db.connection(True) as c:
        recording = db.update(c, db.get(c, recording['id']), {**recording['data'], 'status': 'saved'})
        attachment = db.record(c, 'attachment', 'clinic-east', {'patient_id': 'luna', 'name': 'Synthetic.txt', 'approved': False})
        intake = db.record(c, 'intake', 'clinic-east', {'patient_id': 'luna', 'text': 'Exact owner statement.', 'status': 'new'})
        campaign = db.record(c, 'recall_campaign', 'clinic-east', {'title': 'Synthetic campaign', 'status': 'prepared', 'items': []})
        thread_id = db.uid()
        owner_turn = db.record(c, 'owner_turn', 'clinic-east', {'patient_id': 'luna', 'thread_id': thread_id,
            'speaker': 'owner', 'message': 'Exact synthetic owner question.', 'state': 'completed'})
        thread = db.record(c, 'owner_thread', 'clinic-east', {'patient_id': 'luna', 'owner_access': owner_conversations.digest(grant['id']),
            'title': 'Synthetic owner question', 'status': 'needs_attention', 'urgent': False,
            'last_owner_turn': owner_turn['id']}, thread_id)
        job = db.uid()
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)', (job, 'clinic-east', 'consult-luna', 'failed', json.dumps({'patient_id': 'luna'}), None, 'Synthetic failure', db.now(), db.now()))
    return {
        'patient.create': {'name': 'Synthetic new pet', 'species': 'Cat', 'owner_id': owner['id']},
        'patient.update': {**target(patient), 'weight': 4.5},
        'owner.create': {'name': 'Synthetic new owner'},
        'owner.update': {**target(owner), 'name': 'Synthetic renamed owner', 'email': owner['data']['email'], 'phone': owner['data']['phone']},
        'owner.merge': {**target(extra), 'target_id': owner['id']},
        'consultation.create': {'patient_id': 'luna', 'title': 'Synthetic consultation'},
        'consultation.approve': target(consult), 'consultation.archive': target(consult),
        'source.add': {'patient_id': 'luna', 'text': 'Explicit synthetic observation.', 'consultation_id': consult['id']},
        'observation.add': {'patient_id': 'luna', 'source_id': source['id'], 'name': 'Synthetic weight', 'value': 4.2, 'unit': 'kg'},
        'observation.record': {'patient_id': 'luna', 'source_id': source['id'], 'code': 'weight', 'value': 4.2},
        'summary.generate': {**target(consult), 'mode': 'verbatim'},
        'summary.save': {**target(consult), 'summary': [{'name': 'Subjective', 'text': source['data']['text'], 'source_ids': [source['id']]}]},
        'appointment.create': {'patient_id': 'luna', 'date': '2098-06-02', 'time': '10:00', 'duration': 30, 'clinician': 'clinic-east-vet', 'reason': 'Synthetic booking'},
        'appointment.series': {'patient_id': 'luna', 'date': '2098-06-03', 'time': '10:00', 'duration': 30, 'clinician': 'clinic-east-vet', 'reason': 'Synthetic series', 'count': 2, 'interval_days': 7},
        'appointment.reschedule': {**target(appointment), 'date': '2098-06-04', 'time': '11:00'},
        'appointment.update': {**target(appointment), 'status': 'cancelled'},
        'invoice.create': {'patient_id': 'luna', 'items': [{'name': 'Synthetic service', 'quantity': 2, 'price_cents': 100}], 'discount_cents': 10, 'tax_bps': 900},
        'invoice.void': {**target(invoice), 'reason': 'Synthetic cancellation'},
        'payment.record': {**target(invoice), 'amount_cents': 200, 'method': 'cash'},
        'payment.refund': {'id': payment['id'], 'version': get(paid['id'])['version'], 'amount_cents': 100, 'reason': 'Synthetic refund already completed'},
        'inventory.create': {'name': 'Synthetic supply', 'unit': 'pack', 'stock': 0, 'reorder': 2, 'price_cents': 100},
        'inventory.adjust': {**target(item), 'stock': 8, 'reason': 'Synthetic stocktake'},
        'inventory.receive': {**target(item), 'quantity': 2, 'batch': 'TEST', 'supplier': 'Synthetic supplier'},
        'medication.dispense': {'patient_id': 'luna', 'inventory_id': item['id'], 'version': item['version'], 'quantity': 1, 'dose': 'Exact supplied dose', 'frequency': 'Exact supplied frequency', 'instructions': 'Exact supplied instructions'},
        'template.save': {**target(template), 'name': 'Synthetic revised template', 'sections': ['Subjective', 'Objective']},
        'template.archive': target(template),
        'reminder.queue_due': {},
        'message.queue': {'patient_id': 'luna', 'body': 'Exact supplied message.'},
        'message.update': {**target(message), 'body': 'Exact supplied revised message.'},
        'message.cancel': target(message), 'message.complete': target(message),
        'share.create': {'patient_id': 'luna'}, 'share.revoke': {'token': grant['id']},
        'attachment.approve': {**target(attachment), 'approved': True},
        'recording.approve': {**target(recording), 'approved': True},
        'recording.transcribe': {'id': recording['id'], 'language': 'en', 'diarize': False},
        'job.retry': {'id': job},
        'intake.accept': {**target(intake), 'consultation_id': 'consult-luna'}, 'intake.close': target(intake),
        'settings.save': {'version': get('settings-clinic-east')['version'], 'retention': 'medical', 'language': 'en', 'emergency_phone': '', 'reminder_days': 7},
        'member.save': {'name': 'Synthetic staff', 'role': 'nurse', 'active': True},
        'feature_locks.save': {'version': get('clinic-east')['version'], 'actions': ['inventory.adjust']},
        'ontology.save': {'code': 'synthetic_result', 'name': 'Synthetic result', 'value_type': 'boolean', 'unit': '', 'category': 'Synthetic'},
        'lab.import': {'patient_id': 'luna', 'title': 'Synthetic CSV', 'csv': 'name,value,unit,low,high\nSynthetic value,2,unit,1,3'},
        'source.speakers': {**target(source), 'speaker_labels': {'0': 'Operator supplied label'}},
        'automation.save': {'version': get('settings-clinic-east')['version'], 'auto_reminders': False, 'auto_handover': False, 'handover_at': '07:00'},
        'dashboard.save': {**target(dashboard), 'name': 'Synthetic invoices', 'query': {'kind': 'invoice', 'outstanding': True}},
        'dashboard.delete': target(dashboard),
        'owner.recall_preference': {**target(owner), 'opt_out': True, 'reason': 'Explicit synthetic preference'},
        'conversation.acknowledge': {**target(thread), 'reason': 'Synthetic phone follow-up completed'},
        'conversation.close': {**target(thread), 'reason': 'Synthetic phone follow-up completed'},
        'conversation.reply': {**target(thread), 'message': 'SYNTHETIC staff portal reply copied exactly.'},
        'recall.cancel': {**target(campaign), 'reason': 'Synthetic cancellation'},
        'leave.request': {'member_id': 'clinic-east-nurse', 'start': '2098-08-01', 'end': '2098-08-02', 'reason': 'Synthetic leave'},
        'leave.review': {**target(leave), 'decision': 'approved', 'reason': 'Synthetic approval'},
        'leave.cancel': {**target(leave), 'reason': 'Synthetic withdrawal'},
        'discharge.queue': {'patient_id': 'luna'},
    }


@pytest.mark.parametrize('name', sorted(contracts.SPECS))
def test_every_contract_saved_review_confirm_and_replay(monkeypatch, name):
    payload = fixtures(monkeypatch)[name]
    before = snapshot()
    message = (f"Reply to conversation {payload['id']} message: {payload['message']}" if name == 'conversation.reply'
               else f"{name.split('.')[1].capitalize()} conversation {payload['id']} reason: {payload['reason']}" if name.startswith('conversation.')
               else 'Synthetic explicit operator request')
    turn = proposal(monkeypatch, name, payload, message=message)
    monkeypatch.setattr('providers.available', lambda: {'ai': True, 'transcription': True})
    assert 'action' in turn, turn
    assert snapshot() == before, 'Preparing a review must not change any clinic record or action audit'
    assert turn['review']['fields'] and turn['review']['effects']
    assert turn['action']['action'] == name
    first = confirm(turn)
    after = snapshot()
    assert confirm(turn) == first and snapshot() == after
    saved = TestClient(main.app).get('/api/assistant/conversations/' + turn['conversation_id'], headers={'x-actor-id': 'clinic-east-admin'}).json()['turns'][0]
    assert saved['review'] == turn['review'] and saved['execution'] == first
    if name == 'invoice.create': assert first['data']['total_cents'] == 207
    if name == 'medication.dispense': assert get(payload['inventory_id'])['data']['stock'] == 9
    if name == 'payment.record': assert get(payload['id'])['data']['paid_cents'] == 200
    if name == 'patient.update': assert first['data']['name'] == 'Luna' and first['data']['weight'] == 4.5
    if name == 'appointment.reschedule': assert first['data']['reason'] == 'Synthetic check' and first['data']['time'] == '11:00'
    if name == 'leave.review': assert first['data']['status'] == 'approved'
    if name == 'share.revoke': assert TestClient(main.app).get('/api/owner/' + payload['token']).status_code == 404
    if name.startswith('conversation.'):
        assert first['data']['status'] == ('closed' if name.endswith('close') else 'needs_attention' if name.endswith('reply') else 'acknowledged')
        assert first['data']['last_owner_turn'] == turn['action']['payload']['last_owner_turn']
        assert 'Exact synthetic owner question.' in next(f['value'] for f in turn['review']['fields'] if f['label'] == 'Exact human conversation')
        if name == 'conversation.reply':
            with db.connection() as c:
                token = next(row['token'] for row in c.execute('SELECT token FROM grants WHERE clinic_id=?', ('clinic-east',))
                             if owner_conversations.digest(row['token']) == first['data']['owner_access'])
            assert owner_conversations.owner_read(token, payload['id'])['turns'][-1]['message'] == payload['message']


def test_every_operation_is_strict_guided_or_explicit_internal_test_adapter():
    typed = set(assistant_operations.CONTRACTS) | set(contracts.SPECS)
    assert typed.isdisjoint(contracts.GUIDED)
    assert set(assistant.ACTION_FIELDS) == typed
    assert set(actions.PERMISSIONS) - typed - set(contracts.GUIDED) == {
        'test.lab.receive', 'test.message.callback', 'test.message.create',
        'test.payment.callback', 'test.payment.create', 'test.payment.refund'}
    for contract in assistant.ACTION_FIELDS.values():
        assert contract['payload_schema']['additionalProperties'] is False


@pytest.mark.parametrize('name', sorted(contracts.SPECS))
def test_unknown_fields_never_become_confirmable(monkeypatch, name):
    payload = fixtures(monkeypatch)[name]
    before = snapshot()
    result = proposal(monkeypatch, name, {**payload, 'unreviewed_field': True})
    assert 'action' not in result and snapshot() == before


@pytest.mark.parametrize('name,changes', [
    ('invoice.create', {'discount_cents': True}),
    ('invoice.create', {'tax_bps': '900'}),
    ('inventory.create', {'stock': 1.5}),
    ('payment.record', {'amount_cents': 0}),
    ('payment.record', {'method': 'stripe'}),
    ('appointment.create', {'date': '2098-02-30'}),
    ('appointment.create', {'time': '24:00'}),
    ('appointment.create', {'duration': True}),
    ('patient.update', {'weight': float('nan')}),
    ('patient.update', {'weight': False}),
    ('patient.create', {'owner_name': 'Ambiguous second owner'}),
    ('source.add', {'consultation_id': 'milo'}),
    ('observation.add', {'low': 8, 'high': 2}),
    ('observation.record', {'value': False}),
    ('owner.merge', {'target_id': 'clinic-river-admin'}),
    ('recording.approve', {'approved': 'false'}),
    ('template.save', {'sections': ['Plan', 'Plan']}),
    ('member.save', {'id': 'clinic-east-admin', 'version': 1, 'active': False}),
    ('leave.request', {'end': '2098-07-01'}),
    ('source.speakers', {'speaker_labels': {'99': 'Invented speaker'}}),
])
def test_bad_values_are_clarifications_without_mutations(monkeypatch, name, changes):
    payload = fixtures(monkeypatch)[name]
    before = snapshot()
    result = proposal(monkeypatch, name, {**payload, **changes})
    assert 'action' not in result and snapshot() == before


@pytest.mark.parametrize('name', ['invoice.create', 'consultation.approve', 'source.add', 'intake.accept', 'payment.refund', 'job.retry', 'share.revoke'])
def test_patient_context_cannot_be_crossed(monkeypatch, name):
    payload = fixtures(monkeypatch)[name]
    before = snapshot()
    result = proposal(monkeypatch, name, payload, patient='milo')
    assert 'action' not in result and snapshot() == before


def test_review_dependencies_are_rechecked_atomically_and_replay_precedes_guard(monkeypatch):
    p = fixtures(monkeypatch)['message.queue']
    turn = proposal(monkeypatch, 'message.queue', p)
    owner = get('owner-luna')
    act('owner.update', {'id': owner['id'], 'version': owner['version'], 'name': 'Changed after review', 'phone': '', 'email': ''})
    before = snapshot()
    confirm(turn, expected=409)
    assert snapshot() == before
    fresh = proposal(monkeypatch, 'message.queue', p)
    first = confirm(fresh)
    patient = get('luna')
    act('patient.update', {'id': patient['id'], 'version': patient['version'], 'name': 'Changed after successful confirmation'})
    assert confirm(fresh) == first


def test_permission_revocation_after_proposal_blocks_confirmation(monkeypatch):
    p = fixtures(monkeypatch)['message.queue']
    turn = proposal(monkeypatch, 'message.queue', p, actor='clinic-east-nurse')
    clinic = get('clinic-east')
    act('feature_locks.save', {'version': clinic['version'], 'actions': ['message.queue']}, actor='clinic-east-admin')
    before = snapshot()
    confirm(turn, expected=403, actor='clinic-east-nurse')
    assert snapshot() == before


@pytest.mark.parametrize('operation,destination', [('stripe.refund', 'Billing'), ('recording.create', 'Patients'), ('migration.apply', 'Settings'), ('conversation.policy', 'Handover')])
def test_dedicated_workflows_are_navigation_never_raw_actions(monkeypatch, operation, destination):
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    monkeypatch.setattr(assistant.providers, 'model_json', lambda *a: {'guide': operation})
    before = snapshot()
    result = assistant_history.ask('clinic-east', 'clinic-east-admin', 'Explicit synthetic request', None, None, str(uuid.uuid4()))
    assert 'action' not in result and result['navigate'] == destination and snapshot() == before


def test_missing_tax_and_replacement_contacts_cannot_be_guessed(monkeypatch):
    payloads = fixtures(monkeypatch)
    for name, key in [('invoice.create', 'tax_bps'), ('owner.update', 'phone')]:
        p = dict(payloads[name]); del p[key]
        assert 'action' not in proposal(monkeypatch, name, p)


@pytest.mark.parametrize('name', ['conversation.acknowledge', 'conversation.close'])
def test_conversation_resolution_requires_exact_current_operator_command(monkeypatch, name):
    payload = fixtures(monkeypatch)[name]
    verb = name.split('.')[1].capitalize()
    command = f"{verb} conversation {payload['id']} reason: {payload['reason']}"
    for message, candidate in [
        ('Synthetic explicit operator request', payload),
        (command.replace(payload['id'], 'wrong-conversation'), payload),
        (command.replace(payload['reason'], 'Different reason'), payload),
        (command, {**payload, 'reason': 'Model-invented reason'}),
        (command.replace(' reason:', ' but do not resolve it; reason:'), payload),
    ]:
        before = snapshot()
        result = proposal(monkeypatch, name, candidate, message=message)
        assert 'action' not in result and snapshot() == before
    reviewed = proposal(monkeypatch, name, payload, message=command)
    assert reviewed['action']['payload']['last_owner_turn']


def test_conversation_reply_requires_exact_operator_words(monkeypatch):
    payload = fixtures(monkeypatch)['conversation.reply']
    command = f"Reply to conversation {payload['id']} message: {payload['message']}"
    for message, candidate in [
        ('Reply to the owner with an appropriate answer', payload),
        (command.replace(payload['id'], 'wrong-conversation'), payload),
        (command.replace(payload['message'], 'Different staff words'), payload),
        (command, {**payload, 'message': 'Model-authored clinical advice'}),
        (command.replace(' message:', ' but do not send it; message:'), payload),
    ]:
        before = snapshot()
        result = proposal(monkeypatch, 'conversation.reply', candidate, message=message)
        assert 'action' not in result and snapshot() == before
    reviewed = proposal(monkeypatch, 'conversation.reply', payload, message=command)
    assert reviewed['action']['payload']['message'] == payload['message']
    assert reviewed['action']['payload']['last_owner_turn']


def test_full_length_staff_reply_reaches_owner_portal_only_after_confirmation(monkeypatch):
    payload = fixtures(monkeypatch)['conversation.reply']
    exact = 'SYNTHETIC ' + 'x' * (4000 - len('SYNTHETIC '))
    payload['message'] = exact
    monkeypatch.setattr(assistant.providers, 'model_json', lambda *a: {'action': {'action': 'conversation.reply', 'payload': payload}})
    client = TestClient(main.app)
    before = snapshot()
    response = client.post('/api/assistant', headers={'x-actor-id': 'clinic-east-admin'}, json={
        'message': f"Reply to conversation {payload['id']} message: {exact}", 'patient_id': 'luna',
        'key': str(uuid.uuid4())})
    assert response.status_code == 200
    turn = response.json()
    assert turn['action']['payload']['message'] == exact and snapshot() == before
    result = confirm(turn)
    assert result['data']['status'] == 'needs_attention'
    assert [r['data']['message'] for r in rows('owner_turn') if r['data']['speaker'] == 'clinic'] == [exact]
    with db.connection() as c:
        token = next(row['token'] for row in c.execute('SELECT token FROM grants WHERE clinic_id=?', ('clinic-east',))
                     if owner_conversations.digest(row['token']) == result['data']['owner_access'])
    assert owner_conversations.owner_read(token, payload['id'])['turns'][-1]['message'] == exact


@pytest.mark.parametrize('name', ['conversation.close', 'conversation.reply'])
@pytest.mark.parametrize('state', ['pending', 'closed', 'long'])
def test_conversation_action_rechecks_current_thread_before_review(monkeypatch, state, name):
    payload = fixtures(monkeypatch)[name]
    with db.connection(True) as c:
        thread = db.get(c, payload['id'])
        if state == 'closed':
            thread = db.update(c, thread, {**thread['data'], 'status': 'closed'})
        elif state == 'pending':
            turn = db.get(c, thread['data']['last_owner_turn'])
            db.update(c, turn, {**turn['data'], 'state': 'pending'})
        else:
            for n in range(20):
                db.record(c, 'owner_turn', 'clinic-east', {'patient_id': 'luna', 'thread_id': thread['id'],
                    'speaker': 'clinic', 'message': f'Synthetic clinic follow-up {n}', 'state': 'completed'})
        payload['version'] = thread['version']
    before = snapshot()
    command = (f"Reply to conversation {payload['id']} message: {payload['message']}" if name.endswith('reply')
               else f"Close conversation {payload['id']} reason: {payload['reason']}")
    result = proposal(monkeypatch, name, payload, message=command)
    assert 'action' not in result and snapshot() == before


@pytest.mark.parametrize('name', ['conversation.close', 'conversation.reply'])
def test_conversation_action_new_owner_turn_requires_fresh_review(monkeypatch, name):
    payload = fixtures(monkeypatch)[name]
    command = (f"Reply to conversation {payload['id']} message: {payload['message']}" if name.endswith('reply')
               else f"Close conversation {payload['id']} reason: {payload['reason']}")
    reviewed = proposal(monkeypatch, name, payload, message=command)
    with db.connection(True) as c:
        thread = db.get(c, payload['id'])
        latest = db.record(c, 'owner_turn', 'clinic-east', {'patient_id': 'luna', 'thread_id': thread['id'],
            'speaker': 'owner', 'message': 'New synthetic owner question.', 'state': 'completed'})
        db.update(c, thread, {**thread['data'], 'last_owner_turn': latest['id'], 'status': 'needs_attention'})
    before = snapshot()
    confirm(reviewed, expected=409)
    assert snapshot() == before


@pytest.mark.parametrize('name', ['conversation.close', 'conversation.reply'])
def test_conversation_action_cannot_cross_selected_patient(monkeypatch, name):
    payload = fixtures(monkeypatch)[name]
    before = snapshot()
    command = (f"Reply to conversation {payload['id']} message: {payload['message']}" if name.endswith('reply')
               else f"Close conversation {payload['id']} reason: {payload['reason']}")
    result = proposal(monkeypatch, name, payload, patient='milo', message=command)
    assert 'action' not in result and snapshot() == before


def test_conversation_model_receives_metadata_but_review_displays_exact_text(monkeypatch):
    payload = fixtures(monkeypatch)['conversation.acknowledge']
    captured = {}
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    def model(prompt, context):
        captured.update(context)
        return {'action': {'action': 'conversation.acknowledge', 'payload': payload}}
    monkeypatch.setattr(assistant.providers, 'model_json', model)
    result = assistant_history.ask('clinic-east', 'clinic-east-admin',
        f"Acknowledge conversation {payload['id']} reason: {payload['reason']}", None, None, str(uuid.uuid4()))
    assert 'action' in result
    record = next(r for r in captured['records'] if r['id'] == payload['id'])
    assert set(record['data']) == {'patient_id', 'status', 'urgent'}
    assert 'Exact synthetic owner question.' not in json.dumps(captured)
    assert 'Exact synthetic owner question.' in next(f['value'] for f in result['review']['fields']
        if f['label'] == 'Exact human conversation')
