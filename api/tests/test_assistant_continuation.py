"""Saved selection context and dedicated catalog navigation, without mutations."""
import pytest
from fastapi.testclient import TestClient
import assistant
import db
import main
from test_integrity import isolated


@pytest.mark.parametrize('guided', ['ontology.propose', 'ontology.review'])
def test_saved_ontology_guidance_opens_actual_catalog_without_creating_a_definition(monkeypatch, guided):
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    # Model-provided destinations are ignored; only the fixed server route survives.
    monkeypatch.setattr(assistant.providers, 'model_json', lambda *a: {'guide': guided, 'navigate_section': 'Untrusted section'})
    with db.connection() as c: before = [dict(r) for r in c.execute('SELECT * FROM records ORDER BY id')]
    client = TestClient(main.app)
    headers = {'x-actor-id': 'clinic-east-admin'}
    response = client.post('/api/assistant', headers=headers, json={'message': 'Review dictionary definitions', 'key': 'guide-catalog'}).json()
    assert response['navigate'] == 'Settings' and response['navigate_section'] == 'Observation catalog'
    assert not response.get('action') and not response['sources']
    saved = client.get('/api/assistant/conversations/' + response['conversation_id'], headers=headers).json()['turns'][0]
    assert saved['navigate_section'] == response['navigate_section']
    assert client.post(f"/api/assistant/conversations/{response['conversation_id']}/turns/{response['turn_id']}/confirm", headers=headers).status_code == 409
    with db.connection() as c: assert [dict(r) for r in c.execute('SELECT * FROM records ORDER BY id')] == before


def test_patient_choice_repeats_saved_original_question_and_keeps_filters_and_conversation(monkeypatch):
    with db.connection(True) as c:
        matched = db.record(c, 'invoice', 'clinic-east', {'patient_id': 'bella-cat', 'date': '2098-07-10', 'status': 'issued', 'paid_cents': 0, 'total_cents': 100})
        db.record(c, 'invoice', 'clinic-east', {'patient_id': 'bella-dog', 'date': '2098-07-10', 'status': 'issued', 'paid_cents': 0, 'total_cents': 200})
        db.record(c, 'invoice', 'clinic-east', {'patient_id': 'bella-cat', 'date': '2098-07-11', 'status': 'issued', 'paid_cents': 0, 'total_cents': 300})
    seen = []
    monkeypatch.setattr(assistant.providers, 'available', lambda: {'ai': True})
    def intent(_, data):
        seen.append(data)
        return {'read': {'kind': 'invoice', 'scope': 'patient', 'patient_id': data['patient_id'], 'status': 'issued', 'start': '2098-07-10', 'end': '2098-07-10'}}
    monkeypatch.setattr(assistant.providers, 'model_json', intent)
    client = TestClient(main.app)
    message = 'Show Bella invoices whose status equals issued on 2098-07-10'
    first = client.post('/api/assistant', json={'message': message, 'key': 'ambiguous-patient'}).json()
    assert {r['id'] for r in first['choices']} == {'bella-cat', 'bella-dog'} and not seen
    saved = client.get('/api/assistant/conversations/' + first['conversation_id']).json()['turns'][0]
    second = client.post('/api/assistant', json={'message': saved['message'], 'patient_id': 'bella-cat', 'conversation_id': first['conversation_id'], 'key': 'chosen-patient'}).json()
    assert second['conversation_id'] == first['conversation_id']
    assert seen[0]['request'] == message and seen[0]['patient_id'] == 'bella-cat' and seen[0]['recent_user_requests'] == [message]
    assert second['dashboard']['query'] == {'kind': 'invoice', 'patient_id': 'bella-cat', 'status': 'issued', 'start': '2098-07-10', 'end': '2098-07-10'}
    assert second['dashboard']['source_ids'] == [matched['id']] and not second.get('action')
    restored = client.get('/api/assistant/conversations/' + first['conversation_id']).json()
    assert restored['patient_id'] == 'bella-cat'
    assert [turn['message'] for turn in restored['turns']] == [message, message]
