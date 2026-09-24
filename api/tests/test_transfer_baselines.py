"""Recovery from pre-revision imports without claiming historical equivalence."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import db, main, transfers
from test_integrity import isolated, act, get, err
from test_transfers import TARGET, HEADERS, request, preview, accept, media


def legacy_patient(client, files=False):
    """Reproduce the old import's actual layout, which has no source manifest."""
    if files:
        media(client)
    _, old = request(client)
    original = next(x for x in preview(client, old)['items'] if x['kind'] == 'event')
    with db.connection(True) as c:
        owner = db.record(c, 'owner', 'clinic-river', {'name': 'Earlier copied owner', 'phone': 'old contact'})
        patient = db.record(c, 'patient', 'clinic-river', {'name': 'Locally reviewed Luna', 'species': 'Cat', 'owner_id': owner['id'], 'transfer_request_id': old['id']})
        source = db.record(c, 'source', 'clinic-river', {'patient_id': patient['id'], 'title': 'Transferred approved record',
            'text': 'Earlier source finding', 'category': 'clinical', 'section': 'Objective', 'author': 'Old transfer',
            'origin_event_id': original['origin_id'], 'origin_patient_id': 'luna', 'origin_clinic_id': 'clinic-east'})
        event = db.record(c, 'event', 'clinic-river', {'patient_id': patient['id'], 'title': 'Earlier finding with local review',
            'body': 'Earlier source finding and receiving clinician edit', 'category': 'clinical', 'source_ids': [source['id']],
            'occurred_at': db.now(), 'approved': False, 'transfer_request_id': old['id']})
        if files:
            path = db.DATA / 'files' / 'legacy-copy'
            db.transaction_file(c, path, b'Earlier file bytes')
            db.record(c, 'attachment', 'clinic-river', {'patient_id': patient['id'], 'name': 'Earlier file', 'mime': 'text/plain',
                'path': str(path), 'size': 18, 'sha256': __import__('hashlib').sha256(b'Earlier file bytes').hexdigest(),
                'approved': False, 'transfer_request_id': old['id'], 'origin_id': 'older-file'})
        c.execute('INSERT INTO transferred_patients VALUES(?,?,?,?)', ('clinic-east', 'luna', 'clinic-river', patient['id']))
        c.execute("UPDATE transfer_requests SET status='accepted',result=? WHERE id=?", (json.dumps({'id': patient['id']}), old['id']))
    base, pending = request(client)
    return base, pending, patient, event, old


def establish(client, r, **kwargs):
    return accept(client, r, establish_baseline=True, baseline_reason='Compared earlier records; accept a separate current source baseline.', **kwargs)


def test_baseline_preserves_history_bytes_identity_and_stock_then_deduplicates():
    client = TestClient(main.app)
    _, r, patient, event, old = legacy_patient(client, files=True)
    with db.connection() as c:
        before = db.all_records(c, 'clinic-river')
    review = preview(client, r)
    assert review['baseline_required'] and review['destination_patient'] == patient
    assert review['destination_owner']['data']['phone'] == 'old contact'
    assert review['baseline']['earlier_requests'] == [{'id': old['id'], 'status': 'accepted'}]
    assert len(review['baseline']['existing_records']) == 3
    assert 'path' not in next(x for x in review['baseline']['existing_records'] if x['kind'] == 'attachment')['data']
    assert 'grant_token' not in json.dumps(review)
    assert review['counts']['changed'] == review['counts']['unchanged'] == 0
    for flag in [None, False, 'true', 1]:
        err(409, lambda: accept(client, r, establish_baseline=flag, baseline_reason='A sufficiently detailed reason'))
    for reason in [None, '', 'too short', ' ' * 20, 'x' * 1001, 123]:
        err(422, lambda: accept(client, r, establish_baseline=True, baseline_reason=reason))
    with db.connection() as c:
        assert db.all_records(c, 'clinic-river') == before
    result = establish(client, r)
    assert result['id'] == patient['id'] and result['baseline_id']
    with db.connection() as c:
        assert all(db.get(c, x['id']) == x for x in before)
        baseline = db.get(c, result['baseline_id'])
        assert baseline['data']['reviewed_by'] == TARGET['actor']
        assert baseline['data']['reviewed_digest'] == review['digest']
        assert len(baseline['data']['preserved_records']) == 5
        copied = [x for x in db.all_records(c, 'clinic-river', 'event') if x['data'].get('transfer_baseline_id') == result['baseline_id']]
        assert len(copied) == len(review['items']) and all(not x['data']['approved'] for x in copied)
        notice = next(x for x in db.all_records(c, 'clinic-river', 'event') if x['data']['title'] == 'Reviewed transfer baseline')
        assert notice['data']['source_ids'] and not notice['data']['approved']
        assert 'may duplicate' in notice['data']['body']
        after = db.all_records(c, 'clinic-river')
    assert (db.DATA / 'files' / 'legacy-copy').read_bytes() == b'Earlier file bytes'
    assert act('transfer.accept', {'id': r['id']}, **TARGET) == result
    _, again = request(client)
    assert preview(client, again)['baseline_required'] is False
    repeated = accept(client, again)
    assert repeated['baseline_id'] is None and repeated['counts']['new'] == repeated['counts']['changed'] == 0
    with db.connection() as c:
        assert db.all_records(c, 'clinic-river') == after
    # A later correction compares to the current baseline, not the unknowable old copy.
    with db.connection(True) as c:
        source_id = next(x['origin_id'] for x in review['items'] if x['kind'] == 'event')
        source = db.get(c, source_id)
        db.update(c, source, {**source['data'], 'body': 'Later corrected source'})
    _, changed = request(client)
    assert preview(client, changed)['counts']['changed'] == 1
    err(409, lambda: accept(client, changed))
    assert accept(client, changed, review_changes=True)['counts']['changed'] == 1
    assert get(event['id']) == event and get(patient['id']) == patient


@pytest.mark.parametrize('change', ['source', 'local_event', 'owner', 'new_local_record', 'prior_request'])
def test_baseline_rejects_every_stale_review(change):
    client = TestClient(main.app)
    _, r, patient, event, old = legacy_patient(client)
    review = preview(client, r)
    with db.connection(True) as c:
        if change == 'new_local_record':
            db.event(c, 'clinic-river', patient['id'], 'clinical', 'New local finding', 'New receiving evidence')
        elif change == 'prior_request':
            c.execute("UPDATE transfer_requests SET status='revoked' WHERE id=?", (old['id'],))
        else:
            row = db.get(c, 'luna' if change == 'source' else patient['data']['owner_id'] if change == 'owner' else event['id'])
            db.update(c, row, {**row['data'], 'name': 'Change after review'})
    err(409, lambda: act('transfer.accept', {'id': r['id'], 'expected_digest': review['digest'],
        'establish_baseline': True, 'baseline_reason': 'Review before a concurrent edit'}, **TARGET))
    with db.connection() as c:
        assert not db.all_records(c, 'clinic-river', 'transfer_baseline')
        assert not c.execute('SELECT * FROM transfer_revisions').fetchall()


def test_baseline_respects_revocation_role_and_feature_locks():
    client = TestClient(main.app)
    base, r, patient, _, _ = legacy_patient(client)
    assert client.get('/api/transfers/' + r['id'] + '/preview').status_code == 404
    assert client.get('/api/transfers/' + r['id'] + '/preview', headers={**HEADERS, 'x-actor-id': 'clinic-river-nurse'}).status_code == 403
    err(403, lambda: act('transfer.accept', {'id': r['id']}, clinic='clinic-river', actor='clinic-river-nurse'))
    locked = get('clinic-river')
    act('feature_locks.save', {'version': locked['version'], 'actions': ['transfer.accept']}, clinic='clinic-river', actor='clinic-river-admin')
    err(403, lambda: act('transfer.accept', {'id': r['id']}, **TARGET))
    act('share.revoke', {'token': base.rsplit('/', 1)[-1]})
    assert client.get('/api/transfers/' + r['id'] + '/preview', headers={**HEADERS, 'x-actor-id': 'clinic-river-admin'}).status_code == 404
    assert get(patient['id']) == patient


def test_baseline_limits_and_patient_isolation(monkeypatch):
    client = TestClient(main.app)
    _, r, patient, _, _ = legacy_patient(client)
    with db.connection(True) as c:
        db.record(c, 'source', 'clinic-river', {'patient_id': 'another-patient', 'text': 'Other patient private record'})
    review = preview(client, r)
    assert 'Other patient private record' not in json.dumps(review)
    monkeypatch.setattr(transfers, 'MAX_ITEMS', 1)
    assert client.get('/api/transfers/' + r['id'] + '/preview', headers=HEADERS).status_code == 422


def test_baseline_rolls_back_records_revisions_and_files_on_failure():
    client = TestClient(main.app)
    _, r, _, _, _ = legacy_patient(client, files=True)
    before_files = {p for p in db.DATA.rglob('*') if p.is_file()}
    with db.connection(True) as c:
        before = db.all_records(c, 'clinic-river')
        from db_faults import reject_transfer_audit
        reject_transfer_audit(c,'baseline_failure','baseline injected failure')
    with pytest.raises(Exception, match='baseline injected failure'):
        establish(client, r)
    assert {p for p in db.DATA.rglob('*') if p.is_file()} == before_files
    with db.connection() as c:
        assert db.all_records(c, 'clinic-river') == before
        assert not c.execute('SELECT * FROM transfer_revisions').fetchall()
        assert c.execute('SELECT status FROM transfer_requests WHERE id=?', (r['id'],)).fetchone()[0] == 'pending'


def test_concurrent_baseline_requests_cannot_append_twice():
    client = TestClient(main.app)
    _, first, _, _, _ = legacy_patient(client)
    _, second = request(client)
    review = preview(client, second)
    establish(client, first)
    err(409, lambda: act('transfer.accept', {'id': second['id'], 'expected_digest': review['digest'],
        'establish_baseline': True, 'baseline_reason': 'Earlier concurrently reviewed baseline'}, **TARGET))
    err(409, lambda: establish(client, second))
    assert accept(client, second)['counts']['unchanged'] == len(review['items'])
    with db.connection() as c:
        assert len(db.all_records(c, 'clinic-river', 'transfer_baseline')) == 1


def test_normal_first_import_cannot_claim_legacy_baseline():
    client = TestClient(main.app)
    _, r = request(client)
    err(409, lambda: establish(client, r))
    assert accept(client, r)['baseline_id'] is None


def test_native_receiving_facts_are_in_review_and_invalidate_stale_acceptance(monkeypatch):
    client = TestClient(main.app)
    _, r, patient, _, _ = legacy_patient(client)
    native = {'id': 'native-local-finding', 'kind': 'event', 'clinic_id': 'clinic-river', 'version': 1,
        'created_at': db.now(), 'updated_at': db.now(), 'data': {'patient_id': patient['id'], 'body': 'Receiving native fact', 'native_spine': True}}
    monkeypatch.setattr('spine.reader.native_records', lambda clinic, *a: [native] if clinic == 'clinic-river' else [])
    review = preview(client, r)
    assert any(x['id'] == native['id'] for x in review['baseline']['existing_records'])
    native['data']['body'] = 'Changed native receiving fact'
    err(409, lambda: act('transfer.accept', {'id': r['id'], 'expected_digest': review['digest'],
        'establish_baseline': True, 'baseline_reason': 'Review before native receiving change'}, **TARGET))
