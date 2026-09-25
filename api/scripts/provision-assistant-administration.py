#!/usr/bin/env python3
"""Service-side, opt-in V2 synthetic fixtures; never mounted as a public API.

Creates only fresh empty clinics and administrator memberships for one existing
V2 acceptance account. The operator must first verify the Railway project and
explicitly pass its ID. No existing clinic, organization, member or credential
is edited. State contains fixture identifiers only and is written with mode 0600.
"""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

# This is the isolated Broby New project, not the original Broby deployment.
V2_PROJECT = 'ca389ebd-0186-4b7e-baec-8ddacdfc406b'
parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--state', required=True, type=Path)
parser.add_argument('--account', required=True)
parser.add_argument('--confirm-v2-project', required=True)
args = parser.parse_args()
assert args.confirm_v2_project == V2_PROJECT and os.getenv('RAILWAY_PROJECT_ID') == V2_PROJECT, 'Verify the isolated Broby New Railway project before provisioning.'
assert os.getenv('BROBY_ENVIRONMENT', 'local') != 'local' and os.getenv('BROBY_AUTH_MODE') == 'password', 'Provisioning requires the verified hosted V2 password environment.'
base = args.base_url.rstrip('/')
assert urlsplit(base).scheme == 'https' and not urlsplit(base).username and urlsplit(base).path == '' and not urlsplit(base).query and not urlsplit(base).fragment, 'Use the verified V2 HTTPS origin.'
assert not args.state.exists(), 'State already exists; refuse to duplicate or replace acceptance fixtures.'

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import connection, get, record
from runtime import allowed_origins
assert base in allowed_origins(), 'The supplied origin is not an allowed origin of this V2 service.'

tag = uuid.uuid4().hex[:12]
state = {'base': base, 'project_id': V2_PROJECT, 'account': args.account, 'tag': tag,
         'phase': 'provisioned', 'fixture_type': 'assistant-administration', 'clinics': {}}
for purpose in ('access', 'withdrawal'):
    cid = 'synthetic-assistant-admin-' + tag + '-' + purpose
    state['clinics'][purpose] = {'id': cid, 'member_id': cid + '-admin',
        'name': 'SYNTHETIC Assistant Administration ' + tag + ' ' + purpose}
args.state.parent.mkdir(parents=True, exist_ok=True)
# Exclusive creation protects the recorded run identity as well as fresh IDs.
fd = os.open(args.state, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(fd, 'w') as output:
        with connection(True) as c:
            assert c.execute('SELECT 1 FROM credentials WHERE username=?', (args.account,)).fetchone(), 'Use an existing V2 acceptance account; no credentials are created.'
            memberships = [dict(row) for row in c.execute('SELECT clinic_id,member_id FROM auth_memberships WHERE username=?', (args.account,))]
            assert any((member := get(c, row['member_id'], row['clinic_id'])) and member['kind'] == 'member'
                       and member['data'].get('active') and member['data'].get('role') == 'admin'
                       for row in memberships), 'The acceptance account must already have an active administrator membership.'
            state['existing_memberships'] = memberships
            state['existing_active_memberships'] = [row for row in memberships if
                (member := get(c, row['member_id'], row['clinic_id'])) and member['data'].get('active')]
            for fixture in state['clinics'].values():
                cid, mid = fixture['id'], fixture['member_id']
                assert cid.startswith('synthetic-assistant-admin-' + tag + '-')
                assert not get(c, cid) and not get(c, mid), 'Fixture IDs must be fresh.'
                assert not c.execute('SELECT 1 FROM organization_clinics WHERE clinic_id=?', (cid,)).fetchone()
                record(c, 'clinic', cid, {'name': fixture['name'], 'timezone': 'Asia/Singapore', 'locked_features': [],
                    'synthetic_acceptance': 'assistant-administration', 'synthetic_tag': tag}, cid)
                record(c, 'member', cid, {'name': 'SYNTHETIC Acceptance Administrator ' + tag, 'role': 'admin', 'active': True}, mid)
                record(c, 'settings', cid, {'retention': 'medical', 'language': 'en', 'emergency_phone': '', 'reminder_days': 7,
                    'auto_reminders': False, 'auto_handover': False, 'handover_at': '07:00'}, 'settings-' + cid)
                record(c, 'template', cid, {'name': 'SOAP', 'description': 'Synthetic acceptance template',
                    'sections': ['Subjective', 'Objective', 'Assessment', 'Plan']}, 'soap-' + cid)
                c.execute('INSERT INTO auth_memberships VALUES(?,?,?)', (args.account, mid, cid))
            json.dump(state, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
except Exception:
    args.state.unlink(missing_ok=True)
    raise
print('PASS created two fresh SYNTHETIC clinics and new memberships for the existing acceptance account; no credentials or existing records changed.')
print('State path: ' + str(args.state))
