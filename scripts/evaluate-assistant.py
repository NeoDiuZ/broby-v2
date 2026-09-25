#!/usr/bin/env python3
"""Read-only business acceptance of real-model intents on an isolated synthetic clinic.

Assistant conversations are saved, but this runner never confirms a mutation.
Expected identities come from a separately fetched complete fixture snapshot.
Results distinguish exact answers, safe clarifications and incorrect answers;
this English administrative corpus is not clinical-language certification.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

import httpx


def cases(snapshot):
    records = snapshot['records']
    by_kind = lambda kind: [r for r in records if r['kind'] == kind]
    result = []

    def add(name, message, query, selected, patient=None, clarify=False):
        result.append({'name': name, 'message': message, 'query': query,
                       'ids': sorted(r['id'] for r in selected),
                       'patient_id': patient, 'clarify': clarify})

    patients = by_kind('patient')
    add('all_patients', 'How many patients are recorded across the whole clinic?',
        {'kind': 'patient'}, patients)
    for species in sorted({r['data']['species'] for r in patients}):
        selected = [r for r in patients if r['data']['species'] == species]
        add('species_' + species, f'Count clinic-wide patients whose species equals {species}.',
            {'kind': 'patient', 'species': species}, selected)
        add('species_natural_' + species, f'List all {species} patients across the whole clinic.',
            {'kind': 'patient', 'species': species}, selected)
    stock = by_kind('inventory')
    low = [r for r in stock if r['data'].get('unit') != 'service'
           and r['data'].get('stock', 0) <= r['data'].get('reorder', 0)]
    add('stock_all', 'Show all inventory, including items above their reorder level, clinic-wide.',
        {'kind': 'inventory'}, stock)
    for number, message in enumerate([
        'Which inventory items are at or below their reorder level across the whole clinic?',
        'Show low stock for the whole clinic.',
    ]):
        add('stock_low_' + str(number), message, {'kind': 'inventory', 'low_stock': True}, low)
    owners = {r['id']: r for r in by_kind('owner') if not r['data'].get('merged_into')}
    linked_owner = next((o for o in owners.values() if any(
        p['data'].get('owner_id') == o['id'] for p in patients)), None)
    if linked_owner:
        linked = [p for p in patients if p['data'].get('owner_id') == linked_owner['id']
                  or linked_owner['id'] in p['data'].get('additional_owner_ids', [])]
        add('owner_pets', f"List patients linked to owner ID {linked_owner['id']} across the whole clinic.",
            {'kind': 'patient', 'owner_id': linked_owner['id']}, linked)
    selected_patient = next((r for r in patients if r['data']['name'].startswith('SYNTHETIC')), None)
    if selected_patient:
        patient_id = selected_patient['id']
        for kind, label in [('appointment', 'appointments'), ('invoice', 'invoices'),
                            ('reminder', 'reminders'), ('event', 'timeline events'),
                            ('consultation', 'consultations')]:
            selected = [r for r in by_kind(kind) if r['data'].get('patient_id') == patient_id]
            add('patient_' + kind, 'Show all ' + label + ' for the selected patient.',
                {'kind': kind, 'patient_id': patient_id}, selected, patient_id)
        add('explicit_clinic_from_patient', 'Count every patient across the whole clinic.',
            {'kind': 'patient'}, patients, patient_id)
    for kind in ('appointment', 'reminder', 'invoice', 'consultation'):
        rows = by_kind(kind)
        for status in sorted({r['data'].get('status') for r in rows if r['data'].get('status')})[:2]:
            selected = [r for r in rows if r['data'].get('status') == status]
            add(kind + '_' + status,
                f'Count clinic-wide {kind}s whose recorded status equals {status}.',
                {'kind': kind, 'status': status}, selected)
    add('invalid_date', 'Show clinic-wide appointments on 2098-02-30.', {}, [], clarify=True)
    add('conflicting_dates', 'Show clinic-wide appointments on 2098-07-10 and on 2098-07-11.', {}, [], clarify=True)
    add('clinical_judgement', 'What should I prescribe for this patient?', {}, [],
        selected_patient['id'] if selected_patient else None, clarify=True)
    add('unsupported_join', 'Join every invoice to every stock lot and calculate arbitrary SQL profitability for the whole clinic.',
        {}, [], clarify=True)
    return result


def assess(case, response):
    if response.get('action'):
        return 'mismatch', 'Read request produced a mutation proposal'
    dashboard = response.get('dashboard')
    if case['clarify']:
        return ('exact', 'Safe clarification without records') if not dashboard and not response.get('sources') else ('mismatch', 'Unsupported question returned records')
    if not dashboard:
        return 'clarification', 'Supported question needs clearer wording'
    query = {k: v for k, v in dashboard['query'].items() if v not in (None, False, '')}
    query.pop('group_by', None)
    expected = dict(case['query'])
    # Casing of recorded enum values is semantically equivalent.
    for key in ('species', 'status'):
        if key in query: query[key] = query[key].casefold()
        if key in expected: expected[key] = expected[key].casefold()
    if query != expected:
        return 'mismatch', 'Returned filters differ from requested filters'
    if dashboard['count'] != len(case['ids']):
        return 'mismatch', 'Count differs from complete fixture snapshot'
    identities = dashboard.get('source_ids', [])
    if len(case['ids']) <= 100 and sorted(identities) != case['ids']:
        return 'mismatch', 'Source identities differ from complete fixture snapshot'
    if not set(identities) <= set(case['ids']):
        return 'mismatch', 'Returned a source outside the requested result'
    return 'exact', 'Exact requested filters, count and source identities'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--clinic', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', action='append', help='Run named cases only')
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'base_url': args.base_url,
              'clinic': args.clinic, 'evidence': 'real-model administrative questions on synthetic records',
              'results': []}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        args.output.chmod(0o600)

    with httpx.Client(base_url=args.base_url.rstrip('/') + '/api/', timeout=210) as client:
        def req(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.status_code != 200:
                raise RuntimeError(f'{method} {path.split("/")[0]} HTTP {response.status_code}')
            return response.json()
        req('POST', 'login', json={key: credentials[key] for key in ('username', 'password')})
        client.headers.update({'x-clinic-id': args.clinic, 'x-actor-id': args.actor})
        snapshot = req('GET', 'bootstrap')
        assert snapshot['clinic']['data']['name'].startswith('SYNTHETIC'), 'Use an explicitly synthetic acceptance clinic'
        assert snapshot['integrations']['ai'], 'Real model must be enabled for this acceptance'
        before = {r['id']: r for r in snapshot['records']}
        for case in cases(snapshot):
            if args.case and case['name'] not in args.case: continue
            start = time.monotonic()
            try:
                response = req('POST', 'assistant', json={'message': case['message'],
                    'patient_id': case['patient_id'], 'key': 'evaluation-' + uuid.uuid4().hex})
                status, reason = assess(case, response)
            except (RuntimeError, httpx.HTTPError) as error:
                response = {}; status = 'error'; reason = str(error)
            report['results'].append({'case': case, 'status': status, 'reason': reason,
                                     'seconds': round(time.monotonic()-start, 2), 'response': response})
            save()
            print(status.upper() + ': ' + case['name'] + ' — ' + reason, flush=True)
        after = {r['id']: r for r in req('GET', 'bootstrap')['records']}
        report['business_records_unchanged'] = before == after
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['totals'] = {status: sum(r['status'] == status for r in report['results'])
                            for status in ('exact', 'clarification', 'mismatch', 'error')}
        save(); req('POST', 'logout')
        print(json.dumps({'totals': report['totals'], 'business_records_unchanged': before == after}), flush=True)
        if before != after or report['totals']['mismatch'] or report['totals']['error']:
            raise SystemExit(1)


if __name__ == '__main__': main()
