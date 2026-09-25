#!/usr/bin/env python3
"""Read-only hosted acceptance of disabled clinical escalation in one synthetic clinic.

Only password login/logout change authentication sessions. This helper never
creates a fixture, changes clinic policy, submits an action or sends an alert.
Credentials are read from a private JSON file containing username and password.
"""
import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class AcceptanceError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def run(args, client_factory=httpx.Client):
    base = args.base_url.rstrip('/')
    url = urlsplit(base)
    require(url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
            and not url.path and not url.query and not url.fragment,
            'Use an HTTPS origin without a path, credentials, query or fragment.')
    require(bool(args.clinic) and bool(args.actor), 'An exact clinic and actor are required.')
    require(bool(re.match(r'^SYNTHETIC\b', args.clinic_name)), 'The exact clinic name must be marked SYNTHETIC.')
    binding = {'base_url': base, 'clinic': args.clinic, 'actor': args.actor, 'clinic_name': args.clinic_name}
    require(args.output.resolve() != args.credentials.resolve(), 'Evidence output must differ from the credentials file.')
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        require(previous.get('binding') == binding, 'Existing evidence belongs to a different target.')
    credentials = json.loads(args.credentials.read_text())
    require(all(isinstance(credentials.get(k), str) and credentials[k] for k in ('username', 'password')),
            'The private credentials file must contain username and password.')
    checks = []

    def check(condition, label):
        require(condition, label)
        checks.append(label)

    with client_factory(base_url=base + '/api/', headers={'Origin': base, 'x-clinic-id': args.clinic,
                        'x-actor-id': args.actor}, timeout=120, follow_redirects=False, trust_env=False) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            require(response.status_code == 200, f'{method} {path}: unexpected HTTP status {response.status_code}.')
            return response.json()

        request('POST', 'login', json={k: credentials[k] for k in ('username', 'password')})
        try:
            snapshot = request('GET', 'bootstrap')
            clinic = snapshot.get('clinic') or {}
            actor = snapshot.get('actor') or {}
            check(snapshot.get('mode') == 'password', 'Password authentication is enabled')
            check(clinic.get('id') == args.clinic and clinic.get('kind') == 'clinic'
                  and clinic.get('data', {}).get('name') == args.clinic_name,
                  'Exact existing synthetic clinic is selected')
            check(actor.get('id') == args.actor and actor.get('kind') == 'member'
                  and actor.get('clinic_id') == args.clinic and actor.get('data', {}).get('active') is True,
                  'Exact active staff membership is selected')
            records = snapshot.get('records')
            check(isinstance(records, list) and snapshot.get('unchanged') is not True,
                  'A complete fresh bootstrap was returned')
            check(not any(r.get('kind') == 'owner_policy' and r.get('data', {}).get('escalation', {}).get('enabled')
                          for r in records), 'No clinic owner policy enables external clinical escalation')
            status = request('GET', 'clinical-escalations')
            check(status.get('mode') == 'disabled', 'Clinical escalation transport is disabled')
            check(status.get('routes') == [], 'No clinical destination aliases are exposed')
            check(status.get('monitor_state') == 'disabled', 'Clinical escalation monitor is disabled')
            check(status.get('incidents') == [] and status.get('counts') == {}
                  and status.get('unresolved_count') == 0 and status.get('truncated') is False,
                  'The selected synthetic clinic has no clinical escalation incidents')
        finally:
            request('POST', 'logout')

    result = {'binding': binding, 'verified_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Authenticated read-only checks of this synthetic clinic; no sends or policy changes',
              'checks': checks, 'passed': len(checks)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=args.output.parent, prefix='.clinical-disabled-', delete=False) as f:
        temporary = Path(f.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump(result, f, indent=2)
            f.write('\n')
            f.flush()
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--clinic', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--clinic-name', required=True, help='Exact existing name, marked SYNTHETIC')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args)
    except AcceptanceError as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        # Never print response bodies, credential contents or transport URLs.
        raise SystemExit('Acceptance did not complete. Check private inputs and service availability.') from None
    print(json.dumps({'passed': result['passed'], 'evidence': str(args.output)}))


if __name__ == '__main__':
    main()
