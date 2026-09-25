"""Exercise all smoke-script phases against authenticated APIs, with fake intent."""
import contextlib
import json
import runpy
from pathlib import Path

import httpx
import pytest

import assistant
from test_hosted import hosted


def test_smoke_phases_wait_for_ui_confirmation_and_cleanup(hosted, monkeypatch, tmp_path):
    monkeypatch.setattr('spine.reader.observation_fields', lambda *a: [])
    monkeypatch.setattr('spine.reader.clinical_archive', lambda *a, **k: {})
    credentials = tmp_path / 'credentials.json'
    credentials.write_text(json.dumps({'username': 'admin', 'password': 'synthetic-test-password'}))
    state = tmp_path / 'state.json'
    script = Path(__file__).resolve().parents[2] / 'scripts/smoke-assistant-guided-completion.py'
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})

    def intent(_, data):
        if data.get('question'): return {'topic': 'staff'}
        message = data['request']
        recall = assistant.explicit_recall_prepare(message)
        if recall: return {'action': {'action': 'recall.prepare', 'payload': recall}}
        alert = assistant.explicit_escalation_acknowledge(message)
        assert alert
        return {'action': {'action': 'escalation.acknowledge', 'payload': {**alert, 'version': 1}}}

    monkeypatch.setattr(assistant.providers, 'model_json', intent)

    def local_client(**kwargs):
        hosted.base_url = kwargs['base_url']
        hosted.headers.update(kwargs['headers'])
        return contextlib.nullcontext(hosted)

    monkeypatch.setattr(httpx, 'Client', local_client)

    def run(phase):
        monkeypatch.setattr('sys.argv', [str(script), 'https://broby.example.test', '--credentials', str(credentials),
            '--state', str(state), '--clinic', 'clinic-east', '--actor', 'clinic-east-admin', '--phase', phase])
        runpy.run_path(str(script), run_name='__main__')

    run('setup'); run('review')
    reviewed = json.loads(state.read_text())
    assert reviewed['phase'] == 'reviewed'
    with pytest.raises(AssertionError, match='reviewed browser confirmation is persisted'): run('readback')
    hosted.post('login', json=json.loads(credentials.read_text()))
    for turn in reviewed['turns'].values():
        response = hosted.post(f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm")
        assert response.status_code == 200, response.text
    run('readback')
    assert json.loads(state.read_text())['phase'] == 'complete'
