"""Cloud boundary regressions, exercised without live provider calls."""
import pytest
from fastapi.testclient import TestClient
import auth, db, main, runtime


@pytest.fixture
def hosted(tmp_path, monkeypatch):
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
