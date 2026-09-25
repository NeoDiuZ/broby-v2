#!/usr/bin/env python3
"""V2-only hosted assistant closure of a synthetic owner conversation.

No customer message, provider dispatch, payment, or real patient data is used.
Keep the credentials and state files outside Git. Run setup, review, readback.
"""
import argparse
import json
import uuid
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--credentials', required=True, type=Path)
parser.add_argument('--state', required=True, type=Path)
parser.add_argument('--phase', required=True, choices=('setup', 'review', 'readback'))
args = parser.parse_args()
state = json.loads(args.state.read_text()) if args.state.exists() else {}


def save():
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, indent=2))
    args.state.chmod(0o600)


def check(value, label):
    assert value, label
    print('PASS ' + label, flush=True)


base = args.base_url.rstrip('/')
with httpx.Client(base_url=base + '/api/', headers={'Origin': base, 'x-clinic-id': 'clinic-east'}, timeout=210) as client:
    def req(method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, (method, path.split('/')[0], response.status_code)
        return response.json()

    def act(action, payload):
        return req('POST', 'actions', json={'action': action, 'payload': payload, 'key': str(uuid.uuid4())})

    def rows():
        return {row['id']: row for row in req('GET', 'bootstrap')['records']}

    credentials = json.loads(args.credentials.read_text())
    req('POST', 'login', json={key: credentials[key] for key in ('username', 'password')})
    try:
        if args.phase == 'setup':
            assert not state, 'State already exists; do not duplicate the synthetic fixture.'
            state['tag'] = uuid.uuid4().hex[:8]
            patient = act('patient.create', {'name': 'SYNTHETIC Assistant Conversation ' + state['tag'],
                'species': 'Cat', 'owner_name': 'SYNTHETIC Conversation Owner ' + state['tag']})
            state['patient'] = patient['id']; save()
            grant = act('share.create', {'patient_id': patient['id']})
            state['grant'] = grant['id']; save()
            response = req('POST', 'owner/' + state['grant'] + '/conversations', json={
                'message': 'SYNTHETIC owner question ' + state['tag'] + ': please have staff review this.',
                'request_staff': True, 'urgent': True, 'key': 'assistant-conversation-' + state['tag']})
            state['thread'] = response['id']; state['phase'] = 'setup'; save()
            check(response['status'] == 'needs_attention' and response['urgent'], 'synthetic urgent owner question awaits staff')
            check(len(response['turns']) == 1, 'one exact owner turn persisted')
        elif args.phase == 'review':
            assert state.get('phase') == 'setup', 'Setup must complete before review.'
            thread = req('GET', 'owner-conversations/' + state['thread'])
            check(thread['data']['status'] == 'needs_attention', 'current owner conversation remains open')
            reason = 'SYNTHETIC staff follow-up completed ' + state['tag']
            message = f"Close conversation {state['thread']} reason: {reason}"
            before = rows()[state['thread']]
            turn = req('POST', 'assistant', json={'message': message, 'patient_id': state['patient'],
                'key': 'assistant-conversation-close-' + state['tag']})
            state['turn'] = turn; save()
            check(turn.get('action', {}).get('action') == 'conversation.close', 'real model proposes the exact reviewed closure')
            check(turn['action']['payload']['reason'] == reason, 'reason is copied exactly from the operator request')
            human = next(field['value'] for field in turn['review']['fields'] if field['label'] == 'Exact human conversation')
            check(thread['turns'][0]['data']['message'] in human, 'review displays the exact owner message')
            check(rows()[state['thread']] == before, 'review causes no conversation mutation')
            result = req('POST', f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm")
            state['result'] = result; save()
            check(result['data']['status'] == 'closed', 'confirmation closes the exact synthetic conversation')
            replay = req('POST', f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm")
            check(replay == result, 'confirmation replay returns the same receipt')
            act('share.revoke', {'token': state['grant']})
            state['phase'] = 'complete'; save()
        else:
            assert state.get('phase') == 'complete', 'Review must finish before readback.'
            thread = req('GET', 'owner-conversations/' + state['thread'])
            check(thread['data']['status'] == 'closed' and len(thread['turns']) == 1, 'closed conversation survives a new login')
            saved = req('GET', 'assistant/conversations/' + state['turn']['conversation_id'])['turns'][0]
            check(saved['review'] == state['turn']['review'] and saved['execution'] == state['result'],
                  'exact assistant review and execution survive readback')
            alert = rows().get('conversation-escalation:' + state['thread'])
            check(alert and alert['data']['status'] == 'acknowledged' and alert['data']['delivery'] == 'disabled',
                  'internal urgent alert is acknowledged without external delivery')
            req('GET', 'owner/' + state['grant'] + '/conversations/' + state['thread'], 404)
            check(True, 'revoked synthetic owner link cannot reopen conversation')
            check(not req('GET', 'integrations/twilio/status')['sending_enabled'], 'customer messaging remains disabled')
    finally:
        client.post('logout')
