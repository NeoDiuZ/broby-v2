#!/usr/bin/env python3
"""API-only synthetic child-clinic access review; no independent adoption fixture.

The operator verifies the V2 project/revision first. Setup creates one fresh
synthetic child clinic under an existing organization the account already owns.
Review tightens only that child's clinic locks and leaves member confirmation
to the browser. Parent clinic, organization policy and existing staff never change.
"""
import argparse
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--credentials', required=True, type=Path)
parser.add_argument('--state', required=True, type=Path)
parser.add_argument('--parent-clinic', required=True)
parser.add_argument('--parent-actor', required=True)
parser.add_argument('--organization', required=True)
parser.add_argument('--confirm-v2-project', required=True)
parser.add_argument('--phase', required=True, choices=('setup', 'review', 'readback'))
args = parser.parse_args()
assert args.confirm_v2_project == 'ca389ebd-0186-4b7e-baec-8ddacdfc406b', 'Verify Broby New identity and revision before running.'
base = args.base_url.rstrip('/')
url = urlsplit(base)
assert url.scheme == 'https' and not url.username and not url.path and not url.query and not url.fragment, 'Use the verified V2 HTTPS origin.'
credentials = json.loads(args.credentials.read_text())
binding = {'base': base, 'parent_clinic': args.parent_clinic, 'parent_actor': args.parent_actor,
           'organization': args.organization, 'account': credentials['username'], 'fixture_type': 'assistant-access-child'}
state = json.loads(args.state.read_text()) if args.state.exists() else {}
if state:
    assert all(state.get(k) == value for k, value in binding.items()), 'State belongs to another target.'
else:
    assert args.phase == 'setup', 'Create the synthetic fixture first.'
    state.update(binding, tag=uuid.uuid4().hex[:12], phase='setup_started')
    args.state.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(args.state, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f: json.dump(state, f, indent=2)


def save():
    with args.state.open('w') as f: json.dump(state, f, indent=2)
    args.state.chmod(0o600)


def check(ok, label):
    assert ok, label
    print('PASS ' + label, flush=True)


with httpx.Client(base_url=base + '/api/', headers={'Origin': base}, timeout=210) as client:
    def req(method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, (method, path.split('/')[0], response.status_code)
        return response.json()

    def act(case, action, payload):
        return req('POST', 'actions', json={'action': action, 'payload': payload, 'key': 'assistant-child-' + state['tag'] + '-' + case})

    def ask(case, command):
        turn = req('POST', 'assistant', json={'message': command, 'key': 'assistant-child-' + state['tag'] + '-' + case})
        state.setdefault('turns', {})[case] = turn; save()
        check(turn.get('action', {}).get('action') == 'access.member' and bool(turn.get('review')), case + ': expected reviewed member-access operation')
        return turn

    def confirm(turn, expected=200):
        return req('POST', f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm", expected)

    def parent():
        client.headers.update({'x-clinic-id': args.parent_clinic, 'x-actor-id': args.parent_actor})
        snapshot = req('GET', 'bootstrap'); org = req('GET', 'organization')
        check(snapshot['clinic']['id'] == args.parent_clinic and snapshot['actor']['id'] == args.parent_actor
              and org and org['id'] == args.organization and org['master'], 'exact parent clinic and existing organization master verified')
        current = {'clinic': snapshot['clinic'], 'policy': org['locked_actions'], 'name': org['name']}
        if 'parent_before' in state:
            check(current == state['parent_before'], 'parent clinic and organization name/policy remain unchanged')
            check(set(state['original_clinics']) <= {row['id'] for row in org['clinics']}, 'all original organization clinics remain attached')
        else:
            state['parent_before'] = current
            state['original_clinics'] = [row['id'] for row in org['clinics']]
            state['original_memberships'] = [{k: row[k] for k in ('id', 'member_id')} for row in snapshot['clinics']]
            save()
        return snapshot

    def child():
        assert state['child']['id'] not in state['original_clinics'], 'Only the newly created child can be targeted.'
        client.headers.update({'x-clinic-id': state['child']['id'], 'x-actor-id': state['child']['member_id']})
        snapshot = req('GET', 'bootstrap'); org = req('GET', 'organization')
        check(snapshot['clinic']['id'] == state['child']['id'] and snapshot['clinic']['data']['name'] == state['child_name']
              and snapshot['actor']['id'] == state['child']['member_id'], 'exact fresh synthetic child clinic verified')
        check(org['id'] == args.organization and org['locked_actions'] == state['parent_before']['policy'], 'inherited organization policy remains unchanged')
        check(all(row in [{k: r[k] for k in ('id', 'member_id')} for r in snapshot['clinics']] for row in state['original_memberships']), 'original account memberships remain available')
        check(all(row['kind'] in ('clinic', 'member', 'settings', 'template') for row in snapshot['records']), 'synthetic fixture contains only clinic configuration and staff')
        return snapshot, {row['id']: row for row in snapshot['records']}

    req('POST', 'login', json={key: credentials[key] for key in ('username', 'password')})
    try:
        parent()
        if args.phase == 'setup':
            assert state['phase'] == 'setup_started', 'Setup already completed.'
            state.setdefault('child_name', 'SYNTHETIC Assistant Access ' + state['tag']); save()
            if 'child' not in state:
                state['child'] = act('create-child', 'organization.clinic_create', {'name': state['child_name'], 'timezone': 'Asia/Singapore'}); save()
            snapshot, records = child()
            check(not snapshot['clinic']['data'].get('locked_features'), 'fresh child starts without clinic locks')
            if 'member' not in state:
                state['member'] = act('create-member', 'member.save', {'name': 'SYNTHETIC Restricted Staff ' + state['tag'], 'role': 'nurse', 'active': True})['id']; save()
            state['phase'] = 'setup'; save()
        elif args.phase == 'review':
            assert state['phase'] in ('setup', 'review_started'), 'Complete setup before review.'
            state['phase'] = 'review_started'; save()
            snapshot, records = child(); member = records[state['member']]
            check(member['data']['name'] == 'SYNTHETIC Restricted Staff ' + state['tag'] and member['data']['role'] == 'nurse'
                  and member['data']['active'] and not member['data'].get('read_restrictions'), 'only the fresh unrestricted synthetic nurse is targeted')
            command = f"Set member {member['id']} read restrictions: read.billing reason: SYNTHETIC reviewed restriction {state['tag']}"
            if not state.get('stale_clinic_verified'):
                stale = ask('stale-access', 'Please ' + command)
                check(snapshot['clinic']['data'].get('locked_features', []) in ([], ['read.inventory']), 'only expected synthetic clinic locks may change')
                state.setdefault('lock_payload', {'version': snapshot['clinic']['version'], 'actions': ['read.inventory']}); save()
                act('tighten-clinic', 'feature_locks.save', state['lock_payload'])
                rejected = confirm(stale, 409)
                check(any(text in rejected.get('detail', '').lower() for text in ('access changed', 'review changed')), 'stale clinic access review is explicitly rejected')
                check(child()[1][state['member']] == member, 'stale confirmation leaves the synthetic nurse unchanged')
                state['stale_clinic_verified'] = True; save()
            fresh = ask('tighten-access', command)
            check(fresh['action']['payload']['id'] == state['member'] and fresh['action']['payload']['restrictions'] == ['read.billing'], 'fresh proposal binds exact member and displayed restriction list')
            fields = {field['label']: field['value'] for field in fresh['review']['fields']}
            check('read.inventory' in fields['Inherited read restrictions retained'] and fields['New complete member restrictions'].startswith('read.billing')
                  and 'Billing: Blocked' in fields['Views after confirmation with required dependencies'], 'complete review retains inherited locks and blocks billing')
            check(child()[1][state['member']] == member, 'review leaves member unchanged for browser confirmation')
            state['phase'] = 'reviewed'; save()
            print('In the browser select ' + state['child_name'] + ' and confirm only tighten-access (Set member…). Leave stale-access (Please Set member…) unconfirmed.', flush=True)
        else:
            assert state['phase'] == 'reviewed', 'Review and browser-confirm the fresh proposal first.'
            snapshot, records = child(); turn = state['turns']['tighten-access']
            saved = req('GET', 'assistant/conversations/' + turn['conversation_id'])['turns'][0]
            check(saved['review'] == turn['review'] and saved.get('execution'), 'exact review and browser confirmation persist in a new login')
            check(confirm(turn) == saved['execution'], 'completed confirmation replay returns its original receipt')
            member = records[state['member']]
            check(member['data']['read_restrictions'] == ['read.billing'] and member['data']['role'] == 'nurse' and member['data']['active'], 'only reviewed restriction applied; role and activity unchanged')
            check(snapshot['clinic']['data']['locked_features'] == ['read.inventory'], 'new clinic retains its tightened lock; no access widened')
            stale = state['turns']['stale-access']
            check(not req('GET', 'assistant/conversations/' + stale['conversation_id'])['turns'][0].get('execution'), 'stale proposal has no successful execution')
            state['result'] = saved['execution']; state['phase'] = 'complete'; save()
        parent()
    finally:
        client.post('logout')
