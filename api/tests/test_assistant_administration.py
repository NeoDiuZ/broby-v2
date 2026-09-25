"""Administrative proposals preserve existing authority and reveal effective access."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

import assistant
import assistant_history
import auth
import db
import main
import organization_adoption
import organizations
from read_access import READS, allowed_reads
from test_integrity import isolated, act, get, rows
from test_assistant_operations import proposal, confirm, snapshot

ADMIN = 'clinic-east-admin'
MEMBER = 'clinic-east-nurse'


def access_payload(restrictions=('read.billing',), target=MEMBER):
    return {'id': target, 'version': get(target)['version'], 'restrictions': list(restrictions), 'reason': 'SYNTHETIC exact access review reason'}


def access_command(p):
    return f"Set member {p['id']} read restrictions: {', '.join(p['restrictions']) or 'none'} reason: {p['reason']}"


def ask_access(monkeypatch, p=None, **kwargs):
    p = p or access_payload()
    return proposal(monkeypatch, 'access.member', p, message=access_command(p), **kwargs)


def displayed_values(turn, label):
    value = next(f['value'] for f in turn['review']['fields'] if f['label'] == label)
    return set() if value == 'None' else {line.split(' — ')[0] for line in value.splitlines()}


def memberships():
    with db.connection() as c:
        return [tuple(r) for r in c.execute('SELECT * FROM auth_memberships ORDER BY username,clinic_id')], [tuple(r) for r in c.execute('SELECT * FROM organization_clinics ORDER BY clinic_id')]


def adoption_fixture():
    auth.provision('synthetic-org-master', 'clinic-river-admin', 'clinic-river', 'Synthetic-test-only-password')
    org = act('organization.create', {'name': 'SYNTHETIC parent organization'}, actor='clinic-river-admin', clinic='clinic-river')
    with db.connection() as c: consent = organization_adoption.consent(c, 'clinic-east', org['id'])
    return act('organization.join_request', {'organization_id': org['id'], 'digest': organization_adoption.digest(consent),
        'accept_access': True, 'reason': 'SYNTHETIC original access consent'}, actor=ADMIN)


def ask_withdraw(monkeypatch, request, **kwargs):
    p = {'id': request['id'], 'version': request['version'], 'reason': 'SYNTHETIC exact withdrawal reason'}
    return proposal(monkeypatch, 'organization.join_cancel', p,
                    message=f"Withdraw organization request {request['id']} reason: {p['reason']}", **kwargs)


@pytest.mark.parametrize('role,active,inherited', [('nurse', True, False), ('nurse', True, True), ('admin', True, True), ('vet', False, True)])
def test_member_review_shows_whole_effective_access_and_preserves_inherited_limits(monkeypatch, role, active, inherited):
    act('member.save', {'id': MEMBER, 'version': get(MEMBER)['version'], 'name': 'SYNTHETIC selected staff', 'role': role, 'active': active}, actor=ADMIN)
    act('access.member', access_payload(('read.billing', 'read.clinical')), actor=ADMIN)
    if inherited:
        act('organization.create', {'name': 'SYNTHETIC organization'}, actor=ADMIN)
        act('organization.policy', {'actions': ['read.messages', 'source.add']}, actor=ADMIN)
        practice = get('clinic-east')
        act('feature_locks.save', {'version': practice['version'], 'actions': ['read.patients']}, actor=ADMIN)
    before = snapshot(); accounts = memberships()
    p = access_payload(('read.inventory',))
    turn = ask_access(monkeypatch, p)
    assert snapshot() == before and memberships() == accounts
    with db.connection() as c: current = allowed_reads(c, 'clinic-east', MEMBER)
    assert displayed_values(turn, 'Current effective read access') == current
    assert displayed_values(turn, 'Current member restrictions') == {'read.billing', 'read.clinical'}
    assert displayed_values(turn, 'New complete member restrictions') == {'read.inventory'}
    inherited_values = {'read.messages'} | ({'read.patients'} if role != 'admin' else set()) if inherited else set()
    assert displayed_values(turn, 'Inherited read restrictions retained') == inherited_values
    expected = set(READS) - {'read.inventory'} - inherited_values if active else set()
    assert displayed_values(turn, 'Effective read access after confirmation') == expected
    views = next(f['value'] for f in turn['review']['fields'] if f['label'] == 'Views after confirmation with required dependencies')
    assert ('Billing: Available' in views) == ({'read.patients', 'read.billing'} <= expected)
    assert ('Appointments and rota: Available' in views) == ({'read.patients', 'read.schedule', 'read.staff'} <= expected)
    assert ('Mixed histories, assistant chat, reports and full exports: Available' in views) == (set(READS) <= expected)
    result = confirm(turn)
    assert result['data']['read_restrictions'] == ['read.inventory']
    assert result['data']['role'] == role and result['data']['active'] is active
    assert result['data']['access_review']['reason'] == p['reason'] and memberships() == accounts
    with db.connection() as c: assert allowed_reads(c, 'clinic-east', MEMBER) == expected
    after = snapshot(); assert confirm(turn) == result and snapshot() == after
    saved = TestClient(main.app).get('/api/assistant/conversations/' + turn['conversation_id'], headers={'x-actor-id': ADMIN}).json()['turns'][0]
    assert saved['review'] == turn['review'] and saved['execution'] == result


def test_empty_complete_list_is_explicit_and_model_substitution_cannot_broaden_access(monkeypatch):
    act('access.member', access_payload(('read.billing', 'read.clinical')), actor=ADMIN)
    desired = access_payload(())
    model = {**desired, 'id': 'clinic-river-admin', 'version': 999, 'restrictions': ['read.messages'], 'reason': 'Model replaced reason'}
    turn = proposal(monkeypatch, 'access.member', model, message=access_command(desired))
    assert {k: v for k, v in turn['action']['payload'].items() if k != 'expected_access_digest'} == desired
    assert displayed_values(turn, 'Effective read access after confirmation') == set(READS)
    assert confirm(turn)['data']['read_restrictions'] == []


@pytest.mark.parametrize('change', ['member', 'clinic', 'policy', 'organization_added', 'account'])
def test_member_confirmation_rejects_changed_records_policy_or_account_relationship(monkeypatch, change):
    if change in ('policy', 'account'): act('organization.create', {'name': 'SYNTHETIC reviewed org'}, actor=ADMIN)
    turn = ask_access(monkeypatch)
    if change == 'member':
        member = get(MEMBER)
        act('member.save', {'id': MEMBER, 'version': member['version'], 'name': 'SYNTHETIC renamed member', 'role': 'vet', 'active': True}, actor=ADMIN)
    elif change == 'clinic':
        practice = get('clinic-east')
        act('feature_locks.save', {'version': practice['version'], 'actions': ['read.clinical']}, actor=ADMIN)
    elif change == 'policy': act('organization.policy', {'actions': ['read.messages']}, actor=ADMIN)
    elif change == 'organization_added': act('organization.create', {'name': 'SYNTHETIC organization added'}, actor=ADMIN)
    else: auth.provision('synthetic-target-account', MEMBER, 'clinic-east', 'Synthetic-test-only-password')
    before = snapshot(); confirm(turn, 409); assert snapshot() == before
    assert not get(MEMBER)['data'].get('read_restrictions')


def test_successful_member_confirmation_replays_after_policy_changed(monkeypatch):
    act('organization.create', {'name': 'SYNTHETIC organization'}, actor=ADMIN)
    turn = ask_access(monkeypatch); result = confirm(turn)
    act('organization.policy', {'actions': ['read.messages']}, actor=ADMIN)
    before = snapshot(); assert confirm(turn) == result and snapshot() == before


@pytest.mark.parametrize('invalid', ['generic', 'unknown_field', 'duplicate', 'unknown_capability', 'missing_complete_list', 'foreign', 'self', 'master', 'patient_scope', 'short_reason', 'long_reason'])
def test_member_invalid_or_unauthorized_targets_never_get_confirmable_actions(monkeypatch, invalid):
    p = access_payload(); message = None; candidate = None; patient = None
    if invalid == 'generic': message = 'Remove all restrictions for the nurse'
    if invalid == 'unknown_field': candidate = {**p, 'expected_access_digest': 'forged'}
    if invalid == 'duplicate': p['restrictions'] *= 2
    if invalid == 'unknown_capability': p['restrictions'] = ['write.everything']
    if invalid == 'missing_complete_list': message = f"Set member {MEMBER} read restrictions: reason: Synthetic reason"
    if invalid == 'foreign': p['id'] = 'clinic-river-admin'
    if invalid == 'self': p['id'] = ADMIN
    if invalid == 'master':
        act('organization.create', {'name': 'SYNTHETIC protected master'}, actor=ADMIN)
        second = act('member.save', {'name': 'SYNTHETIC other administrator', 'role': 'admin', 'active': True}, actor=ADMIN)
        p['id'] = ADMIN
        before = snapshot()
        turn = proposal(monkeypatch, 'access.member', p, actor=second['id'], message=access_command(p))
        assert 'action' not in turn and snapshot() == before
        return
    if invalid == 'patient_scope': patient = 'luna'
    if invalid == 'short_reason': p['reason'] = 'x'
    if invalid == 'long_reason': p['reason'] = 'x' * 501
    before = snapshot()
    turn = proposal(monkeypatch, 'access.member', candidate or p, message=message or access_command(p), patient=patient)
    assert 'action' not in turn and snapshot() == before


def test_member_administrator_role_revocation_blocks_saved_confirmation(monkeypatch):
    other = act('member.save', {'name': 'SYNTHETIC second admin', 'role': 'admin'}, actor=ADMIN)
    turn = ask_access(monkeypatch, actor=other['id'])
    act('member.save', {'id': other['id'], 'version': other['version'], 'name': other['data']['name'], 'role': 'nurse', 'active': True}, actor=ADMIN)
    before = snapshot(); confirm(turn, 403, actor=other['id']); assert snapshot() == before


def test_organization_withdrawal_preserves_records_memberships_and_consent(monkeypatch):
    request = adoption_fixture(); accounts = memberships(); before = snapshot()
    turn = ask_withdraw(monkeypatch, request)
    assert snapshot() == before and memberships() == accounts
    fields = {field['label']: field['value'] for field in turn['review']['fields']}
    assert request['data']['consent']['organization_id'] in fields['Requested organization']
    assert fields['Original proposed access'] == request['data']['consent']['access']
    assert fields['Original request reason'] == request['data']['reason']
    assert fields['Reason'] == 'SYNTHETIC exact withdrawal reason'
    result = confirm(turn)
    assert result['data']['status'] == 'withdrawn' and result['data']['consent'] == request['data']['consent']
    assert memberships() == accounts
    with db.connection() as c: assert organizations.policy(c, 'clinic-east') is None
    after = snapshot(); assert confirm(turn) == result and snapshot() == after
    saved = TestClient(main.app).get('/api/assistant/conversations/' + turn['conversation_id'], headers={'x-actor-id': ADMIN}).json()['turns'][0]
    assert saved['review'] == turn['review'] and saved['execution'] == result


def test_organization_withdrawal_uses_exact_target_reason_and_private_metadata(monkeypatch):
    request = adoption_fixture(); captured = []
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    monkeypatch.setattr(assistant.providers, 'model_json', lambda _, data: captured.append(data) or {'action': {
        'action': 'organization.join_cancel', 'payload': {'id': 'model-wrong-target', 'version': 999, 'reason': 'Model substituted reason'}}})
    message = f"Withdraw organization request {request['id']} reason: SYNTHETIC authoritative reason"
    turn = assistant_history.ask('clinic-east', ADMIN, message, None, None, str(uuid.uuid4()))
    assert turn['action']['payload'] == {'id': request['id'], 'version': request['version'], 'reason': 'SYNTHETIC authoritative reason'}
    metadata = next(r for r in captured[0]['records'] if r['id'] == request['id'])
    assert metadata['data'] == {'status': 'pending'}
    assert 'synthetic-org-master' not in json.dumps(captured[0])


@pytest.mark.parametrize('change', ['request_closed', 'request_accepted', 'requester', 'clinic'])
def test_withdrawal_confirmation_rechecks_complete_review(monkeypatch, change):
    request = adoption_fixture(); turn = ask_withdraw(monkeypatch, request)
    if change == 'request_closed':
        act('organization.join_cancel', {'id': request['id'], 'version': request['version'], 'reason': 'SYNTHETIC concurrent withdrawal'}, actor=ADMIN)
    elif change == 'request_accepted':
        with db.connection() as c: review = organization_adoption.acceptance(c, request)[0]
        act('organization.join_review', {'id': request['id'], 'version': request['version'], 'decision': 'accepted',
            'digest': review['digest'], 'accept_access': True, 'reason': 'SYNTHETIC concurrent acceptance'}, actor='clinic-river-admin', clinic='clinic-river')
    elif change == 'requester':
        current = get(ADMIN)
        act('member.save', {'id': ADMIN, 'version': current['version'], 'name': 'SYNTHETIC current administrator', 'role': 'admin', 'active': True}, actor=ADMIN)
    else:
        practice = get('clinic-east')
        act('feature_locks.save', {'version': practice['version'], 'actions': ['source.add']}, actor=ADMIN)
    before = snapshot(); accounts = memberships(); confirm(turn, 409)
    assert snapshot() == before and memberships() == accounts


@pytest.mark.parametrize('invalid', ['generic', 'unknown_field', 'foreign', 'wrong_kind', 'patient_scope', 'closed', 'short_reason', 'long_reason'])
def test_withdrawal_invalid_input_never_becomes_confirmable(monkeypatch, invalid):
    request = adoption_fixture()
    p = {'id': request['id'], 'version': request['version'], 'reason': 'SYNTHETIC withdrawal'}
    patient = None; message = None
    if invalid == 'generic': message = 'Withdraw the pending organization request'
    if invalid == 'unknown_field': p['accept_access'] = True
    if invalid == 'foreign':
        with db.connection(True) as c: foreign = db.record(c, 'organization_adoption', 'clinic-river', request['data'])
        p['id'] = foreign['id']
    if invalid == 'wrong_kind': p['id'] = MEMBER
    if invalid == 'patient_scope': patient = 'luna'
    if invalid == 'closed': act('organization.join_cancel', p, actor=ADMIN)
    if invalid == 'short_reason': p['reason'] = 'x'
    if invalid == 'long_reason': p['reason'] = 'x' * 501
    before = snapshot()
    turn = proposal(monkeypatch, 'organization.join_cancel', p, patient=patient,
        message=message or f"Withdraw organization request {p['id']} reason: {p['reason']}")
    assert 'action' not in turn and snapshot() == before
