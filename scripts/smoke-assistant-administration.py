#!/usr/bin/env python3
"""Synthetic V2 administration: setup -> review -> browser confirm -> readback.

First run api/scripts/provision-assistant-administration.py in the identity-
verified V2 service and copy its private state file locally. All mutations below
are scoped to those new clinics, their new staff member and their own new org.
Browser confirmations only tighten synthetic member access and withdraw a new
synthetic adoption request. No existing staff access or organization is changed.
"""
import argparse
import json
import os
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--credentials', required=True, type=Path)
parser.add_argument('--state', required=True, type=Path)
parser.add_argument('--phase', required=True, choices=('setup', 'review', 'readback'))
args = parser.parse_args()
base = args.base_url.rstrip('/')
state = json.loads(args.state.read_text())
assert state['base'] == base and state['project_id'] == 'ca389ebd-0186-4b7e-baec-8ddacdfc406b' and state['fixture_type'] == 'assistant-administration'
credentials = json.loads(args.credentials.read_text())
assert credentials['username'] == state['account'], 'The fixture belongs to another acceptance account.'


def save():
    fd = os.open(args.state, os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output: json.dump(state, output, indent=2)
    args.state.chmod(0o600)


def check(ok, label):
    assert ok, label
    print('PASS ' + label, flush=True)


with httpx.Client(base_url=base + '/api/', headers={'Origin': base}, timeout=210) as client:
    def req(method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, (method, path.split('/')[0], response.status_code)
        return response.json()

    def select(purpose):
        fixture = state['clinics'][purpose]
        assert fixture['id'].startswith('synthetic-assistant-admin-' + state['tag'] + '-')
        client.headers.update({'x-clinic-id': fixture['id'], 'x-actor-id': fixture['member_id']})
        snapshot = req('GET', 'bootstrap')
        practice = snapshot['clinic']
        check(practice['id'] == fixture['id'] and practice['data'].get('synthetic_acceptance') == 'assistant-administration'
              and practice['data'].get('synthetic_tag') == state['tag'] and snapshot['actor']['id'] == fixture['member_id'],
              purpose + ': exact disposable synthetic clinic and administrator verified')
        current = {(row['id'], row['member_id']) for row in snapshot['clinics']}
        check(all((row['clinic_id'], row['member_id']) in current for row in state['existing_active_memberships']), 'pre-existing active acceptance-account memberships remain available')
        return {row['id']: row for row in snapshot['records']}

    def act(case, name, payload):
        return req('POST', 'actions', json={'action': name, 'payload': payload, 'key': 'assistant-admin-' + state['tag'] + '-' + case})

    def ask(case, command, action):
        turn = req('POST', 'assistant', json={'message': command, 'key': 'assistant-admin-' + state['tag'] + '-' + case})
        state.setdefault('turns', {})[case] = turn; save()
        check(turn.get('action', {}).get('action') == action and bool(turn.get('review')), case + ': model proposes the expected reviewed operation')
        return turn

    def confirm(turn, expected=200):
        return req('POST', f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm", expected)

    req('POST', 'login', json={key: credentials[key] for key in ('username', 'password')})
    try:
        if args.phase == 'setup':
            assert state['phase'] in ('provisioned', 'setup_started'), 'Setup already completed.'
            state['phase'] = 'setup_started'; save()
            select('access')
            if not state.get('organization'):
                org = act('create-organization', 'organization.create', {'name': 'SYNTHETIC Assistant Administration ' + state['tag']})
                state['organization'] = org['id']; save()
            organization = req('GET', 'organization')
            check(organization['id'] == state['organization'] and organization['master']
                  and {row['id'] for row in organization['clinics']} == {state['clinics']['access']['id']}, 'new organization contains only the new synthetic access clinic')
            if not state.get('member'):
                member = act('create-member', 'member.save', {'name': 'SYNTHETIC Restricted Staff ' + state['tag'], 'role': 'nurse', 'active': True})
                state['member'] = member['id']; save()
            select('withdrawal')
            check(req('GET', 'organization') is None, 'new withdrawal clinic remains independent')
            if not state.get('request'):
                preview = req('POST', 'organization/join-preview', json={'organization_id': state['organization']})
                request = act('create-request', 'organization.join_request', {'organization_id': state['organization'],
                    'digest': preview['digest'], 'accept_access': True, 'reason': 'SYNTHETIC acceptance request only ' + state['tag']})
                state['request'] = request['id']; state['original_request'] = request; save()
            state['phase'] = 'setup'; save()
        elif args.phase == 'review':
            assert state['phase'] in ('setup', 'review_started'), 'Complete setup before review; do not repeat completed review.'
            state['phase'] = 'review_started'; save()
            before = select('access'); member = before[state['member']]
            check(member['data']['name'] == 'SYNTHETIC Restricted Staff ' + state['tag'] and not member['data'].get('read_restrictions'), 'only the newly created unrestricted synthetic staff member is targeted')
            command = f"Set member {member['id']} read restrictions: read.billing reason: SYNTHETIC reviewed restriction {state['tag']}"
            if not state.get('stale_policy_verified'):
                stale = ask('stale-access', 'Please ' + command, 'access.member')
                # This organization contains only the fresh fixture clinic. A
                # lost policy response safely replays its deterministic key.
                organization = req('GET', 'organization')
                check(organization['id'] == state['organization'] and organization['locked_actions'] in ([], ['read.inventory'])
                      and {row['id'] for row in organization['clinics']} == {state['clinics']['access']['id']}, 'policy-change test is confined to the new synthetic organization')
                act('tighten-synthetic-policy', 'organization.policy', {'actions': ['read.inventory']})
                rejected = confirm(stale, 409)
                check('access changed' in rejected.get('detail', '').lower(), 'stale organization-policy digest is explicitly rejected')
                after = select('access')
                check(after[state['member']] == member, 'stale confirmation leaves synthetic member unchanged')
                state['stale_policy_verified'] = True; save()
            fresh = ask('tighten-access', command, 'access.member')
            check(fresh['action']['payload']['restrictions'] == ['read.billing'] and fresh['action']['payload']['id'] == state['member'], 'fresh review binds exact member and tightening-only restriction list')
            fields = {field['label']: field['value'] for field in fresh['review']['fields']}
            check('read.inventory' in fields['Inherited read restrictions retained'] and fields['New complete member restrictions'].startswith('read.billing'), 'review retains the new inherited restriction and shows the additional member restriction')
            check('Billing: Blocked' in fields['Views after confirmation with required dependencies'], 'review shows the actual resulting blocked billing view')
            check(select('access')[state['member']] == member, 'fresh access review has not yet changed the synthetic member')
            before = select('withdrawal'); request = before[state['request']]
            check(request == state['original_request'] and request['data']['status'] == 'pending', 'only the new synthetic pending adoption request is targeted')
            withdrawal = ask('withdraw-request', f"Withdraw organization request {request['id']} reason: SYNTHETIC withdrawal after review {state['tag']}", 'organization.join_cancel')
            fields = {field['label']: field['value'] for field in withdrawal['review']['fields']}
            check(state['organization'] in fields['Requested organization'] and fields['Original proposed access'] == request['data']['consent']['access'], 'withdrawal review preserves exact original organization and access consent')
            check(select('withdrawal')[state['request']] == request and req('GET', 'organization') is None, 'withdrawal review changes no request or organization membership')
            state['phase'] = 'reviewed'; save()
            print('In the browser, choose each new SYNTHETIC clinic and confirm only tighten-access and withdraw-request. Leave stale-access unconfirmed.', flush=True)
        else:
            assert state['phase'] == 'reviewed', 'Review and browser-confirm both new synthetic proposals first.'
            for case, purpose in (('tighten-access', 'access'), ('withdraw-request', 'withdrawal')):
                select(purpose); turn = state['turns'][case]
                saved = req('GET', 'assistant/conversations/' + turn['conversation_id'])['turns'][0]
                check(saved['review'] == turn['review'] and saved.get('execution'), case + ': exact review and confirmation persist in a new login')
                check(confirm(turn) == saved['execution'], case + ': confirmation replay returns the original receipt')
                state.setdefault('results', {})[case] = saved['execution']; save()
            records = select('access'); member = records[state['member']]
            check(member['data']['read_restrictions'] == ['read.billing'] and member['data']['role'] == 'nurse' and member['data']['active'], 'only the displayed read restriction was applied to the new synthetic member')
            check(req('GET', 'organization')['locked_actions'] == ['read.inventory'], 'synthetic inherited restriction remains; no access was widened')
            stale = state['turns']['stale-access']
            check(not req('GET', 'assistant/conversations/' + stale['conversation_id'])['turns'][0].get('execution'), 'stale proposal has no saved successful execution')
            records = select('withdrawal'); request = records[state['request']]
            check(request['data']['status'] == 'withdrawn' and request['data']['consent'] == state['original_request']['data']['consent'], 'withdrawal preserves the exact original consent history')
            check(req('GET', 'organization') is None, 'synthetic withdrawal clinic remains independent; no adoption occurred')
            check(not any(row['kind'] in ('patient', 'owner', 'outbox', 'payment') for row in records.values()), 'withdrawal fixture contains no customer records, messages or money movement')
            state['phase'] = 'complete'; save()
    finally:
        client.post('logout')
