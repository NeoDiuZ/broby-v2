"""Run real same-origin script stages locally; intent is a fixed test stand-in."""
import contextlib
import json
import re
import runpy
from pathlib import Path

import httpx
import pytest
import assistant
import db
from test_hosted import hosted


@pytest.mark.parametrize('positive_history', [False, True])
def test_linked_read_acceptance_script_setup_evaluation_and_merge_readback(hosted, monkeypatch, tmp_path, positive_history):
    with db.connection(True) as c:
        practice = db.get(c, 'clinic-east'); db.update(c, practice, {**practice['data'], 'name': 'SYNTHETIC Linked Acceptance'})
        if positive_history:
            patient = db.record(c, 'patient', 'clinic-east', {'name': 'SYNTHETIC Prior Transfer', 'species': 'Cat'})
            history = db.record(c, 'medication_history', 'clinic-east', {'patient_id': patient['id'], 'name': 'SYNTHETIC Historical Drug', 'dose': 'Original', 'frequency': 'Original', 'instructions': 'External history only'})
    monkeypatch.setattr('spine.reader.observation_fields', lambda *a: [])
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    def intent(_, data):
        q = data['request']
        if 'dictionary definition review' in q: return {'guide': 'ontology.review'}
        if 'medication name equals' in q:
            name = re.search(r'equals "([^"]+)"', q).group(1)
            return {'read': {'kind': 'medication_history' if 'imported medication history' in q else 'medication', 'name': name, 'patient_id': data['patient_id']}}
        if 'SYNTHETIC Choice ' in q:
            return {'read': {'kind': 'reminder', 'patient_id': data['patient_id'], 'status': 'due', 'start': '2098-10-11', 'end': '2098-10-11'}}
        owner = re.search(r'owner ID (\S+)', q).group(1)
        if 'invoices' in q: return {'read': {'kind': 'invoice', 'owner_id': owner, 'outstanding': True, 'scope': 'clinic'}}
        return {'read': {'kind': 'reminder', 'owner_id': owner, 'status': 'due', 'start': '2098-10-11', 'end': '2098-10-11', 'scope': 'clinic'}}
    monkeypatch.setattr(assistant.providers, 'model_json', intent)
    def local_client(**kwargs):
        hosted.base_url = kwargs['base_url']; hosted.headers.update(kwargs['headers'])
        return contextlib.nullcontext(hosted)
    monkeypatch.setattr(httpx, 'Client', local_client)
    script = Path(__file__).resolve().parents[2] / 'scripts/smoke-assistant-linked-reads.py'
    credentials = tmp_path / 'credentials.json'; credentials.write_text(json.dumps({'username': 'admin', 'password': 'synthetic-test-password'}))
    state = tmp_path / 'state.json'
    for phase in ('setup', 'evaluate', 'readback'):
        args = [str(script), 'https://broby.example.test', '--credentials', str(credentials), '--state', str(state), '--clinic', 'clinic-east', '--actor', 'clinic-east-admin', '--phase', phase]
        if positive_history: args += ['--history-record', history['id']]
        monkeypatch.setattr('sys.argv', args)
        if phase == 'readback':
            with pytest.raises(AssertionError, match='browser patient choice retains'):
                runpy.run_path(str(script), run_name='__main__')
            # Local API stand-in only. Root observes the actual browser choice.
            saved = json.loads(state.read_text())
            hosted.post('login', json=json.loads(credentials.read_text()))
            response = hosted.post('assistant', json={'message': saved['browser']['duplicate_prompt'], 'patient_id': saved['fixtures']['choice-Cat']['id'], 'conversation_id': saved['browser_turns']['choices']['conversation_id'], 'key': 'local-browser-choice-stand-in'})
            assert response.status_code == 200
        runpy.run_path(str(script), run_name='__main__')
    saved = json.loads(state.read_text())
    assert saved['phase'] == 'complete' and state.stat().st_mode & 0o777 == 0o600
    assert len(saved['answers']) == (5 if positive_history else 4)
    assert saved['browser_turns']['choices']['choices'] and saved['browser_turns']['catalog']['navigate_section'] == 'Observation catalog'
    with db.connection() as c:
        assert not c.execute('SELECT 1 FROM assistant_turns WHERE execution IS NOT NULL').fetchone()
        assert not db.all_records(c, 'clinic-east', 'payment') and not db.all_records(c, 'clinic-east', 'outbox')
