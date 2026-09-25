"""Deployment configuration and idempotent first-boot account provisioning."""
import os
from urllib.parse import urlsplit


def hosted():
    return os.getenv('BROBY_ENVIRONMENT', 'local') != 'local'


def allowed_origins():
    configured = os.getenv('BROBY_ALLOWED_ORIGINS', '')
    if configured:
        return {value.strip().rstrip('/') for value in configured.split(',') if value.strip()}
    return set() if hosted() else {
        'http://127.0.0.1:3100', 'http://localhost:3100', 'http://127.0.0.1:8100',
    }


def worker_mode():
    value = os.getenv('BROBY_WORKER_MODE', 'embedded')
    if value not in ('embedded', 'external'):
        raise RuntimeError('BROBY_WORKER_MODE must be embedded or external')
    return value


def validate():
    worker_mode()
    if os.getenv('BROBY_PROCESS_ROLE', 'api') not in ('api', 'worker'):
        raise RuntimeError('BROBY_PROCESS_ROLE must be api or worker')
    if not hosted():
        return
    if os.getenv('BROBY_AUTH_MODE') != 'password':
        raise RuntimeError('Hosted deployments require password authentication')
    if not os.getenv('BROBY_SPINE_URL') or not os.getenv('BROBY_DATA_DIR'):
        raise RuntimeError('Hosted deployments require PostgreSQL and a persistent data directory')
    if not allowed_origins() or any(urlsplit(origin).scheme != 'https' for origin in allowed_origins()):
        raise RuntimeError('Hosted deployments require explicit HTTPS browser origins')


def provision_admin():
    import auth
    from db import connection
    username = os.getenv('BROBY_ADMIN_USERNAME', '')
    password = os.getenv('BROBY_ADMIN_PASSWORD', '')
    if not username:
        return
    with connection() as c:
        exists = c.execute('SELECT 1 FROM credentials WHERE username=?', (username,)).fetchone()
    if not exists:
        auth.provision(username, os.getenv('BROBY_ADMIN_MEMBER', 'clinic-east-admin'),
                       os.getenv('BROBY_ADMIN_CLINIC', 'clinic-east'), password)
