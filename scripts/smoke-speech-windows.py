#!/usr/bin/env python3
"""Opt-in synthetic 25-minute boundary test against a running V2 deployment.

Makes real speech-provider requests unless --verify-only is supplied. The fixture
must contain synthetic speech before and after 25 minutes; never use patient data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--credentials', type=Path)
parser.add_argument('--audio', type=Path)
parser.add_argument('--state', required=True, type=Path)
parser.add_argument('--verify-only', action='store_true')
args = parser.parse_args()
checks = []


def check(ok, label):
    if not ok:
        raise AssertionError(label)
    checks.append(label)
    print('PASS ' + label, flush=True)


with httpx.Client(base_url=args.base_url.rstrip('/') + '/api/', timeout=120,
                  headers={'x-clinic-id': 'clinic-east', 'x-actor-id': 'clinic-east-admin'}) as client:
    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code != 200:
            raise AssertionError(f'{method} {path.split("/")[0]} returned {response.status_code}')
        return response

    def act(action, payload, key=None):
        return request('POST', 'actions', json={'action': action, 'payload': payload,
                       'key': key or str(uuid.uuid4())}).json()

    def save():
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2))
        args.state.chmod(0o600)

    if args.credentials:
        credentials = json.loads(args.credentials.read_text())
        request('POST', 'login', json={k: credentials[k] for k in ('username', 'password')})
    check(request('GET', 'ready').json()['status'] == 'ready', 'deployment ready')
    if args.verify_only:
        state = json.loads(args.state.read_text())
    else:
        if not args.audio:
            parser.error('--audio is required for a new synthetic test')
        original = args.audio.read_bytes()
        patient = act('patient.create', {'name': 'SYNTHETIC Speech Windows ' + uuid.uuid4().hex[:8],
                       'species': 'Dog', 'owner_name': 'Synthetic Speech Test Owner'})
        consult = act('consultation.create', {'patient_id': patient['id'], 'title': 'Synthetic 25-minute speech acceptance'})
        recording = act('recording.create', {'patient_id': patient['id'], 'consultation_id': consult['id'],
                         'device': 'synthetic-fixture', 'mime': 'audio/flac'})
        state = {'patient': patient['id'], 'consultation': consult['id'], 'recording': recording['id'],
                 'audio_sha256': hashlib.sha256(original).hexdigest()}
        save()
        pieces = [original[i:i+5*1024*1024] for i in range(0, len(original), 5*1024*1024)]
        for index, piece in enumerate(pieces):
            request('PUT', f'recordings/{recording["id"]}/chunks/{index}', content=piece)
        act('recording.complete', {'id': recording['id'], 'expected_chunks': len(pieces), 'duration': 0})
        job = act('recording.transcribe', {'id': recording['id'], 'language': 'en', 'diarize': True})
        state['job'] = job['id']
        save()
        last = None
        for _ in range(180):
            job = request('GET', 'jobs/' + state['job']).json()
            progress = (job['status'], (job.get('result') or {}).get('completed_windows', 0))
            if progress != last:
                print('Speech job: ' + str(progress), flush=True)
                last = progress
            if job['status'] in ('completed', 'failed', 'conflict'):
                break
            time.sleep(5)
        check(job['status'] == 'completed', 'real speech-provider job completed')
        state['source'] = job['result']['source_id']
        save()
    records = {r['id']: r for r in request('GET', 'bootstrap').json()['records']}
    source = records[state['source']]['data']
    windows = source['refinement_windows']
    check(len(windows) == 2 and windows[0]['end'] == 1500 and windows[1]['start'] == 1500,
          'exact 25-minute window boundary persisted')
    check('blue marker' in source['text'].lower() and 'green marker' in source['text'].lower(),
          'both synthetic spoken markers returned by the live provider')
    check(any(u['start'] >= 1500 for u in source['utterances']), 'second-window timestamps point into the original audio')
    check({u['window_index'] for u in source['utterances']} == {0, 1}, 'both windows have original-audio receipts')
    check(records[state['consultation']]['data']['source_ids'].count(state['source']) == 1,
          'one transcript source attached to the consultation')
    audio = request('GET', 'recordings/' + state['recording'] + '/audio').content
    check(hashlib.sha256(audio).hexdigest() == state['audio_sha256'], 'original audio preserved byte for byte')
    check(request('GET', 'operations/status').json()['sending_enabled'] is False, 'messaging remains disabled')
    print(f'{len(checks)} speech acceptance checks passed', flush=True)
