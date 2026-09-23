"""Consent boundaries, immutable updates and binary transaction acceptance."""
import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import db, main, transfers
from test_integrity import isolated, act, get, rows, err

TARGET = {'clinic': 'clinic-river', 'actor': 'clinic-river-vet'}
HEADERS = {'x-clinic-id': 'clinic-river', 'x-actor-id': 'clinic-river-vet'}


def request(client, **scope):
    grant = act('share.create', {'patient_id': 'luna'})
    base = '/api/owner/' + grant['id']
    response = client.post(base + '/transfers', json={'target_clinic': 'clinic-river', 'consent': True, **scope})
    assert response.status_code == 200, response.text
    return base, response.json()


def preview(client, r):
    response = client.get('/api/transfers/' + r['id'] + '/preview', headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def accept(client, r, **p):
    review = preview(client, r)
    return act('transfer.accept', {'id': r['id'], 'expected_digest': review['digest'], **p}, **TARGET)


def media(client):
    res = client.post('/api/uploads', data={'patient_id': 'luna'}, files={'file': ('transfer.txt', b'Approved file content', 'text/plain')})
    assert res.status_code == 200, res.text
    f = res.json()
    act('attachment.approve', {'id': f['id'], 'version': f['version'], 'approved': True})
    recording = act('recording.create', {'patient_id': 'luna', 'consultation_id': 'consult-luna'})
    for i, content in enumerate([b'original audio start', b'original audio end']):
        assert client.put(f"/api/recordings/{recording['id']}/chunks/{i}", content=content).status_code == 200
    r = act('recording.complete', {'id': recording['id'], 'expected_chunks': 2, 'duration': 8})
    act('recording.approve', {'id': r['id'], 'version': r['version'], 'approved': True})
    stock = next(r for r in rows('inventory') if r['data']['unit'] == 'tablet')
    medication = act('medication.dispense', {'patient_id': 'luna', 'inventory_id': stock['id'], 'version': stock['version'], 'quantity': 2,
                    'dose': 'Source veterinarian supplied dose', 'frequency': 'Source supplied frequency', 'instructions': 'Original instructions'})
    return f, recording, medication


def test_default_scope_is_notes_and_files_only():
    client = TestClient(main.app)
    media(client)
    _, r = request(client)
    review = preview(client, r)
    assert not review['scope']['audio'] and not review['scope']['medications']
    assert {x['kind'] for x in review['items']} == {'identity', 'event', 'file'}
    out = accept(client, r)
    assert out['files_copied'] == 1 and out['audio_copied'] == out['medication_histories'] == 0


def test_exact_media_history_and_revocation_independence():
    client = TestClient(main.app)
    f, audio, med = media(client)
    # Unapproved source text and provider/session state must never be transferred.
    with db.connection(True) as c:
        source = db.record(c, 'source', 'clinic-east', {'patient_id': 'luna', 'text': 'PRIVATE TRANSCRIPT', 'speaker_labels': {'0': 'private name'}})
        original = db.get(c, audio['id'])
        db.update(c, original, {**original['data'], 'transcript_source_id': source['id'], 'refinement_job_id': 'private-job'})
        stock_before = db.all_records(c, 'clinic-river', 'inventory')
    base, r = request(client, include_audio=True, include_medications=True)
    review = preview(client, r)
    assert 'PRIVATE TRANSCRIPT' not in str(review) and 'private-job' not in str(review)
    out = accept(client, r)
    assert out['audio_copied'] == out['medication_histories'] == out['files_copied'] == 1
    with db.connection() as c:
        assert db.all_records(c, 'clinic-river', 'inventory') == stock_before
        assert not db.all_records(c, 'clinic-river', 'medication')
        history = db.all_records(c, 'clinic-river', 'medication_history')[0]
        assert history['data']['externally_recorded'] and history['data']['dose'] == med['data']['dose']
        assert 'inventory_id' not in history['data'] and 'lots' not in history['data']
        copied_audio = db.all_records(c, 'clinic-river', 'recording')[0]
        copied_file = db.all_records(c, 'clinic-river', 'attachment')[0]
        assert not copied_audio['data']['approved'] and not copied_file['data']['approved']
        assert copied_audio['data']['consultation_id'] == out['consultation_id']
        assert 'transcript_source_id' not in copied_audio['data']
        assert Path(copied_file['data']['path']).read_bytes() == b'Approved file content'
        assert not any(x['data']['approved'] for x in db.all_records(c, 'clinic-river', 'event'))
    act('share.revoke', {'token': base.rsplit('/', 1)[-1]})
    assert client.get('/api/recordings/' + copied_audio['id'] + '/audio', headers=HEADERS).content == b'original audio startoriginal audio end'
    assert act('transfer.accept', {'id': r['id']}, **TARGET) == out
    assert client.get(base).status_code == 404
    own = act('share.create', {'patient_id': out['id']}, **TARGET)
    vault = client.get('/api/owner/' + own['id']).json()
    assert not vault['audio'] and not vault['events'] and not vault['files'] and not vault['medications']


def test_repeated_requests_skip_every_origin_record():
    client = TestClient(main.app)
    media(client)
    _, first = request(client, include_audio=True, include_medications=True)
    one = accept(client, first)
    with db.connection() as c:
        before = db.all_records(c, 'clinic-river')
    _, second = request(client, include_audio=True, include_medications=True)
    two = accept(client, second)
    assert two['id'] == one['id'] and two['counts']['new'] == two['counts']['changed'] == 0
    assert two['files_copied'] == two['audio_copied'] == two['medication_histories'] == two['transferred_events'] == 0
    with db.connection() as c:
        assert db.all_records(c, 'clinic-river') == before


def test_new_and_changed_sources_append_without_overwriting_local_edits():
    client = TestClient(main.app)
    _, first = request(client)
    first_plan = preview(client, first)
    origin = next(x for x in first_plan['items'] if x['kind'] == 'event')
    one = accept(client, first)
    with db.connection(True) as c:
        imported = next(x for x in db.all_records(c, 'clinic-river', 'event') if x['data']['origin_id'] == origin['origin_id'])
        edited = db.update(c, imported, {**imported['data'], 'body': 'Receiving veterinarian local review'})
        source = db.get(c, origin['origin_id'])
        db.update(c, source, {**source['data'], 'body': 'Source corrected finding'})
        db.event(c, 'clinic-east', 'luna', 'clinical', 'New approved update', 'New approved source content', approved=True)
        patient = db.get(c, one['id'])
        local_patient = db.update(c, patient, {**patient['data'], 'name': 'Locally corrected identity'})
    _, second = request(client)
    plan = preview(client, second)
    assert plan['counts'] == {'new': 1, 'changed': 1, 'unchanged': 1}
    changed = next(x for x in plan['items'] if x['state'] == 'changed')
    assert changed['destination_copy']['data']['body'] == edited['data']['body']
    err(409, lambda: act('transfer.accept', {'id': second['id'], 'expected_digest': plan['digest']}, **TARGET))
    two = accept(client, second, review_changes=True)
    assert two['id'] == one['id'] and two['transferred_events'] == 2
    assert get(edited['id']) == edited and get(one['id']) == local_patient
    with db.connection() as c:
        copies = [x for x in db.all_records(c, 'clinic-river', 'event') if x['data'].get('origin_id') == origin['origin_id']]
        assert len(copies) == 2 and {x['data']['origin_revision'] for x in copies} == {1, 2}


@pytest.mark.parametrize('change', ['source', 'destination', 'approval', 'identity'])
def test_preview_rejects_changes_since_review(change):
    client = TestClient(main.app)
    _, first = request(client)
    one = accept(client, first)
    _, r = request(client)
    plan = preview(client, r)
    item = next(x for x in plan['items'] if x['kind'] == 'event')
    with db.connection(True) as c:
        if change == 'destination':
            source = db.get(c, item['destination_copy']['id'])
            db.update(c, source, {**source['data'], 'body': 'Receiving edit after preview'})
        elif change == 'identity':
            source = db.get(c, one['id'])
            db.update(c, source, {**source['data'], 'name': 'Receiving edit after preview'})
        else:
            source = db.get(c, item['origin_id'])
            db.update(c, source, {**source['data'], **({'body': 'Source edit after preview'} if change == 'source' else {'approved': False})})
    err(409, lambda: act('transfer.accept', {'id': r['id'], 'expected_digest': plan['digest'], 'review_changes': True}, **TARGET))


@pytest.mark.parametrize('invalid', ['request-revoke', 'grant-revoke', 'expiry', 'wrong-patient'])
def test_revocation_expiry_and_patient_binding(invalid):
    client = TestClient(main.app)
    base, r = request(client)
    plan = preview(client, r)
    if invalid == 'request-revoke':
        assert client.delete(base + '/transfers/' + r['id']).status_code == 200
    elif invalid == 'grant-revoke':
        act('share.revoke', {'token': base.rsplit('/', 1)[-1]})
    else:
        with db.connection(True) as c:
            if invalid == 'expiry':
                c.execute('UPDATE transfer_requests SET expires_at=? WHERE id=?', ('2000-01-01', r['id']))
            else:
                c.execute('UPDATE grants SET patient_id=? WHERE token=?', ('milo', base.rsplit('/', 1)[-1]))
    err(404 if invalid == 'grant-revoke' else 409, lambda: act('transfer.accept', {'id': r['id'], 'expected_digest': plan['digest']}, **TARGET))
    assert not client.get('/api/transfers/incoming', headers=HEADERS).json()


def test_permission_preview_and_missing_digest():
    client = TestClient(main.app)
    _, r = request(client)
    route = '/api/transfers/' + r['id'] + '/preview'
    assert client.get(route).status_code == 404
    assert client.get(route, headers={**HEADERS, 'x-actor-id': 'clinic-river-nurse'}).status_code == 403
    err(403, lambda: act('transfer.accept', {'id': r['id']}, clinic='clinic-river', actor='clinic-river-nurse'))
    err(409, lambda: act('transfer.accept', {'id': r['id']}, **TARGET))


def test_consent_is_strict_persistent_and_cannot_expand_pending_request():
    client = TestClient(main.app)
    base, r = request(client)
    body = {'target_clinic': 'clinic-river', 'consent': True, 'include_audio': True}
    assert client.post(base + '/transfers', json=body).status_code == 409
    assert client.post(base + '/transfers', json={**body, 'include_audio': 'true'}).status_code == 422
    assert client.get(base + '/transfers').json()[0]['scope'] == {'audio': False, 'medications': False}
    client.delete(base + '/transfers/' + r['id'])
    next_request = client.post(base + '/transfers', json=body).json()
    assert next_request['id'] != r['id'] and next_request['scope']['audio']


@pytest.mark.parametrize('fault', ['gap', 'hash', 'size', 'unfinished', 'limit'])
def test_invalid_audio_or_files_never_create_patient(fault, monkeypatch):
    client = TestClient(main.app)
    f, audio, _ = media(client)
    _, r = request(client, include_audio=True)
    with db.connection(True) as c:
        if fault == 'gap':
            c.execute('DELETE FROM chunks WHERE recording_id=? AND chunk_index=0', (audio['id'],))
        elif fault == 'hash':
            row = c.execute('SELECT path FROM chunks WHERE recording_id=? LIMIT 1', (audio['id'],)).fetchone()
            Path(row[0]).write_bytes(b'tampered audio')
        elif fault == 'size':
            file = db.get(c, f['id'])
            db.update(c, file, {**file['data'], 'size': 123456})
        elif fault == 'unfinished':
            a = db.get(c, audio['id'])
            db.update(c, a, {**a['data'], 'status': 'recording'})
        else:
            monkeypatch.setattr(transfers, 'MAX_BYTES', 10)
    response = client.get('/api/transfers/' + r['id'] + '/preview', headers=HEADERS)
    assert response.status_code == (422 if fault == 'limit' else 409)
    with db.connection() as c:
        assert not db.all_records(c, 'clinic-river', 'patient')


def test_failed_transaction_removes_only_new_binary_copies(monkeypatch):
    client = TestClient(main.app)
    media(client)
    _, r = request(client, include_audio=True)
    plan = preview(client, r)
    existing_files = {p for p in db.DATA.rglob('*') if p.is_file()}
    with db.connection(True) as c:
        # Failure after dispatch has written copies, during the shared action audit.
        c.execute("CREATE TRIGGER transfer_failure BEFORE INSERT ON audit WHEN NEW.action='transfer.accept' BEGIN SELECT RAISE(ABORT, 'injected commit-boundary failure'); END")
    with pytest.raises(Exception, match='injected commit-boundary failure'):
        act('transfer.accept', {'id': r['id'], 'expected_digest': plan['digest']}, **TARGET)
    assert {p for p in db.DATA.rglob('*') if p.is_file()} == existing_files
    with db.connection() as c:
        assert not db.all_records(c, 'clinic-river', 'patient')
        assert not c.execute('SELECT * FROM transfer_revisions').fetchall()
        assert c.execute('SELECT status FROM transfer_requests WHERE id=?', (r['id'],)).fetchone()[0] == 'pending'


def test_legacy_request_scope_migration_and_untracked_copies_blocked():
    client = TestClient(main.app)
    _, r = request(client)
    with db.connection(True) as c:
        owner = db.record(c, 'owner', 'clinic-river', {'name': 'Earlier owner'})
        patient = db.record(c, 'patient', 'clinic-river', {'name': 'Earlier copied patient', 'species': 'Cat', 'owner_id': owner['id']})
        c.execute('INSERT INTO transferred_patients VALUES(?,?,?,?)', ('clinic-east', 'luna', 'clinic-river', patient['id']))
    response = client.get('/api/transfers/' + r['id'] + '/preview', headers=HEADERS)
    assert response.status_code == 409 and 'origin mapping' in response.text
    with db.connection(True) as c:
        c.execute('ALTER TABLE transfer_requests DROP COLUMN scope')
        transfers.setup(c)
        assert json_scope(c, r) == {'medications': False, 'audio': False}


def json_scope(c, r):
    import json
    return json.loads(c.execute('SELECT scope FROM transfer_requests WHERE id=?', (r['id'],)).fetchone()[0])


def test_typed_observations_preserve_values_ranges_and_origin(monkeypatch):
    client = TestClient(main.app)
    native = {'id': 'native-event', 'kind': 'event', 'clinic_id': 'clinic-east', 'version': 1, 'created_at': db.now(), 'updated_at': db.now(),
              'data': {'patient_id': 'luna', 'title': 'Approved native laboratory result', 'category': 'bloods', 'body': 'Source supplied facts',
                       'occurred_at': db.now(), 'approved': True, 'observations': [
                           {'concept': 'confirmed', 'name': 'Confirmed', 'value': False, 'value_type': 'boolean', 'unit': '', 'ref_low': None, 'ref_high': None},
                           {'concept': 'potassium', 'name': 'Potassium', 'value': 6.2, 'value_type': 'number', 'unit': 'mmol/L', 'ref_low': 3.5, 'ref_high': 5.5}]}}
    monkeypatch.setattr('spine.reader.native_records', lambda clinic, *a: [native] if clinic == 'clinic-east' else [])
    _, r = request(client)
    out = accept(client, r)
    with db.connection() as c:
        facts = db.all_records(c, 'clinic-river', 'observation')
        assert len(facts) == 2
        flag = next(x for x in facts if x['data']['code'] == 'confirmed')
        number = next(x for x in facts if x['data']['code'] == 'potassium')
        assert flag['data']['value'] is False and flag['data']['value_type'] == 'boolean'
        assert number['data']['low'] == 3.5 and number['data']['high'] == 5.5
        assert all(x['data']['patient_id'] == out['id'] and x['data']['origin_id'] == 'native-event' for x in facts)
    _, again = request(client)
    assert accept(client, again)['transferred_events'] == 0


def test_binary_tampering_after_preview_cannot_import():
    client = TestClient(main.app)
    f, _, _ = media(client)
    _, r = request(client, include_audio=True)
    review = preview(client, r)
    Path(get(f['id'])['data']['path']).write_bytes(b'changed after review')
    err(409, lambda: act('transfer.accept', {'id': r['id'], 'expected_digest': review['digest']}, **TARGET))
    with db.connection() as c:
        assert not db.all_records(c, 'clinic-river', 'patient')


def test_source_reversion_requires_review_and_retains_chronology():
    client = TestClient(main.app)
    _, first = request(client)
    origin = next(x for x in preview(client, first)['items'] if x['kind'] == 'event')
    original = get(origin['origin_id'])
    accept(client, first)
    with db.connection(True) as c:
        db.update(c, original, {**original['data'], 'body': 'Corrected source'})
    _, second = request(client)
    accept(client, second, review_changes=True)
    with db.connection(True) as c:
        changed = db.get(c, original['id'])
        db.update(c, changed, original['data'])
    _, third = request(client)
    review = preview(client, third)
    reverted = next(x for x in review['items'] if x['kind'] == 'event')
    assert reverted['state'] == 'changed' and reverted['revision'] == 3
    assert reverted['previous']['body'] == 'Corrected source'
    err(409, lambda: act('transfer.accept', {'id': third['id'], 'expected_digest': review['digest']}, **TARGET))
    accept(client, third, review_changes=True)
    with db.connection() as c:
        copies = [x for x in db.all_records(c, 'clinic-river', 'event') if x['data'].get('origin_id') == original['id']]
        assert len(copies) == 3 and {x['data']['origin_revision'] for x in copies} == {1, 2, 3}
    _, fourth = request(client)
    assert accept(client, fourth)['counts']['changed'] == 0
