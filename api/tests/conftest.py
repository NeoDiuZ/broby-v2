"""Opt-in full-suite acceptance against the PostgreSQL PMS backend.

Every case receives a disposable schema. The normal suite keeps SQLite coverage;
CI runs both, so a dialect difference cannot be hidden by an adapter-only test.
"""
import os,uuid
import pytest
from sqlalchemy import create_engine


@pytest.fixture(autouse=True)
def postgres_pms_backend(monkeypatch):
    if os.getenv('BROBY_TEST_PMS_POSTGRES')!='1':
        yield
        return
    connection_url=os.getenv('BROBY_TEST_SPINE_URL') or os.getenv('BROBY_SPINE_URL')
    assert connection_url,'PostgreSQL acceptance requires the isolated test database'
    namespace='pms_suite_'+uuid.uuid4().hex
    monkeypatch.setenv('BROBY_PMS_STORE','postgres')
    monkeypatch.setenv('BROBY_PMS_URL',connection_url)
    monkeypatch.setenv('BROBY_PMS_SCHEMA',namespace)
    try:yield
    finally:
        from pms_postgres import pool,url
        pool(url(),namespace).dispose()
        with create_engine(connection_url).begin() as c:c.exec_driver_sql('DROP SCHEMA IF EXISTS '+namespace+' CASCADE')
