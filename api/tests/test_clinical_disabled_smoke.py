"""Hosted disabled acceptance remains explicitly bound and cannot send alerts."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

spec = importlib.util.spec_from_file_location('clinical_disabled_smoke', Path(__file__).resolve().parents[2] / 'scripts/check-clinical-escalation-disabled.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
BASE = 'https://v2.example.test'
SNAPSHOT = {'mode': 'password', 'clinic': {'id': 'clinic-target', 'kind': 'clinic', 'data': {'name': 'SYNTHETIC acceptance'}},
            'actor': {'id': 'target-admin', 'kind': 'member', 'clinic_id': 'clinic-target', 'data': {'active': True}},
            'records': [{'id': 'private-policy-id', 'kind': 'owner_policy', 'data': {'escalation': {'enabled': False}, 'text': 'PRIVATE CLINICAL CONTENT'}}]}
STATUS = {'mode': 'disabled', 'routes': [], 'monitor_state': 'disabled', 'incidents': [], 'counts': {}, 'unresolved_count': 0, 'truncated': False}


@pytest.fixture
def args(tmp_path):
    credentials = tmp_path / 'credentials.json'
    credentials.write_text(json.dumps({'username': 'private-user', 'password': 'private-password'}))
    return SimpleNamespace(base_url=BASE, credentials=credentials, clinic='clinic-target', actor='target-admin',
                           clinic_name='SYNTHETIC acceptance', output=tmp_path / 'evidence.json')


def server(snapshot=None, status=None, error=None):
    calls = []
    def transport(request):
        calls.append(request)
        assert request.headers['x-clinic-id'] == 'clinic-target'
        assert request.headers['x-actor-id'] == 'target-admin'
        assert request.headers['origin'] == BASE
        path = request.url.path
        assert (request.method, path) in {('POST', '/api/login'), ('POST', '/api/logout'),
                                          ('GET', '/api/bootstrap'), ('GET', '/api/clinical-escalations')}
        if error and path == error[0]:
            return httpx.Response(error[1], json={'detail': 'PRIVATE SERVER CONTENT'}, headers={'location': 'https://unexpected.example.test'})
        if path == '/api/login':
            assert json.loads(request.content) == {'username': 'private-user', 'password': 'private-password'}
            # Login may return a different default clinic. It must never be followed.
            return httpx.Response(200, json={'clinic': 'new-default', 'actor': 'new-admin'}, headers={'set-cookie': 'broby_session=private-cookie; Path=/'})
        assert request.headers.get('cookie') == 'broby_session=private-cookie'
        return httpx.Response(200, json=(snapshot if snapshot is not None else SNAPSHOT) if path == '/api/bootstrap'
                              else (status if status is not None else STATUS) if path == '/api/clinical-escalations' else {'ok': True})
    def factory(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.Client(transport=httpx.MockTransport(transport), **kwargs)
    return factory, calls


def test_exact_binding_survives_login_default_drift_and_writes_only_safe_private_evidence(args):
    factory, calls = server()
    result = helper.run(args, factory)
    assert result['passed'] == 9
    assert [(r.method, r.url.path) for r in calls] == [('POST', '/api/login'), ('GET', '/api/bootstrap'), ('GET', '/api/clinical-escalations'), ('POST', '/api/logout')]
    assert json.loads(args.output.read_text()) == result
    assert args.output.stat().st_mode & 0o777 == 0o600
    assert all(secret not in args.output.read_text() for secret in ('private-user', 'private-password', 'private-cookie', 'private-policy-id', 'PRIVATE CLINICAL CONTENT'))
    # Rerun is safe only for the same explicit binding.
    helper.run(args, server()[0])


@pytest.mark.parametrize('change', ['clinic', 'name', 'actor', 'membership', 'inactive', 'mode', 'partial', 'no_records', 'policy'])
def test_wrong_identity_incomplete_snapshot_or_enabled_policy_stops_before_status(args, change):
    snapshot = copy.deepcopy(SNAPSHOT)
    if change == 'clinic': snapshot['clinic']['id'] = 'another-clinic'
    elif change == 'name': snapshot['clinic']['data']['name'] = 'Real clinic'
    elif change == 'actor': snapshot['actor']['id'] = 'another-admin'
    elif change == 'membership': snapshot['actor']['clinic_id'] = 'another-clinic'
    elif change == 'inactive': snapshot['actor']['data']['active'] = False
    elif change == 'mode': snapshot['mode'] = 'local-demo'
    elif change == 'partial': snapshot['unchanged'] = True
    elif change == 'no_records': snapshot.pop('records')
    elif change == 'policy': snapshot['records'][0]['data']['escalation']['enabled'] = True
    factory, calls = server(snapshot=snapshot)
    with pytest.raises(helper.AcceptanceError): helper.run(args, factory)
    assert [r.url.path for r in calls] == ['/api/login', '/api/bootstrap', '/api/logout']
    assert not args.output.exists()


@pytest.mark.parametrize('change', [{'mode': 'webhook'}, {'routes': ['primary']}, {'monitor_state': 'fresh'},
                                  {'incidents': [{'id': 'incident'}]}, {'counts': {'acknowledged': 1}},
                                  {'unresolved_count': 1}, {'truncated': True}])
def test_each_disabled_condition_is_required_and_failure_never_emits_success(args, change):
    factory, calls = server(status={**STATUS, **change})
    with pytest.raises(helper.AcceptanceError): helper.run(args, factory)
    assert calls[-1].url.path == '/api/logout'
    assert not args.output.exists()


@pytest.mark.parametrize('base', ['http://v2.example.test', 'https://user:secret@v2.example.test',
                                 'https://v2.example.test/path', 'https://v2.example.test?secret=x',
                                 'https://v2.example.test#fragment', 'https://'])
def test_unsafe_origin_is_rejected_before_credentials_are_sent(args, base):
    args.base_url = base
    with pytest.raises(helper.AcceptanceError): helper.run(args, lambda **_: pytest.fail('Must not connect'))


def test_exact_synthetic_name_required_before_login(args):
    args.clinic_name = 'Real clinic'
    with pytest.raises(helper.AcceptanceError, match='SYNTHETIC'): helper.run(args, lambda **_: pytest.fail('Must not connect'))


def test_existing_evidence_cannot_be_rebound_and_credentials_cannot_be_overwritten(args):
    args.output.write_text(json.dumps({'binding': {'clinic': 'another-clinic'}}))
    with pytest.raises(helper.AcceptanceError, match='different target'): helper.run(args, lambda **_: pytest.fail('Must not connect'))
    args.output = args.credentials
    before = args.credentials.read_text()
    with pytest.raises(helper.AcceptanceError, match='differ'): helper.run(args, lambda **_: pytest.fail('Must not connect'))
    assert args.credentials.read_text() == before


@pytest.mark.parametrize('path,code', [('/api/login', 302), ('/api/bootstrap', 403), ('/api/clinical-escalations', 302), ('/api/logout', 503)])
def test_redirects_authorization_and_logout_failure_are_not_accepted_or_leaked(args, path, code):
    factory, calls = server(error=(path, code))
    with pytest.raises(helper.AcceptanceError) as caught: helper.run(args, factory)
    assert 'PRIVATE SERVER CONTENT' not in str(caught.value) and 'unexpected.example' not in str(caught.value)
    assert all(r.url.host == 'v2.example.test' for r in calls)
    assert not args.output.exists()
