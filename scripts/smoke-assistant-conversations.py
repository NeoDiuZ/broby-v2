#!/usr/bin/env python3
"""V2-only hosted assistant reply and closure of a synthetic owner conversation.

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
            reply = 'SYNTHETIC staff portal reply ' + state['tag'] + ': we received your question.'
            reply_command = f"Reply to conversation {state['thread']} message: {reply}"
            before = rows()[state['thread']]
            reply_turn = req('POST', 'assistant', json={'message': reply_command, 'patient_id': state['patient'],
                'key': 'assistant-conversation-reply-' + state['tag']})
            state['reply_turn'] = reply_turn; save()
            check(reply_turn.get('action', {}).get('action') == 'conversation.reply', 'real model proposes the reviewed portal reply')
            check(reply_turn['action']['payload']['message'] == reply, 'model copies the operator reply exactly')
            check(rows()[state['thread']] == before, 'reply review leaves the owner thread unchanged')
            reply_result = req('POST', f"assistant/conversations/{reply_turn['conversation_id']}/turns/{reply_turn['turn_id']}/confirm")
            state['reply_result'] = reply_result; save()
            check(reply_result['data']['status'] == 'needs_attention', 'reply leaves the urgent staff queue open')
            owner_view = req('GET', 'owner/' + state['grant'] + '/conversations/' + state['thread'])
            check(len(owner_view['turns']) == 2 and owner_view['turns'][-1]['speaker'] == 'clinic'
                  and owner_view['turns'][-1]['message'] == reply, 'exact staff reply is visible through the owner portal link')
            reply_replay = req('POST', f"assistant/conversations/{reply_turn['conversation_id']}/turns/{reply_turn['turn_id']}/confirm")
            check(reply_replay == reply_result and len(req('GET', 'owner-conversations/' + state['thread'])['turns']) == 2,
                  'reply confirmation replay does not duplicate the portal message')
            alert = rows().get('conversation-escalation:' + state['thread'])
            check(alert and alert['data']['status'] == 'needs_attention', 'reply does not silently acknowledge the urgent alert')
            thread = req('GET', 'owner-conversations/' + state['thread'])
            reason = 'SYNTHETIC staff follow-up completed ' + state['tag']
            message = f"Close conversation {state['thread']} reason: {reason}"
            before = rows()[state['thread']]
            turn = req('POST', 'assistant', json={'message': message, 'patient_id': state['patient'],
                'key': 'assistant-conversation-close-' + state['tag']})
            state['turn'] = turn; save()
            check(turn.get('action', {}).get('action') == 'conversation.close', 'real model proposes the exact reviewed closure')
            check(turn['action']['payload']['reason'] == reason, 'reason is copied exactly from the operator request')
            human = next(field['value'] for field in turn['review']['fields'] if field['label'] == 'Exact human conversation')
            check(all(turn['data']['message'] in human for turn in thread['turns']), 'closure review displays both exact human messages')
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
            expected = 2 if state.get('reply_turn') else 1
            check(thread['data']['status'] == 'closed' and len(thread['turns']) == expected, 'closed conversation survives a new login')
            saved = req('GET', 'assistant/conversations/' + state['turn']['conversation_id'])['turns'][0]
            check(saved['review'] == state['turn']['review'] and saved['execution'] == state['result'],
                  'exact assistant review and execution survive readback')
            if state.get('reply_turn'):
                reply_saved = req('GET', 'assistant/conversations/' + state['reply_turn']['conversation_id'])['turns'][0]
                check(reply_saved['review'] == state['reply_turn']['review'] and reply_saved['execution'] == state['reply_result'],
                      'exact owner-visible reply review and result survive readback')
                timeline = req('GET', 'v2/patients/' + state['patient'] + '/timeline?category=message')['items']
                check({event['id'] for event in timeline} == {'conversation-event:' + turn['id'] for turn in thread['turns']},
                      'owner and clinic messages each have one patient-timeline receipt')
            alert = rows().get('conversation-escalation:' + state['thread'])
            check(alert and alert['data']['status'] == 'acknowledged' and alert['data']['delivery'] == 'disabled',
                  'internal urgent alert is acknowledged without external delivery')
            req('GET', 'owner/' + state['grant'] + '/conversations/' + state['thread'], 404)
            check(True, 'revoked synthetic owner link cannot reopen conversation')
            check(not req('GET', 'integrations/twilio/status')['sending_enabled'], 'customer messaging remains disabled')
    finally:
        client.post('logout')
