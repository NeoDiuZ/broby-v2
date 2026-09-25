#!/usr/bin/env python3
"""Opt-in synthetic real-model linked reads and saved-view refresh.

Only the named SYNTHETIC clinic is eligible. Setup creates new marked fixtures;
evaluate never confirms an assistant mutation. Readback changes only the new
owner's own synthetic links through a reviewed shared owner merge. No messages,
provider calls other than model intent, or real money movement are requested.
"""
import argparse
import json
import os
import uuid
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--credentials', required=True, type=Path)
parser.add_argument('--state', required=True, type=Path)
parser.add_argument('--clinic', required=True)
parser.add_argument('--actor', required=True)
parser.add_argument('--history-record', help='Optional existing synthetic imported medication-history record, read-only')
parser.add_argument('--phase', required=True, choices=('setup', 'evaluate', 'readback'))
args = parser.parse_args()
base = args.base_url.rstrip('/')
state = json.loads(args.state.read_text()) if args.state.exists() else {}
binding = {'base': base, 'clinic': args.clinic, 'actor': args.actor, 'history_record': args.history_record}
if state:
    assert all(state.get(k) == v for k, v in binding.items()), 'State belongs to another target.'
else:
    assert args.phase == 'setup', 'Create synthetic fixtures first.'
    state = {**binding, 'tag': uuid.uuid4().hex[:10], 'phase': 'setup_started', 'fixtures': {}}
    args.state.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(args.state, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f: json.dump(state, f, indent=2)


def save():
    args.state.write_text(json.dumps(state, indent=2)); args.state.chmod(0o600)


def check(ok, label):
    assert ok, label
    print('PASS ' + label, flush=True)


with httpx.Client(base_url=base + '/api/', headers={'Origin': base}, timeout=210) as client:
    def req(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == 200, (method, path.split('/')[0], response.status_code)
        return response.json()

    def action(case, name, payload):
        return req('POST', 'actions', json={'action': name, 'payload': payload, 'key': 'linked-read-' + state['tag'] + '-' + case})

    def fixture(case, name, payload):
        if case not in state['fixtures']:
            state['fixtures'][case] = action(case, name, payload); save()
        return state['fixtures'][case]

    credentials = json.loads(args.credentials.read_text())
    req('POST', 'login', json={key: credentials[key] for key in ('username', 'password')})
    client.headers.update({'x-clinic-id': args.clinic, 'x-actor-id': args.actor})
    try:
        snapshot = req('GET', 'bootstrap')
        check(snapshot['clinic']['id'] == args.clinic and snapshot['actor']['id'] == args.actor
              and snapshot['clinic']['data']['name'].startswith('SYNTHETIC'), 'exact synthetic clinic and actor verified')
        rows = {row['id']: row for row in snapshot['records']}
        if args.phase == 'setup':
            assert state['phase'] == 'setup_started', 'Setup already completed.'
            owner = fixture('owner', 'owner.create', {'name': 'SYNTHETIC Linked Owner ' + state['tag']})
            primary = fixture('primary', 'patient.create', {'name': 'SYNTHETIC Read Cat ' + state['tag'], 'species': 'Cat', 'owner_id': owner['id']})
            extra = fixture('additional', 'patient.create', {'name': 'SYNTHETIC Read Dog ' + state['tag'], 'species': 'Dog', 'owner_name': 'SYNTHETIC Second Owner ' + state['tag']})
            fixture('additional-link', 'patient.owners', {'id': extra['id'], 'version': extra['version'], 'owner_id': extra['data']['owner_id'], 'additional_owner_ids': [owner['id']]})
            for case, patient in (('primary', primary), ('additional', extra)):
                fixture(case + '-invoice', 'invoice.create', {'patient_id': patient['id'], 'items': [{'name': 'SYNTHETIC query charge', 'quantity': 1, 'price_cents': 100}]})
                fixture(case + '-reminder', 'reminder.create', {'patient_id': patient['id'], 'title': 'SYNTHETIC query reminder', 'due': '2098-10-11'})
            duplicate_name = 'SYNTHETIC Choice ' + state['tag']
            for species, cents in (('Cat', 100), ('Dog', 200)):
                duplicate = fixture('choice-' + species, 'patient.create', {'name': duplicate_name, 'species': species, 'owner_name': 'SYNTHETIC Choice Owner ' + species + ' ' + state['tag']})
                fixture('choice-' + species + '-invoice', 'invoice.create', {'patient_id': duplicate['id'], 'items': [{'name': 'SYNTHETIC ' + species + ' charge', 'quantity': 1, 'price_cents': cents}]})
                fixture('choice-' + species + '-reminder', 'reminder.create', {'patient_id': duplicate['id'], 'title': 'SYNTHETIC ' + species + ' reminder', 'due': '2098-10-11'})
            state['browser'] = {'duplicate_prompt': 'Show reminders for ' + duplicate_name + ' whose status equals due on 2098-10-11',
                                'catalog_prompt': 'Open the dictionary definition review in Observation catalog.'}; save()
            for strength in ('5mg', '50mg'):
                stock = fixture(strength + '-stock', 'inventory.create', {'name': 'SYNTHETIC Compound ' + state['tag'] + ' ' + strength, 'unit': 'tablet', 'stock': 3, 'reorder': 0})
                fixture(strength + '-medication', 'medication.dispense', {'patient_id': primary['id'], 'inventory_id': stock['id'], 'version': stock['version'], 'quantity': 1, 'dose': 'SYNTHETIC source dose', 'frequency': 'SYNTHETIC source frequency', 'instructions': 'SYNTHETIC fixture only; not for clinical use'})
            if args.history_record:
                history = rows.get(args.history_record)
                check(history and history['kind'] == 'medication_history' and history['data'].get('name')
                      and rows.get(history['data'].get('patient_id'), {}).get('data', {}).get('name', '').startswith('SYNTHETIC'), 'optional imported-history receipt belongs to an existing synthetic patient')
                state['history'] = history
            state['phase'] = 'setup'; save()
        elif args.phase == 'evaluate':
            assert state['phase'] in ('setup', 'evaluation_started'), 'Complete setup before evaluation.'
            check(snapshot['integrations']['ai'], 'configured model is enabled for this acceptance')
            state['phase'] = 'evaluation_started'; save()
            f = state['fixtures']; owner = f['owner']['id']; primary = f['primary']['id']
            cases = [
                ('invoices', f'Show outstanding invoices for patients currently linked to owner ID {owner} across the whole clinic.', {'kind': 'invoice', 'owner_id': owner, 'outstanding': True}, [f['primary-invoice']['id'], f['additional-invoice']['id']], None),
                ('reminders', f'Show reminders whose status equals due on 2098-10-11 for patients currently linked to owner ID {owner} across the whole clinic.', {'kind': 'reminder', 'owner_id': owner, 'status': 'due', 'start': '2098-10-11', 'end': '2098-10-11'}, [f['primary-reminder']['id'], f['additional-reminder']['id']], None),
            ]
            name = f['5mg-stock']['data']['name']
            cases += [
                ('local-medication', f'Show local prescriptions whose recorded medication name equals "{name}" for this patient.', {'kind': 'medication', 'patient_id': primary, 'name': name}, [f['5mg-medication']['id']], primary),
                ('history-separation', f'Show imported medication history whose recorded medication name equals "{name}" for this patient.', {'kind': 'medication_history', 'patient_id': primary, 'name': name}, [], primary),
            ]
            if state.get('history'):
                history = state['history']; name = history['data']['name']; patient = history['data']['patient_id']
                cases.append(('history-positive', f'Show imported medication history whose recorded medication name equals "{name}" for this patient.', {'kind': 'medication_history', 'patient_id': patient, 'name': name}, [row['id'] for row in rows.values() if row['kind'] == 'medication_history' and row['data'].get('patient_id') == patient and str(row['data'].get('name', '')).casefold() == name.casefold()], patient))
            before = rows
            for case, message, expected, ids, patient in cases:
                answer = req('POST', 'assistant', json={'message': message, 'patient_id': patient, 'key': 'linked-read-' + state['tag'] + '-' + case})
                state.setdefault('answers', {})[case] = answer; save()
                check(not answer.get('action') and bool(answer.get('dashboard')), case + ': factual answer without mutation proposal')
                actual = dict(answer['dashboard']['query']); actual.pop('group_by', None)
                if 'name' in actual: actual['name'] = actual['name'].casefold(); expected['name'] = expected['name'].casefold()
                check(actual == expected and answer['dashboard']['count'] == len(ids)
                      and set(answer['dashboard']['source_ids']) == set(ids), case + ': exact filters, complete count and source identities')
            choices = req('POST', 'assistant', json={'message': state['browser']['duplicate_prompt'], 'key': 'linked-read-' + state['tag'] + '-browser-choice'})
            check({r['id'] for r in choices.get('choices', [])} == {f['choice-Cat']['id'], f['choice-Dog']['id']}
                  and not choices.get('action') and not choices.get('dashboard'), 'browser fixture presents only the two same-name synthetic patients')
            catalog = req('POST', 'assistant', json={'message': state['browser']['catalog_prompt'], 'key': 'linked-read-' + state['tag'] + '-browser-catalog'})
            check(catalog.get('navigate') == 'Settings' and catalog.get('navigate_section') == 'Observation catalog'
                  and not catalog.get('action'), 'browser fixture opens catalog review without mutation')
            state['browser_turns'] = {'choices': choices, 'catalog': catalog}; save()
            check({r['id']: r for r in req('GET', 'bootstrap')['records']} == before, 'all model reads leave clinic records unchanged')
            for case, answer in state['answers'].items():
                view = fixture('view-' + case, 'dashboard.save', {'name': 'SYNTHETIC Linked ' + case + ' ' + state['tag'], 'query': answer['dashboard']['query']})
                saved = req('GET', 'dashboards/' + view['id'])['result']
                check(saved['query'] == answer['dashboard']['query'] and saved['count'] == answer['dashboard']['count'], case + ': saved view retains exact read')
            state['phase'] = 'evaluated'; save()
        else:
            assert state['phase'] in ('evaluated', 'readback_started'), 'Evaluate before persisted readback.'
            choice = req('GET', 'assistant/conversations/' + state['browser_turns']['choices']['conversation_id'])
            f = state['fixtures']; selected = choice['turns'][-1]
            selected_species = next((species for species in ('Cat', 'Dog') if selected.get('patient_id') == f['choice-' + species]['id']), None)
            check(len(choice['turns']) >= 2 and selected_species and selected['message'] == state['browser']['duplicate_prompt']
                  and not selected.get('action'), 'browser patient choice retains the exact original request in its saved conversation')
            expected = {'kind': 'reminder', 'patient_id': f['choice-' + selected_species]['id'], 'status': 'due', 'start': '2098-10-11', 'end': '2098-10-11'}
            selected_query = dict(selected.get('dashboard', {}).get('query', {})); selected_query.pop('group_by', None)
            check(selected_query == expected and selected['dashboard']['count'] == 1
                  and selected['dashboard']['source_ids'] == [f['choice-' + selected_species + '-reminder']['id']], 'selected patient answer preserves filters and only its exact reminder source')
            catalog = req('GET', 'assistant/conversations/' + state['browser_turns']['catalog']['conversation_id'])['turns'][0]
            check(catalog.get('navigate') == 'Settings' and catalog.get('navigate_section') == 'Observation catalog'
                  and not catalog.get('action'), 'catalog review destination persists without a mutation')
            state['phase'] = 'readback_started'; save()
            original = rows[f['owner']['id']]
            check(original['data']['name'] == 'SYNTHETIC Linked Owner ' + state['tag'], 'owner merge targets only this newly created synthetic fixture')
            target = fixture('merged-owner', 'owner.create', {'name': 'SYNTHETIC Current Owner ' + state['tag']})
            fixture('owner-merge', 'owner.merge', {'id': f['owner']['id'], 'version': f['owner']['version'], 'target_id': target['id']})
            for case, answer in state['answers'].items():
                stored = req('GET', 'assistant/conversations/' + answer['conversation_id'])['turns'][0]
                check(stored['dashboard'] == answer['dashboard'] and not stored.get('execution'), case + ': saved answer persists as its original read snapshot')
                saved = req('GET', 'dashboards/' + f['view-' + case]['id'])['result']
                check(saved['count'] == answer['dashboard']['count'] and {r['id'] for r in saved['records']} == set(answer['dashboard']['source_ids']), case + ': current saved view preserves exact source membership')
                if case in ('invoices', 'reminders'):
                    check(saved['query']['owner_id'] == target['id'], case + ': saved owner query resolves only the reviewed synthetic merge')
            state['phase'] = 'complete'; save()
    finally:
        client.post('logout')
