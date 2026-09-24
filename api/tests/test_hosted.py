"""Cloud boundary regressions, exercised without live provider calls."""
import pytest
from fastapi.testclient import TestClient
import auth, db, main, runtime


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setattr('spine.reader.native_records',lambda *a,**k:[])
    monkeypatch.setattr(db, 'DB', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('BROBY_ENVIRONMENT', 'staging')
    monkeypatch.setenv('BROBY_AUTH_MODE', 'password')
    monkeypatch.setenv('BROBY_ALLOWED_ORIGINS', 'https://broby.example.test')
    monkeypatch.setenv('BROBY_SPINE_URL', 'postgresql://unused/test')
    monkeypatch.setenv('BROBY_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('BROBY_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('BROBY_ADMIN_PASSWORD', 'synthetic-test-password')
    with TestClient(main.app, base_url='https://broby.example.test') as client:
        yield client


def test_hosted_rejects_forged_demo_identity(hosted):
    for path in ['/api/bootstrap', '/api/v2/patients', '/api/audit', '/api/backup']:
        assert hosted.get(path, headers={'x-actor-id': 'clinic-east-admin'}).status_code == 401


def test_session_is_secure_and_clinic_membership_is_verified(hosted):
    result = hosted.post('/api/login', json={'username':'admin','password':'synthetic-test-password'},
                         headers={'origin':'https://broby.example.test'})
    assert result.status_code == 200
    cookie = result.headers['set-cookie'].lower()
    assert all(flag in cookie for flag in ['secure','httponly','samesite=strict'])
    assert hosted.get('/api/bootstrap').status_code == 200
    assert hosted.get('/api/bootstrap', headers={'x-clinic-id':'clinic-river'}).status_code == 403
    assert hosted.get('/api/bootstrap', headers={'x-actor-id':'clinic-east-nurse'}).json()['actor']['id'] == 'clinic-east-admin'
    assert hosted.post('/api/logout').status_code == 200
    assert hosted.get('/api/bootstrap').status_code == 401


def test_foreign_origins_cannot_login_or_mutate(hosted):
    for origin in ['https://evil.example', 'chrome-extension://untrusted', 'null']:
        assert hosted.post('/api/login', headers={'origin':origin},
                           json={'username':'admin','password':'synthetic-test-password'}).status_code == 403
    assert hosted.post('/api/logout', headers={'sec-fetch-site':'cross-site'}).status_code == 403


def test_admin_bootstrap_does_not_reset_existing_password(hosted, monkeypatch):
    monkeypatch.setenv('BROBY_ADMIN_PASSWORD','different-test-password')
    runtime.provision_admin()
    assert hosted.post('/api/login',json={'username':'admin','password':'synthetic-test-password'}).status_code == 200


def test_owner_saved_access_uses_a_secure_cookie(hosted):
    hosted.post('/api/login',json={'username':'admin','password':'synthetic-test-password'})
    shared=hosted.post('/api/actions',json={'action':'share.create','payload':{'patient_id':'milo'},'key':'hosted-owner-test'}).json()
    token=shared['url'].split('token=')[1]
    response=hosted.post('/api/owner/'+token+'/claim')
    assert response.status_code == 200
    assert 'secure' in response.headers['set-cookie'].lower()


def test_hosted_startup_fails_closed(monkeypatch):
    monkeypatch.setenv('BROBY_ENVIRONMENT','staging')
    monkeypatch.setenv('BROBY_AUTH_MODE','demo')
    with pytest.raises(RuntimeError,match='password authentication'):runtime.validate()


def test_readiness_fails_when_postgres_is_unavailable(hosted, monkeypatch):
    from spine import database
    def unavailable():raise RuntimeError('Do not expose connection secrets')
    monkeypatch.setattr(database,'engine',unavailable)
    response=hosted.get('/api/ready')
    assert response.status_code == 503
    assert 'secrets' not in response.text


def test_device_access_uses_actual_session_deadline_and_never_exposes_secrets(hosted):
    from datetime import datetime, timezone, timedelta
    before = hosted.get('/api/session')
    assert before.json()['expires_at'] is None
    assert before.headers['cache-control'] == 'no-store'
    hosted.post('/api/login', json={'username':'admin','password':'synthetic-test-password'})
    response = hosted.get('/api/session')
    data = response.json()
    assert data['authenticated'] and data['username'] == 'admin'
    deadline = datetime.fromisoformat(data['expires_at'])
    assert datetime.now(timezone.utc) < deadline <= datetime.now(timezone.utc)+timedelta(hours=12)
    assert set(data) == {'authenticated','mode','username','expires_at'}
    assert response.headers['cache-control'] == 'no-store'
    hosted.post('/api/logout')
    assert hosted.get('/api/session').json()['expires_at'] is None


def test_public_enquiry_is_durable_private_and_replay_safe(hosted):
    import uuid
    payload = {'submission_key': str(uuid.uuid4()), 'contact_name': 'Dr Test',
               'clinic_name': 'Synthetic Clinic', 'country': 'SG',
               'contact_channel': 'email', 'contact_handle': 'test@example.invalid'}
    first = hosted.post('/api/marketing/leads/submit', json=payload)
    assert first.status_code == 201 and first.json()['received']
    assert hosted.post('/api/marketing/leads/submit', json=payload).json() == first.json()
    assert hosted.post('/api/marketing/leads/submit', json={**payload, 'clinic_name': 'Changed'}).status_code == 409
    assert hosted.get('/api/marketing/leads').status_code == 401
    hosted.post('/api/login', json={'username': 'admin', 'password': 'synthetic-test-password'})
    result = hosted.get('/api/marketing/leads')
    assert result.status_code == 200 and result.json()['outstanding'] == 1
    lead = result.json()['leads'][0]
    assert lead['id'] == first.json()['reference']
    assert lead['contact_handle'] == payload['contact_handle']
    assert 'submission_key' not in lead and 'payload_hash' not in lead
    marked = hosted.post('/api/marketing/leads/' + lead['id'] + '/contacted')
    assert marked.status_code == 200 and marked.json()['changed']
    assert hosted.post('/api/marketing/leads/' + lead['id'] + '/contacted').json()['changed'] is False
    assert hosted.get('/api/marketing/leads').json()['outstanding'] == 0


def test_public_enquiry_validates_and_limits_repeated_contact(hosted):
    import uuid
    base = {'contact_name': 'Dr Test', 'country': 'MY', 'contact_channel': 'email',
            'contact_handle': 'test@example.invalid'}
    invalid = hosted.post('/api/marketing/leads/submit', json={**base, 'submission_key': str(uuid.uuid4()),
                                                                  'contact_handle': 'not-an-email'})
    assert invalid.status_code == 422
    trap = hosted.post('/api/marketing/leads/submit', json={**base, 'submission_key': str(uuid.uuid4()),
                                                               'company_website': 'https://bot.example'})
    assert trap.status_code == 201 and trap.json() == {'received': True}
    for handle in ['test@example.invalid', 'TEST@example.invalid', 'Test@Example.Invalid']:
        assert hosted.post('/api/marketing/leads/submit', json={**base, 'submission_key': str(uuid.uuid4()),
                                                                    'contact_handle': handle}).status_code == 201
    assert hosted.post('/api/marketing/leads/submit', json={**base, 'submission_key': str(uuid.uuid4())}).status_code == 429
    hosted.post('/api/login', json={'username': 'admin', 'password': 'synthetic-test-password'})
    assert hosted.get('/api/marketing/leads').json()['outstanding'] == 3


def test_clinic_staff_cannot_read_or_acknowledge_site_enquiries(hosted):
    import uuid
    payload = {'submission_key': str(uuid.uuid4()), 'contact_name': 'Dr Test',
               'country': 'SG', 'contact_channel': 'email', 'contact_handle': 'private@example.invalid'}
    lead_id = hosted.post('/api/marketing/leads/submit', json=payload).json()['reference']
    auth.provision('other-admin', 'clinic-river-admin', 'clinic-river', 'synthetic-other-password')
    hosted.post('/api/login', json={'username': 'other-admin', 'password': 'synthetic-other-password'})
    assert hosted.get('/api/marketing/leads').status_code == 403
    assert hosted.post('/api/marketing/leads/' + lead_id + '/contacted').status_code == 403
