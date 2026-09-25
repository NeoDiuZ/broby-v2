#!/usr/bin/env python3
"""Opt-in V2 synthetic recall/alert review, browser confirmation, saved readback.

Run setup then review; confirm BOTH saved proposals in the V2 browser. Run
readback after confirmation to verify saved results, replay and cleanup. This
script never sends customer messages or acknowledges a real person's alert.
Credentials/state contain private capabilities and must remain outside Git.
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
parser.add_argument('--clinic', required=True)
parser.add_argument('--actor', required=True)
parser.add_argument('--phase', required=True, choices=('setup', 'review', 'readback'))
args = parser.parse_args()
base = args.base_url.rstrip('/')
state = json.loads(args.state.read_text()) if args.state.exists() else {}


def save():
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, indent=2))
    args.state.chmod(0o600)


def check(ok, label):
    assert ok, label
    print('PASS ' + label, flush=True)


with httpx.Client(base_url=base + '/api/', headers={'Origin': base}, timeout=210) as client:
    def req(method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, (method, path.split('/')[0], response.status_code)
        return response.json()

    def act(name, payload):
        return req('POST', 'actions', json={'action': name, 'payload': payload, 'key': str(uuid.uuid4())})

    def rows():
        return {row['id']: row for row in req('GET', 'bootstrap')['records']}

    def ask(case, command, operation):
        turn = req('POST', 'assistant', json={'message': command, 'patient_id': state['patient'],
            'key': 'assistant-guided-' + state['tag'] + '-' + case})
        state.setdefault('turns', {})[case] = turn; save()
        check(turn.get('action', {}).get('action') == operation and turn.get('review'), case + ': real model proposes the expected reviewed action')
        return turn

    credentials = json.loads(args.credentials.read_text())
    req('POST', 'login', json={key: credentials[key] for key in ('username', 'password')})
    client.headers.update({'x-clinic-id': args.clinic, 'x-actor-id': args.actor})
    try:
        if args.phase == 'setup':
            assert not state, 'Existing fixture state; do not duplicate setup.'
            state.update(base=base, clinic=args.clinic, actor=args.actor, tag=uuid.uuid4().hex[:8])
            patient = act('patient.create', {'name': 'SYNTHETIC Reviewed Batch ' + state['tag'], 'species': 'Cat',
                'owner_name': 'SYNTHETIC Batch Owner ' + state['tag'], 'owner_email': 'synthetic-' + state['tag'] + '@example.invalid'})
            state['patient'] = patient['id']; state['owner'] = patient['data']['owner_id']; save()
            state['reminders'] = []; save()
            for index in range(2):
                reminder = act('reminder.create', {'patient_id': patient['id'],
                    'title': 'SYNTHETIC reviewed reminder ' + state['tag'] + '-' + str(index), 'due': '2098-10-21'})
                state['reminders'].append(reminder['id']); save()
            grant = act('share.create', {'patient_id': patient['id']})
            state['grant'] = grant['id']; save()
            question = 'SYNTHETIC internal alert ' + state['tag'] + ': staff review requested.'
            thread = req('POST', 'owner/' + grant['id'] + '/conversations', json={
                'message': question, 'urgent': True, 'request_staff': True, 'key': 'assistant-guided-' + state['tag']})
            state['thread'] = thread['id']; state['alert'] = 'conversation-escalation:' + thread['id']; state['owner_message'] = question
            state['phase'] = 'setup'; save()
            check(rows()[state['alert']]['data']['delivery'] == 'disabled', 'synthetic internal alert exists with external notification disabled')
        else:
            assert (state['base'], state['clinic'], state['actor']) == (base, args.clinic, args.actor), 'State belongs to another target.'
            if args.phase == 'review':
                assert state.get('phase') == 'setup', 'Run review once after setup.'
                before = rows()
                title = 'SYNTHETIC assistant batch ' + state['tag']
                command = f"Prepare recall campaign {title} from 2098-10-21 to 2098-10-21 reminders: {', '.join(state['reminders'])}"
                recall = ask('recall', command, 'recall.prepare')
                check(recall['action']['payload']['reminder_ids'] == state['reminders'], 'exact operator recipient selection is retained')
                check(recall['action']['payload']['title'] == title, 'exact campaign title is retained')
                fields = {field['label']: field['value'] for field in recall['review']['fields']}
                for index, rid in enumerate(state['reminders'], 1):
                    r = before[rid]
                    expected = f"Reminder for {before[state['patient']]['data']['name']}: {r['data']['title']}, due {r['data']['due']}. Please contact your clinic to arrange this."
                    check(fields[f'Exact draft {index}'] == expected, f'recall {index}: deterministic review displays exact draft')
                    check(state['owner'] in fields[f'Recipient {index}'], f'recall {index}: review identifies exact primary owner')
                alert = ask('alert', 'Acknowledge escalation ' + state['alert'], 'escalation.acknowledge')
                human = next(field['value'] for field in alert['review']['fields'] if field['label'] == 'Exact human conversation')
                check(state['owner_message'] in human, 'alert review displays exact owner source text')
                after = rows()
                check(all(after[id] == before[id] for id in [*state['reminders'], state['alert'], state['thread']]), 'both reviews leave underlying records unchanged')
                state['phase'] = 'reviewed'; save()
                print('Confirm both saved proposals in the V2 browser, then run readback.', flush=True)
            else:
                assert state.get('phase') == 'reviewed', 'Run review, then confirm both proposals in the browser first.'
                results = {}
                for case, turn in state['turns'].items():
                    saved = req('GET', 'assistant/conversations/' + turn['conversation_id'])['turns'][0]
                    check(saved['review'] == turn['review'] and saved.get('execution'), case + ': reviewed browser confirmation is persisted')
                    results[case] = saved['execution']
                    replay = req('POST', f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm")
                    check(replay == saved['execution'], case + ': replay returns the original receipt')
                records = rows(); campaign = records[results['recall']['id']]
                drafts = [r for r in records.values() if r['kind'] == 'outbox' and r['data'].get('campaign_id') == campaign['id']]
                check(len(drafts) == 2 and all(r['data']['status'] == 'pending' and r['data']['channel'] == 'manual' for r in drafts), 'exactly two pending manual drafts; no provider delivery')
                fields = {field['label']: field['value'] for field in state['turns']['recall']['review']['fields']}
                for index, rid in enumerate(state['reminders'], 1):
                    check(records[records[rid]['data']['outbox_id']]['data']['body'] == fields[f'Exact draft {index}'], f'recall {index}: stored draft equals displayed review')
                check(records[state['alert']]['data']['status'] == 'acknowledged' and records[state['alert']]['data']['delivery'] == 'disabled', 'only the internal alert was acknowledged')
                thread = req('GET', 'owner-conversations/' + state['thread'])
                check(thread['data']['status'] == 'needs_attention' and len(thread['turns']) == 1, 'acknowledgement sends no reply and leaves the owner conversation open')
                state['results'] = results; save()
                act('recall.cancel', {'id': campaign['id'], 'version': campaign['version'], 'reason': 'SYNTHETIC acceptance completed; cancel unsent drafts'})
                current = rows()[state['thread']]
                act('conversation.close', {'id': current['id'], 'version': current['version'], 'last_owner_turn': current['data']['last_owner_turn'], 'reason': 'SYNTHETIC acceptance completed'})
                act('share.revoke', {'token': state['grant']})
                final = rows()
                check(all(final[draft['id']]['data']['status'] == 'cancelled' for draft in drafts), 'synthetic unsent drafts are cancelled after acceptance')
                req('GET', 'owner/' + state['grant'], 404)
                check(True, 'synthetic owner link is revoked')
                state['phase'] = 'complete'; save()
    finally:
        client.post('logout')
