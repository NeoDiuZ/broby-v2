import hashlib
import json
import importlib.util
from pathlib import Path

import pytest
from backup_verification import binary_receipts, file_inventory

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('verify_backup_script',ROOT/'scripts/verify-backup.py')
verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)


def test_missing_and_symlink_data_are_rejected(tmp_path):
    with pytest.raises(ValueError):file_inventory(tmp_path/'missing')
    (tmp_path/'linked').symlink_to(tmp_path/'missing')
    with pytest.raises(ValueError):file_inventory(tmp_path)


def test_every_binary_receipt_is_verified_and_path_escape_is_rejected(tmp_path):
    (tmp_path/'files').mkdir();(tmp_path/'files'/'attachment').write_bytes(b'original file')
    (tmp_path/'audio'/'recording').mkdir(parents=True);(tmp_path/'audio'/'recording'/'0').write_bytes(b'original audio')
    rows=[('attachment',json.dumps({'sha256':hashlib.sha256(b'original file').hexdigest()}))]
    chunks=[('recording',0,hashlib.sha256(b'original audio').hexdigest())]
    assert binary_receipts(rows,chunks,tmp_path)==2
    (tmp_path/'audio'/'recording'/'0').write_bytes(b'corrupted')
    with pytest.raises(ValueError):binary_receipts(rows,chunks,tmp_path)
    with pytest.raises(ValueError):binary_receipts([('../escape','{}')],[],tmp_path)
    with pytest.raises(ValueError):binary_receipts([], [('../escape',0,'x')],tmp_path)


def test_restore_refuses_changed_dump_before_creating_database(tmp_path,monkeypatch):
    backup=tmp_path/'backup';backup.mkdir();(backup/'data').mkdir()
    (backup/'spine.dump').write_bytes(b'changed dump')
    (backup/'manifest.json').write_text(json.dumps({'format':3,'data':'data','postgresql':'spine.dump','tables':{'pms.records':{}},'postgres_sha256':'incorrect','files':{}}))
    monkeypatch.setattr(verifier,'create_engine',lambda *a,**k:pytest.fail('No database access before backup validation'))
    with pytest.raises(ValueError,match='bytes'):verifier.verify(backup,tmp_path/'restore')
    assert not (tmp_path/'restore').exists()


def test_restore_preserves_existing_destination_and_refuses_incomplete_backup(tmp_path):
    (tmp_path/'original').write_text('preserve')
    with pytest.raises(ValueError,match='existing'):verifier.verify(tmp_path,tmp_path/'original')
    (tmp_path/'manifest.json').write_text('{"format":2}')
    (tmp_path/'INCOMPLETE').write_text('interrupted')
    with pytest.raises(ValueError,match='incomplete'):verifier.verify(tmp_path,tmp_path.parent/(tmp_path.name+'-restore'))
    assert (tmp_path/'original').read_text()=='preserve'


def test_backup_refuses_reachable_or_unverifiable_api_and_nested_target(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('backup_script',ROOT/'scripts/backup-local.py')
    backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)
    import socket
    from contextlib import nullcontext
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:nullcontext())
    with pytest.raises(SystemExit,match='Stop the API'):backup.backup(tmp_path/'backup')
    def timeout(*a,**k):raise TimeoutError('unverifiable')
    monkeypatch.setattr(socket,'create_connection',timeout)
    with pytest.raises(SystemExit,match='Cannot verify'):backup.backup(tmp_path/'backup')
    def refused(*a,**k):raise ConnectionRefusedError()
    monkeypatch.setattr(socket,'create_connection',refused)
    monkeypatch.setenv('BROBY_DATA_DIR',str(tmp_path))
    with pytest.raises(SystemExit,match='outside'):backup.backup(tmp_path/'backup')
