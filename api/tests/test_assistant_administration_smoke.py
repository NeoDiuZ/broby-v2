"""Staged acceptance script checks, using authenticated local APIs and fake intent."""
import contextlib
import json
import runpy
from pathlib import Path

import httpx
import pytest

import assistant
import db
from test_hosted import hosted

V2_PROJECT = 'ca389ebd-0186-4b7e-baec-8ddacdfc406b'
ROOT = Path(__file__).resolve().parents[2]
PROVISION = ROOT / 'api/scripts/provision-assistant-administration.py'
SMOKE = ROOT / 'scripts/smoke-assistant-administration.py'
BASE = 'https://broby.example.test'


def provision(monkeypatch, state, account='admin', confirmation=V2_PROJECT):
    monkeypatch.setattr('sys.argv', [str(PROVISION), BASE, '--state', str(state), '--account', account,
                                   '--confirm-v2-project', confirmation])
    runpy.run_path(str(PROVISION), run_name='__main__')


def stored():
    with db.connection() as c:
        return {'records': {r['id']: dict(r) for r in c.execute('SELECT * FROM records')},
                'credentials': [tuple(r) for r in c.execute('SELECT * FROM credentials ORDER BY username')],
                'memberships': [tuple(r) for r in c.execute('SELECT * FROM auth_memberships ORDER BY username,clinic_id')],
                'organizations': {r['id']: dict(r) for r in c.execute('SELECT * FROM organizations')},
                'clinic_organizations': [tuple(r) for r in c.execute('SELECT * FROM organization_clinics ORDER BY clinic_id')]}


def runner(hosted, monkeypatch, credentials, state):
    monkeypatch.setattr('spine.reader.observation_fields', lambda *a: [])
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})

    def intent(_, data):
        for name in ('access.member', 'organization.join_cancel'):
            exact = assistant.explicit_administrative_access(data['request'], name)
            if exact: return {'action': {'action': name, 'payload': {**exact, 'version': 1}}}
        raise AssertionError('Unexpected synthetic command')

    monkeypatch.setattr(assistant.providers, 'model_json', intent)

    def local_client(**kwargs):
        hosted.base_url = kwargs['base_url']; hosted.headers.update(kwargs['headers'])
        return contextlib.nullcontext(hosted)

    monkeypatch.setattr(httpx, 'Client', local_client)

    def run(phase):
        monkeypatch.setattr('sys.argv', [str(SMOKE), BASE, '--credentials', str(credentials), '--state', str(state), '--phase', phase])
        runpy.run_path(str(SMOKE), run_name='__main__')
    return run


def test_disposable_admin_script_all_stages_keep_existing_authority_unchanged(hosted, monkeypatch, tmp_path):
    monkeypatch.setenv('RAILWAY_PROJECT_ID', V2_PROJECT)
    credentials = tmp_path / 'credentials.json'; credentials.write_text(json.dumps({'username': 'admin', 'password': 'synthetic-test-password'}))
    state = tmp_path / 'state.json'
    # An unrelated existing organization must remain unchanged, including policy.
    hosted.post('/api/login', json=json.loads(credentials.read_text()))
    created = hosted.post('/api/actions', json={'action': 'organization.create', 'payload': {'name': 'SYNTHETIC pre-existing organization'}, 'key': 'existing-org-setup'})
    assert created.status_code == 200
    hosted.post('/api/actions', json={'action': 'organization.policy', 'payload': {'actions': ['read.billing']}, 'key': 'existing-org-policy'})
    before = stored()
    provision(monkeypatch, state)
    seed = json.loads(state.read_text())
    assert state.stat().st_mode & 0o777 == 0o600
    after = stored()
    assert after['credentials'] == before['credentials']
    assert set(map(tuple, before['memberships'])) <= set(map(tuple, after['memberships']))
    assert len(after['memberships']) == len(before['memberships']) + 2
    assert all(after['records'][id] == record for id, record in before['records'].items())
    assert after['organizations'] == before['organizations'] and after['clinic_organizations'] == before['clinic_organizations']
    run = runner(hosted, monkeypatch, credentials, state)
    run('setup'); run('review')
    reviewed = json.loads(state.read_text())
    assert reviewed['phase'] == 'reviewed' and set(reviewed['turns']) == {'stale-access', 'tighten-access', 'withdraw-request'}
    with pytest.raises(AssertionError, match='exact review and confirmation persist'): run('readback')
    # API confirmation here is an automated local stand-in, not browser evidence.
    hosted.post('login', json=json.loads(credentials.read_text()))
    for case, purpose in (('tighten-access', 'access'), ('withdraw-request', 'withdrawal')):
        hosted.headers['x-clinic-id'] = seed['clinics'][purpose]['id']
        turn = reviewed['turns'][case]
        response = hosted.post(f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm")
        assert response.status_code == 200, response.text
    run('readback')
    assert json.loads(state.read_text())['phase'] == 'complete'
    after = stored()
    assert after['credentials'] == before['credentials']
    assert all(after['records'][id] == record for id, record in before['records'].items())
    assert all(after['organizations'][id] == organization for id, organization in before['organizations'].items())
    assert set(map(tuple, before['clinic_organizations'])) <= set(map(tuple, after['clinic_organizations']))


@pytest.mark.parametrize('guard', ['wrong_ack', 'wrong_project', 'missing_project', 'local_environment', 'demo_auth', 'missing_account', 'existing_state', 'unapproved_origin'])
def test_service_fixture_guards_fail_before_any_write(hosted, monkeypatch, tmp_path, guard):
    monkeypatch.setenv('RAILWAY_PROJECT_ID', V2_PROJECT)
    state = tmp_path / 'state.json'; account = 'admin'; confirmation = V2_PROJECT
    if guard == 'wrong_ack': confirmation = 'not-v2'
    if guard == 'wrong_project': monkeypatch.setenv('RAILWAY_PROJECT_ID', 'original-broby-is-not-authorized')
    if guard == 'missing_project': monkeypatch.delenv('RAILWAY_PROJECT_ID')
    if guard == 'local_environment': monkeypatch.setenv('BROBY_ENVIRONMENT', 'local')
    if guard == 'demo_auth': monkeypatch.setenv('BROBY_AUTH_MODE', 'demo')
    if guard == 'missing_account': account = 'no-such-acceptance-account'
    if guard == 'existing_state': state.write_text('existing state must not change')
    if guard == 'unapproved_origin': monkeypatch.setenv('BROBY_ALLOWED_ORIGINS', 'https://another.example.test')
    before = stored()
    with pytest.raises(AssertionError): provision(monkeypatch, state, account, confirmation)
    assert stored() == before
    assert not state.exists() or state.read_text() == 'existing state must not change'


def test_fixture_does_not_elevate_an_existing_non_admin_account(hosted, monkeypatch, tmp_path):
    import auth
    monkeypatch.setenv('RAILWAY_PROJECT_ID', V2_PROJECT)
    auth.provision('synthetic-existing-nurse', 'clinic-east-nurse', 'clinic-east', 'Synthetic-test-only-password')
    before = stored()
    with pytest.raises(AssertionError, match='active administrator membership'):
        provision(monkeypatch, tmp_path / 'state.json', 'synthetic-existing-nurse')
    assert stored() == before


def test_hosted_script_refuses_a_state_pointing_to_an_existing_clinic(hosted, monkeypatch, tmp_path):
    monkeypatch.setenv('RAILWAY_PROJECT_ID', V2_PROJECT)
    credentials = tmp_path / 'credentials.json'; credentials.write_text(json.dumps({'username': 'admin', 'password': 'synthetic-test-password'}))
    state = tmp_path / 'state.json'; provision(monkeypatch, state)
    altered = json.loads(state.read_text()); altered['clinics']['access']['id'] = 'clinic-east'; state.write_text(json.dumps(altered))
    before = stored(); run = runner(hosted, monkeypatch, credentials, state)
    with pytest.raises(AssertionError): run('setup')
    assert stored() == before


@pytest.mark.parametrize('lost_action', ['organization.create', 'organization.policy'])
def test_interrupted_setup_or_policy_review_resumes_without_duplicate_authority(hosted, monkeypatch, tmp_path, lost_action):
    monkeypatch.setenv('RAILWAY_PROJECT_ID', V2_PROJECT)
    credentials = tmp_path / 'credentials.json'; credentials.write_text(json.dumps({'username': 'admin', 'password': 'synthetic-test-password'}))
    state = tmp_path / 'state.json'; provision(monkeypatch, state)
    run = runner(hosted, monkeypatch, credentials, state)
    if lost_action == 'organization.policy': run('setup')
    original = hosted.request
    lost = False

    def lose_response(method, url, **kwargs):
        nonlocal lost
        response = original(method, url, **kwargs)
        if not lost and method == 'POST' and str(url) == 'actions' and kwargs.get('json', {}).get('action') == lost_action:
            assert response.status_code == 200
            lost = True
            raise RuntimeError('SYNTHETIC response lost after committed mutation')
        return response

    monkeypatch.setattr(hosted, 'request', lose_response)
    phase = 'setup' if lost_action == 'organization.create' else 'review'
    with pytest.raises(RuntimeError, match='response lost'): run(phase)
    assert lost
    run(phase)
    if phase == 'setup': run('review')
    saved = json.loads(state.read_text())
    assert saved['phase'] == 'reviewed' and saved['stale_policy_verified']
    after = stored()
    assert len(after['organizations']) == 1
    assert after['organizations'][saved['organization']]['locked_actions'] == '["read.inventory"]'
    member = json.loads(after['records'][saved['member']]['data'])
    assert not member.get('read_restrictions')
