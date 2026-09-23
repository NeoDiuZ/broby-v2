#!/usr/bin/env python3
"""Authorized synthetic hosted transfer acceptance; owner/receiver UI steps are separate.

prepare creates a synthetic patient, media, stock, lab event and receiving clinic.
verify checks the first UI-accepted transfer, then requests unchanged and changed
updates; the changed request is left for browser review. final verifies that UI
acceptance, revokes source access, and checks independent copies and PostgreSQL.
All capabilities/credentials remain in the private state file, never stdout.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import struct
import uuid
import wave
import httpx

p = argparse.ArgumentParser()
p.add_argument('base_url')
p.add_argument('--credentials', type=Path, required=True)
p.add_argument('--state', type=Path, required=True)
p.add_argument('--phase', choices=['prepare', 'verify', 'final'], required=True)
a = p.parse_args()
checks = []
state = json.loads(a.state.read_text()) if a.state.exists() else {}


def check(value, label):
    if not value:
        raise AssertionError(label)
    checks.append(label)
    print('PASS ' + label, flush=True)


def save():
    state['checks'] = list(dict.fromkeys(state.get('checks', []) + checks))
    a.state.parent.mkdir(parents=True, exist_ok=True)
    a.state.write_text(json.dumps(state, indent=2))
    a.state.chmod(0o600)


with httpx.Client(base_url=a.base_url.rstrip('/') + '/api/', timeout=120) as c:
    def req(method, route, expected=200, **kwargs):
        response = c.request(method, route, **kwargs)
        if response.status_code != expected:
            # Avoid exposing owner capability paths or credentials in errors.
            raise AssertionError(f'{method} {route.split("/")[0]}: expected {expected}, got {response.status_code}: ' + response.text[:300])
        return response

    def act(name, payload):
        return req('POST', 'actions', json={'action': name, 'payload': payload, 'key': str(uuid.uuid4())}).json()

    def switch(clinic, actor):
        c.headers.update({'x-clinic-id': clinic, 'x-actor-id': actor})

    def records():
        return req('GET', 'bootstrap').json()['records']

    def current(id):
        return next(x for x in records() if x['id'] == id)

    def source():
        switch(state['source_clinic'], state['source_actor'])

    def receiver():
        switch(state['target_clinic'], state['target_actor'])

    def owner_request():
        return req('POST', 'owner/' + state['grant'] + '/transfers', json={'target_clinic': state['target_clinic'], 'consent': True,
                   'include_audio': True, 'include_medications': True}).json()

    def preview(id):
        return req('GET', 'transfers/' + id + '/preview').json()

    creds = json.loads(a.credentials.read_text())
    login = req('POST', 'login', json={k: creds[k] for k in ('username', 'password')}).json()
    if a.phase == 'prepare':
        if state:
            raise AssertionError('Use a fresh state file for prepare; preserve existing evidence')
        state.update(source_clinic=login['clinic'], source_actor=login['actor'])
        source()
        org = req('GET', 'organization').json()
        if not org:
            act('organization.create', {'name': 'Broby New synthetic verification group'})
        target = act('organization.clinic_create', {'name': 'SYNTHETIC Transfer Receiving Clinic', 'timezone': 'Asia/Singapore'})
        state.update(target_clinic=target['id'], target_actor=target['member_id'])
        save()
        patient = act('patient.create', {'name': 'SYNTHETIC Transfer ' + uuid.uuid4().hex[:6], 'species': 'Dog',
                      'owner_name': 'Synthetic Transfer Owner', 'owner_email': 'transfer-owner@example.test'})
        state['patient'] = patient['id']
        state['patient_name'] = patient['data']['name']
        consultation = act('consultation.create', {'patient_id': patient['id'], 'title': 'Synthetic original voice note'})
        state['source_consultation'] = consultation['id']
        f = req('POST', 'uploads', data={'patient_id': patient['id']}, files={'file': ('synthetic-transfer.txt', b'SYNTHETIC approved transfer document', 'text/plain')}).json()
        act('attachment.approve', {'id': f['id'], 'version': f['version'], 'approved': True})
        state['file'] = f['id']
        # Deterministic WAV tone; no physical microphone or private sound is captured.
        import math
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
            wav.writeframes(b''.join(struct.pack('<h', round(1000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(16000)))
        content = output.getvalue()
        audio = act('recording.create', {'patient_id': patient['id'], 'consultation_id': consultation['id'], 'device': 'synthetic-generated-tone', 'mime': 'audio/wav'})
        req('PUT', 'recordings/' + audio['id'] + '/chunks/0', content=content)
        finished = act('recording.complete', {'id': audio['id'], 'expected_chunks': 1, 'duration': 2})
        act('recording.approve', {'id': audio['id'], 'version': finished['version'], 'approved': True})
        state.update(audio=audio['id'], audio_sha256=hashlib.sha256(content).hexdigest())
        stock = act('inventory.create', {'name': 'SYNTHETIC Transfer Medication', 'unit': 'test unit', 'stock': 10, 'price_cents': 0})
        medication = act('medication.dispense', {'patient_id': patient['id'], 'inventory_id': stock['id'], 'version': stock['version'], 'quantity': 1,
                         'dose': 'Synthetic source dose only', 'frequency': 'Synthetic source frequency', 'instructions': 'Test history; not for patient use'})
        state['medication'] = medication['id']
        lab = act('test.lab.receive', {'patient_id': patient['id'], 'dedupe_key': 'synthetic-transfer-' + uuid.uuid4().hex,
                  'occurred_at': datetime.now(timezone.utc).isoformat(), 'summary': 'SYNTHETIC transfer potassium result',
                  'source': {'kind': 'document', 'id': 'synthetic-transfer-lab', 'page': 1, 'text': 'Synthetic potassium 6.2 mmol/L; supplied range 3.5–5.5.'},
                  'observations': [{'concept': 'potassium', 'name': 'Potassium', 'value': 6.2, 'unit': 'mmol/L', 'ref_low': 3.5, 'ref_high': 5.5}]})
        state['lab'] = lab['id']
        act('clinical.approve', {'id': lab['id'], 'approved': True})
        grant = act('share.create', {'patient_id': patient['id']})
        state['grant'] = grant['id']
        receiver()
        act('inventory.create', {'name': 'SYNTHETIC receiving stock sentinel', 'unit': 'test unit', 'stock': 17, 'price_cents': 0})
        state['stock_before'] = [x for x in records() if x['kind'] == 'inventory']
        check(True, 'synthetic source fixtures and receiving clinic prepared; no customer contact')
        save()
    else:
        receiver()
        requests = req('GET', 'owner/' + state['grant'] + '/transfers').json() if not state.get('grant_revoked') else []
        if a.phase == 'verify':
            accepted = next((r for r in requests if r['status'] == 'accepted'), None)
            check(accepted is not None, 'owner request and receiving acceptance completed through browser')
            result = act('transfer.accept', {'id': accepted['id']})
            state['first_result'] = result
            check(result['audio_copied'] == result['files_copied'] == result['medication_histories'] == 1, 'original audio, file and medication history imported')
            state['target_patient'] = result['id']
            rs = records()
            state['target_audio'] = next(x['id'] for x in rs if x['kind'] == 'recording' and x['data']['patient_id'] == result['id'])
            state['target_file'] = next(x['id'] for x in rs if x['kind'] == 'attachment' and x['data']['patient_id'] == result['id'])
            check(hashlib.sha256(req('GET', 'recordings/' + state['target_audio'] + '/audio').content).hexdigest() == state['audio_sha256'], 'copied audio is byte-identical')
            check(req('GET', 'files/' + state['target_file']).content == b'SYNTHETIC approved transfer document', 'copied file is byte-identical')
            check([x for x in rs if x['kind'] == 'inventory'] == state['stock_before'] and not any(x['kind'] == 'medication' for x in rs), 'receiving stock unchanged and no medication dispensed')
            check(all(not x['data'].get('approved') for x in rs if x['kind'] in ('event', 'recording', 'attachment') and x['data'].get('patient_id') == result['id']), 'all receiving copies start private')
            stable = [(x['id'], x['version']) for x in rs]
            repeat = owner_request(); review = preview(repeat['id'])
            check(review['counts']['new'] == review['counts']['changed'] == 0, 'subsequent identical request contains only already-copied origins')
            duplicate = act('transfer.accept', {'id': repeat['id'], 'expected_digest': review['digest']})
            check(duplicate['id'] == result['id'] and [(x['id'], x['version']) for x in records()] == stable, 'repeat creates no duplicate patient, media, facts or stock changes')
            target_patient = current(result['id'])
            edited = act('patient.update', {'id': result['id'], 'version': target_patient['version'], 'name': state['patient_name'] + ' local reviewed'})
            state['local_patient_edit'] = edited['data']['name']
            source()
            original = current(state['patient'])
            act('patient.update', {'id': original['id'], 'version': original['version'], 'age': 'Synthetic updated age'})
            update_request = owner_request();state['update_request'] = update_request['id']
            receiver();review = preview(update_request['id'])
            check(review['counts']['changed'] == 1 and review['destination_patient']['data']['name'] == state['local_patient_edit'], 'changed source identity shown beside preserved receiving identity')
            req('POST', 'actions', expected=409, json={'action': 'transfer.accept', 'payload': {'id': update_request['id'], 'expected_digest': review['digest']}, 'key': str(uuid.uuid4())})
            check(True, 'changed origin cannot import without explicit review acknowledgement')
            save()
        else:
            result = act('transfer.accept', {'id': state['update_request']})
            check(result['counts']['changed'] == 1, 'browser accepted the reviewed changed-source revision')
            check(current(state['target_patient'])['data']['name'] == state['local_patient_edit'], 'receiving patient edit remains unchanged after revised transfer')
            rs = records()
            identities = [x for x in rs if x['kind'] == 'event' and x['data'].get('origin_kind') == 'identity' and x['data'].get('patient_id') == state['target_patient']]
            check(len(identities) == 2 and {x['data']['origin_revision'] for x in identities} == {1, 2}, 'both immutable identity revisions remain available')
            # The read API synchronizes and reads PostgreSQL, not just bootstrap SQLite.
            timeline = req('GET', 'patients/' + state['target_patient'] + '/timeline').json()
            state['timeline_keys'] = list(timeline)
            check('6.2' in json.dumps(timeline) and 'Externally recorded medication history' in json.dumps(timeline), 'PostgreSQL timeline contains typed lab and clearly labelled external medication history')
            if not state.get('grant_revoked'):
                source();act('share.revoke', {'token': state['grant']});state['grant_revoked'] = True;save()
            req('GET', 'owner/' + state['grant'], expected=404)
            receiver()
            check(hashlib.sha256(req('GET', 'recordings/' + state['target_audio'] + '/audio').content).hexdigest() == state['audio_sha256'], 'copied audio still available after source access revocation')
            check(req('GET', 'files/' + state['target_file']).content == b'SYNTHETIC approved transfer document', 'copied file still available after source access revocation')
            check([x for x in records() if x['kind'] == 'inventory'] == state['stock_before'], 'stock sentinel remains unchanged after all updates')
            save()
    check(req('GET', 'ready').json()['status'] == 'ready', 'deployed stores ready')
    save()
print(f'{len(checks)} {a.phase} checks passed', flush=True)
