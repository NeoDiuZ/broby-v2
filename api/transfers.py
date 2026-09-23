"""Revocable owner consent, reviewed receiving copies and immutable origin revisions."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field, StrictBool
import db
from db import connection, get, record, all_records, now, uid
from actions import fail, owned

router = APIRouter()
PERMISSIONS = {'transfer.accept': {'vet', 'admin'}}
MAX_BYTES = 100 * 1024 * 1024
MAX_ITEMS = 1000
DEFAULT_SCOPE = {'medications': False, 'audio': False}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def setup(c):
    c.execute('CREATE TABLE IF NOT EXISTS transferred_patients(source_clinic TEXT,source_patient TEXT,target_clinic TEXT,target_patient TEXT,PRIMARY KEY(source_clinic,source_patient,target_clinic))')
    c.execute('CREATE TABLE IF NOT EXISTS transfer_requests(id TEXT PRIMARY KEY,source_clinic TEXT,target_clinic TEXT,patient_id TEXT,grant_token TEXT,status TEXT,expires_at TEXT,result TEXT)')
    if 'scope' not in {r[1] for r in c.execute('PRAGMA table_info(transfer_requests)')}:
        c.execute("ALTER TABLE transfer_requests ADD COLUMN scope TEXT NOT NULL DEFAULT '{\"medications\":false,\"audio\":false}'")
    c.execute('''CREATE TABLE IF NOT EXISTS transfer_revisions(
        source_clinic TEXT,source_patient TEXT,target_clinic TEXT,kind TEXT,origin_id TEXT,
        fingerprint TEXT,revision INTEGER,target_id TEXT,payload TEXT,request_id TEXT,
        PRIMARY KEY(source_clinic,source_patient,target_clinic,kind,origin_id,revision))''')


class Consent(BaseModel):
    target_clinic: str = Field(min_length=1, max_length=200)
    consent: StrictBool
    include_medications: StrictBool = False
    include_audio: StrictBool = False


@router.get('/api/owner/{token}/transfer-clinics')
def clinics(token: str):
    from portal import grant
    with connection() as c:
        g = grant(c, token)
        return [{'id': r['id'], 'name': r['data']['name']} for r in
                [db.unpack(row) for row in c.execute("SELECT * FROM records WHERE kind='clinic'")]
                if r['id'] != g['clinic_id']]


@router.post('/api/owner/{token}/transfers')
def request_transfer(token: str, p: Consent):
    from portal import grant
    if not p.consent:
        fail('Explicit sharing consent is required')
    scope = {'medications': p.include_medications, 'audio': p.include_audio}
    with connection(True) as c:
        g = grant(c, token)
        owned(c, p.target_clinic, p.target_clinic, 'clinic')
        if p.target_clinic == g['clinic_id']:
            fail('Choose a different clinic')
        existing = c.execute("SELECT * FROM transfer_requests WHERE grant_token=? AND target_clinic=? AND status='pending' AND expires_at>?", (g['token'], p.target_clinic, now())).fetchone()
        if existing:
            if json.loads(existing['scope']) != scope:
                fail('Withdraw the pending request before changing what you share', 409)
            return {'id': existing['id'], 'status': 'pending', 'expires_at': existing['expires_at'], 'scope': scope}
        id = uid()
        expiry = min(g['expires_at'], (datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
        c.execute('INSERT INTO transfer_requests(id,source_clinic,target_clinic,patient_id,grant_token,status,expires_at,result,scope) VALUES(?,?,?,?,?,?,?,NULL,?)',
                  (id, g['clinic_id'], p.target_clinic, g['patient_id'], g['token'], 'pending', expiry, encoded(scope)))
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (uid(), g['clinic_id'], 'owner-grant', 'transfer.consented', id, now()))
        return {'id': id, 'status': 'pending', 'expires_at': expiry, 'scope': scope}


@router.delete('/api/owner/{token}/transfers/{id}')
def revoke_transfer(token: str, id: str):
    from portal import grant
    with connection(True) as c:
        g = grant(c, token)
        r = c.execute('SELECT * FROM transfer_requests WHERE id=? AND grant_token=?', (id, g['token'])).fetchone()
        if not r:
            fail('Transfer not found', 404)
        if r['status'] == 'accepted':
            fail('The receiving clinic already imported its copy; contact that clinic about its medical records', 409)
        c.execute("UPDATE transfer_requests SET status='revoked' WHERE id=?", (id,))
    return {'revoked': True}


@router.get('/api/owner/{token}/transfers')
def owner_requests(token: str):
    from portal import grant
    with connection() as c:
        g = grant(c, token)
        return [{'id': r['id'], 'target_clinic': r['target_clinic'],
                 'status': 'expired' if r['status'] == 'pending' and r['expires_at'] <= now() else r['status'],
                 'expires_at': r['expires_at'], 'scope': json.loads(r['scope'])}
                for r in c.execute('SELECT * FROM transfer_requests WHERE grant_token=? ORDER BY rowid DESC', (g['token'],))]


def pending(c, id, clinic):
    from portal import grant
    r = c.execute('SELECT * FROM transfer_requests WHERE id=? AND target_clinic=?', (id, clinic)).fetchone()
    if not r:
        fail('Transfer request not found', 404)
    if r['status'] == 'accepted':
        return r
    if r['status'] != 'pending' or r['expires_at'] <= now():
        fail('Transfer request expired or revoked', 409)
    g = grant(c, r['grant_token'])
    if g['patient_id'] != r['patient_id'] or g['clinic_id'] != r['source_clinic']:
        fail('Sharing permission does not match this patient', 409)
    return r


@router.get('/api/transfers/incoming')
def incoming(request: Request):
    from main import identity
    from actions import authorize
    clinic, actor = identity(request)
    with connection() as c:
        authorize(c, clinic, actor, 'transfer.accept')
        results = []
        for r in c.execute("SELECT * FROM transfer_requests WHERE target_clinic=? AND status='pending' AND expires_at>?", (clinic, now())):
            try:
                pending(c, r['id'], clinic)
            except HTTPException:
                continue
            results.append({'id': r['id'], 'patient_name': owned(c, r['patient_id'], r['source_clinic'], 'patient')['data']['name'],
                            'source_clinic': owned(c, r['source_clinic'], r['source_clinic'], 'clinic')['data']['name'],
                            'expires_at': r['expires_at'], 'scope': json.loads(r['scope'])})
        return results


def fields(data, names):
    return {k: data[k] for k in names if k in data}


def verified_binary(path, expected_hash, budget):
    try:
        path = Path(path)
        size = path.stat().st_size
        if size > budget or size < 1:
            fail('Transfer exceeds 100 MB or contains empty media; arrange a reviewed archive transfer', 422)
        # A bounded read also guards a file growing between stat and read.
        with path.open('rb') as stream:
            content = stream.read(budget + 1)
        if len(content) > budget:
            fail('Transfer exceeds 100 MB', 422)
    except OSError:
        fail('An approved media file is unavailable; ask the source clinic to repair it', 409)
    if hashlib.sha256(content).hexdigest() != expected_hash:
        fail('Transferred media checksum mismatch', 409)
    return content


def snapshot(c, r):
    """Build a bounded, explicit data allowlist; private source notes never cross clinics."""
    from portal import grant, view
    data = view(c, grant(c, r['grant_token']))
    source_patient = owned(c, r['patient_id'], r['source_clinic'], 'patient')
    owner = owned(c, source_patient['data']['owner_id'], r['source_clinic'], 'owner')
    scope = json.loads(r['scope'])
    identity = {'patient': fields(source_patient['data'], ('name', 'species', 'breed', 'sex', 'weight', 'age', 'date_of_birth', 'external_id')),
                'owner': fields(owner['data'], ('name', 'phone', 'email')), 'owner_id': owner['id']}
    items = [{'kind': 'identity', 'origin_id': source_patient['id'], 'payload': identity}]
    for e in data['events']:
        d = e['data']
        # Medication-specific consent includes the structured history. Existing approved
        # clinical notes may themselves mention medicine, as disclosed in the owner UI.
        payload = fields(d, ('title', 'body', 'category', 'occurred_at', 'observations'))
        items.append({'kind': 'event', 'origin_id': e['id'], 'payload': payload})
    if scope.get('medications'):
        for m in data['medications']:
            payload = fields(m['data'], ('name', 'quantity', 'dose', 'frequency', 'instructions', 'prescribed_by'))
            payload['recorded_at'] = m['created_at']
            items.append({'kind': 'medication', 'origin_id': m['id'], 'payload': payload})
    audio = data['audio'] if scope.get('audio') else []
    if len(data['files']) > 25 or len(audio) > 25:
        fail('Transfer exceeds 25 files or 25 voice notes; arrange a reviewed archive transfer')
    binaries = {}
    total = 0
    for f in data['files']:
        original = owned(c, f['id'], r['source_clinic'], 'attachment')
        content = verified_binary(original['data']['path'], original['data']['sha256'], MAX_BYTES - total)
        if len(content) != original['data']['size']:
            fail('Transferred file size mismatch', 409)
        total += len(content)
        payload = fields(original['data'], ('name', 'mime', 'size', 'sha256'))
        payload['recorded_at'] = original['created_at']
        items.append({'kind': 'file', 'origin_id': f['id'], 'payload': payload})
        binaries[('file', f['id'])] = [content]
    for a in audio:
        original = owned(c, a['id'], r['source_clinic'], 'recording')
        d = original['data']
        chunks = list(c.execute('SELECT * FROM chunks WHERE recording_id=? ORDER BY chunk_index', (a['id'],)))
        expected = d.get('expected_chunks', 0)
        if d.get('status') != 'saved' or not 1 <= expected <= 4000 or [x['chunk_index'] for x in chunks] != list(range(expected)):
            fail('Approved audio has an incomplete finalized manifest', 409)
        parts = []
        manifest = []
        for chunk in chunks:
            content = verified_binary(chunk['path'], chunk['sha256'], MAX_BYTES - total)
            total += len(content)
            parts.append(content)
            manifest.append({'index': chunk['chunk_index'], 'sha256': chunk['sha256'], 'size': len(content)})
        payload = fields(d, ('title', 'mime', 'duration', 'interrupted'))
        payload.update(recorded_at=original['created_at'], manifest=manifest)
        items.append({'kind': 'audio', 'origin_id': a['id'], 'payload': payload})
        binaries[('audio', a['id'])] = parts
    if len(items) > MAX_ITEMS or len(encoded(items).encode()) > 5 * 1024 * 1024:
        fail('Transfer exceeds the reviewed record limit; arrange an archive transfer')
    return sorted(items, key=lambda x: (x['kind'], x['origin_id'])), binaries, total


def plan(c, r):
    items, binaries, total = snapshot(c, r)
    key = (r['source_clinic'], r['patient_id'], r['target_clinic'])
    mapped = c.execute('SELECT target_patient FROM transferred_patients WHERE source_clinic=? AND source_patient=? AND target_clinic=?', key).fetchone()
    target = owned(c, mapped[0], r['target_clinic'], 'patient') if mapped else None
    revisions = list(c.execute('SELECT * FROM transfer_revisions WHERE source_clinic=? AND source_patient=? AND target_clinic=? ORDER BY revision', key))
    # Historical payloads cannot be reconstructed reliably. A reviewed baseline
    # appends today's approved facts; it never labels an old copy as equivalent.
    baseline = legacy_review(c, r, target) if target and not revisions else None
    counts = {'new': 0, 'changed': 0, 'unchanged': 0}
    for item in items:
        fp = digest(item['payload'])
        prior = [x for x in revisions if x['kind'] == item['kind'] and x['origin_id'] == item['origin_id']]
        last = prior[-1] if prior else None
        # A source reverting to an older value is still a change from the last
        # accepted revision. It needs review and a dated revision, not a silent skip.
        state = 'unchanged' if last and last['fingerprint'] == fp else 'changed' if prior else 'new'
        current = get(c, last['target_id'], r['target_clinic']) if last else None
        item.update(fingerprint=fp, state=state, revision=(max([x['revision'] for x in prior], default=0) + 1),
                    previous=json.loads(last['payload']) if last else None, destination_copy=current)
        counts[state] += 1
    identity = next(x['payload'] for x in items if x['kind'] == 'identity')
    public = {'id': r['id'], 'source_clinic': {'id': r['source_clinic'], 'name': owned(c, r['source_clinic'], r['source_clinic'], 'clinic')['data']['name']},
              'source_patient_id': r['patient_id'], 'scope': json.loads(r['scope']), 'expires_at': r['expires_at'],
              'patient': identity['patient'], 'owner': identity['owner'], 'destination_patient': target,
              'destination_owner': owned(c, target['data']['owner_id'], r['target_clinic'], 'owner') if target else None,
              'baseline_required': baseline is not None, 'baseline': baseline,
              'counts': counts, 'media_bytes': total, 'items': items}
    public['digest'] = digest(public)
    return public, binaries


def legacy_review(c, r, patient):
    """Bounded receiving-side context. Only this patient's clinical records cross
    the preview boundary; request capabilities and filesystem paths never do."""
    kinds = {'event', 'source', 'attachment', 'observation', 'recording', 'medication_history', 'consultation'}
    rows = c.execute("SELECT * FROM records WHERE clinic_id=? AND json_extract(data,'$.patient_id')=? ORDER BY kind,id LIMIT ?",
                     (r['target_clinic'], patient['id'], MAX_ITEMS + 1)).fetchall()
    if len(rows) > MAX_ITEMS:
        fail('The receiving record exceeds the baseline review limit; arrange a reviewed archive reconciliation', 422)
    from spine.reader import native_records
    records = [db.unpack(row) for row in rows if row['kind'] in kinds]
    records.extend(native_records(r['target_clinic'], patient['id']))
    if len(records) > MAX_ITEMS:
        fail('The receiving record exceeds the baseline review limit; arrange a reviewed archive reconciliation', 422)
    records.sort(key=lambda x: (x['kind'], x['id']))
    records = [{**x, 'data': {k: v for k, v in x['data'].items() if k != 'path'}} for x in records]
    requests = [{'id': row['id'], 'status': row['status']} for row in c.execute(
        "SELECT id,status FROM transfer_requests WHERE source_clinic=? AND patient_id=? AND target_clinic=? AND status='accepted' ORDER BY id LIMIT ?",
        (r['source_clinic'], r['patient_id'], r['target_clinic'], MAX_ITEMS + 1))]
    context = {'mode': 'append_current_source', 'existing_records': records, 'earlier_requests': requests}
    if len(requests) > MAX_ITEMS or len(encoded(context).encode()) > 5 * 1024 * 1024:
        fail('The receiving history exceeds the baseline review limit; arrange a reviewed archive reconciliation', 422)
    return context


@router.get('/api/transfers/{id}/preview')
def preview(id: str, request: Request):
    from main import identity
    from actions import authorize
    clinic, actor = identity(request)
    with connection() as c:
        authorize(c, clinic, actor, 'transfer.accept')
        c.execute('BEGIN')
        r = pending(c, id, clinic)
        if r['status'] == 'accepted':
            fail('This request was already accepted', 409)
        result, _ = plan(c, r)
        # Do not expose local media paths in previews. The full copy participates in
        # the digest so a receiving edit invalidates an earlier review.
        for item in result['items']:
            local = item['destination_copy']
            if local:
                item['destination_copy'] = {**local, 'data': {k: v for k, v in local['data'].items() if k != 'path'}}
        return result


def receipt_text(item):
    d = item['payload']
    if item['kind'] == 'event':
        text = d.get('body', '')
        for o in d.get('observations', []):
            text += '\n' + f"{o['name']}: {o['value']} {o['unit']} (supplied range {o.get('ref_low')}–{o.get('ref_high')})"
        return text
    if item['kind'] == 'medication':
        labels = {'name': 'Medication', 'quantity': 'Recorded quantity', 'dose': 'Recorded dose', 'frequency': 'Recorded frequency',
                  'instructions': 'Source instructions', 'prescribed_by': 'Source prescriber reference', 'recorded_at': 'Originally recorded'}
        return ('Externally recorded medication history. This is not a new prescription or dispensing instruction.\n' +
                '\n'.join(f'{labels[k]}: {v}' for k, v in d.items()))
    if item['kind'] == 'identity':
        labels = {'name': 'Name', 'species': 'Species', 'breed': 'Breed', 'sex': 'Sex', 'weight': 'Weight (kg)', 'age': 'Recorded age',
                  'date_of_birth': 'Date of birth', 'external_id': 'Source patient reference', 'phone': 'Phone', 'email': 'Email'}
        lines = ['Source clinic patient and owner details at transfer. Local details are not overwritten.']
        for heading, values in [('Patient', d['patient']), ('Primary owner', d['owner'])]:
            lines.append(heading)
            lines.extend(f'{labels[k]}: {v}' for k, v in values.items() if v is not None and v != '')
        return '\n'.join(lines)
    return 'Original approved ' + ('voice note' if item['kind'] == 'audio' else 'file') + ' copied with verified checksums. Original recorded at ' + d['recorded_at']


def dispatch(c, a, p, clinic, actor):
    from actions import require
    r = pending(c, require(p, 'id'), clinic)
    if r['status'] == 'accepted':
        return json.loads(r['result'])
    review, binaries = plan(c, r)
    if p.get('expected_digest') != review['digest']:
        fail('Review the current transfer preview before accepting; source or receiving records may have changed', 409)
    if review['counts']['changed'] and p.get('review_changes') is not True:
        fail('Explicitly acknowledge changed origin records; earlier copies and local edits will be retained', 409)
    baseline = review['baseline']
    reason = p.get('baseline_reason')
    if baseline:
        if p.get('establish_baseline') is not True:
            fail('Review the earlier receiving records and explicitly accept a new baseline; current source facts may duplicate earlier copies', 409)
        if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 1000:
            fail('Record a baseline review reason between 10 and 1000 characters', 422)
    elif p.get('establish_baseline') or reason:
        fail('This transfer no longer needs a baseline; reload its preview', 409)
    identity = next(x['payload'] for x in review['items'] if x['kind'] == 'identity')
    patient = review['destination_patient']
    if not patient:
        owner = record(c, 'owner', clinic, identity['owner'])
        patient = record(c, 'patient', clinic, {**identity['patient'], 'owner_id': owner['id'],
                         'external_id': 'transfer:' + r['source_clinic'] + ':' + r['patient_id'], 'transfer_request_id': r['id']})
        c.execute('INSERT INTO transferred_patients VALUES(?,?,?,?)', (r['source_clinic'], r['patient_id'], clinic, patient['id']))
    baseline_record = None
    if baseline:
        baseline_record = record(c, 'transfer_baseline', clinic, {
            'patient_id': patient['id'], 'source_clinic_id': r['source_clinic'], 'source_patient_id': r['patient_id'],
            'transfer_request_id': r['id'], 'mode': baseline['mode'], 'reason': reason.strip(),
            'reviewed_by': actor, 'reviewed_at': now(), 'reviewed_digest': review['digest'],
            'earlier_requests': baseline['earlier_requests'],
            'preserved_records': [{'id': x['id'], 'kind': x['kind'], 'version': x['version'], 'fingerprint': digest(x)}
                                  for x in [patient, review['destination_owner'], *baseline['existing_records']]],
            'current_origins': [{'kind': x['kind'], 'origin_id': x['origin_id'], 'fingerprint': x['fingerprint']} for x in review['items']]})
        text = ('Reviewed transfer baseline. Earlier source payloads are unknown. Current approved source facts were appended; '
                'they may duplicate earlier copies. No earlier records or local edits were overwritten or marked equivalent.\n'
                'Review reason: ' + reason.strip() + '\nReviewed by: ' + actor + '\nBaseline: ' + baseline_record['id'])
        db.event(c, clinic, patient['id'], 'clinical', 'Reviewed transfer baseline', text)
    copied = {'event': 0, 'file': 0, 'medication': 0, 'audio': 0, 'identity': 0}
    consultation = None
    for item in review['items']:
        if item['state'] == 'unchanged':
            continue
        d = item['payload']
        kind = item['kind']
        provenance = {'transfer_request_id': r['id'], 'origin_clinic_id': r['source_clinic'],
                      'origin_clinic_name': review['source_clinic']['name'], 'origin_patient_id': r['patient_id'],
                      'origin_id': item['origin_id'], 'origin_kind': kind, 'origin_revision': item['revision'],
                      'origin_fingerprint': item['fingerprint'], 'origin_recorded_at': d.get('occurred_at', d.get('recorded_at'))}
        if baseline_record:
            provenance['transfer_baseline_id'] = baseline_record['id']
        text = receipt_text(item)
        title = d.get('title') or d.get('name') or ('Patient and owner details' if kind == 'identity' else 'Voice note')
        title = ('Transferred medication history · ' if kind == 'medication' else 'Transferred ') + title + (f" · source revision {item['revision']}" if item['revision'] > 1 else '')
        source = record(c, 'source', clinic, {**provenance, 'patient_id': patient['id'], 'title': title,
                        'text': text, 'category': d.get('category', 'clinical'), 'section': 'Objective',
                        'author': 'Consented transfer from ' + review['source_clinic']['name']})
        target = source
        if kind == 'file':
            fid = uid()
            path = db.DATA / 'files' / fid
            db.transaction_file(c, path, binaries[(kind, item['origin_id'])][0])
            target = record(c, 'attachment', clinic, {**provenance, **fields(d, ('name', 'mime', 'size', 'sha256')),
                            'patient_id': patient['id'], 'consultation_id': '', 'approved': False, 'path': str(path)}, fid)
        elif kind == 'audio':
            if not consultation:
                consultation = record(c, 'consultation', clinic, {'patient_id': patient['id'], 'title': 'Transferred approved audio',
                                      'status': 'in_progress', 'template_id': 'soap-' + clinic, 'summary': [], 'source_ids': [],
                                      'input_revision': 0, 'generated_revision': 0, 'date': now()[:10], **provenance})
            rid = uid()
            target = record(c, 'recording', clinic, {**provenance, **fields(d, ('title', 'mime', 'duration', 'interrupted')),
                            'patient_id': patient['id'], 'consultation_id': consultation['id'], 'number': copied['audio'] + 1,
                            'device': 'Consented clinic transfer', 'status': 'saved', 'expected_chunks': len(d['manifest']),
                            'approved': False}, rid)
            for chunk, content in zip(d['manifest'], binaries[(kind, item['origin_id'])]):
                path = db.DATA / 'audio' / rid / str(chunk['index'])
                db.transaction_file(c, path, content)
                c.execute('INSERT INTO chunks VALUES(?,?,?,?)', (rid, chunk['index'], str(path), chunk['sha256']))
            source = db.update(c, source, {**source['data'], 'recording_id': rid})
            consultation = db.update(c, consultation, {**consultation['data'], 'source_ids': consultation['data']['source_ids'] + [source['id']]})
        elif kind == 'medication':
            target = record(c, 'medication_history', clinic, {**provenance, **d, 'patient_id': patient['id'],
                            'source_id': source['id'], 'externally_recorded': True})
        event = record(c, 'event', clinic, {**provenance, 'patient_id': patient['id'], 'category': d.get('category', 'clinical'),
                       'title': title, 'body': text, 'source_ids': [target['id'] if kind == 'file' else source['id']],
                       'occurred_at': d.get('occurred_at', d.get('recorded_at', now())), 'approved': False})
        if kind in ('event', 'identity'):
            target = event
        if kind == 'event':
            for o in d.get('observations', []):
                record(c, 'observation', clinic, {'patient_id': patient['id'], 'code': o['concept'], 'name': o['name'], 'value': o['value'],
                       'value_type': o['value_type'], 'unit': o['unit'], 'low': o.get('ref_low'), 'high': o.get('ref_high'),
                       'source_id': source['id'], 'category': d['category'], 'observed_at': d['occurred_at'], **provenance})
        c.execute('INSERT INTO transfer_revisions VALUES(?,?,?,?,?,?,?,?,?,?)', (r['source_clinic'], r['patient_id'], clinic,
                  kind, item['origin_id'], item['fingerprint'], item['revision'], target['id'], encoded(d), r['id']))
        copied[kind] += 1
    result = {'id': patient['id'], 'transfer_id': r['id'], 'transferred_events': copied['event'], 'files_copied': copied['file'],
              'audio_copied': copied['audio'], 'medication_histories': copied['medication'], 'counts': review['counts'],
              'consultation_id': consultation['id'] if consultation else None, 'reviewed_digest': review['digest'],
              'reviewed_by': actor, 'accepted_at': now(),
              'baseline_id': baseline_record['id'] if baseline_record else None}
    c.execute("UPDATE transfer_requests SET status='accepted',result=? WHERE id=?", (encoded(result), r['id']))
    return result


@router.get('/api/owner-account/transfer-clinics')
@router.get('/api/owner-account/pets/{patient_id}/transfer-clinics')
def account_clinics(request: Request, patient_id: str | None = None):
    from portal import saved_token
    return clinics(saved_token(request, patient_id))


@router.post('/api/owner-account/transfers')
@router.post('/api/owner-account/pets/{patient_id}/transfers')
def account_transfer(p: Consent, request: Request, patient_id: str | None = None):
    from portal import saved_token
    return request_transfer(saved_token(request, patient_id), p)


@router.get('/api/owner-account/transfers')
@router.get('/api/owner-account/pets/{patient_id}/transfers')
def account_requests(request: Request, patient_id: str | None = None):
    from portal import saved_token
    return owner_requests(saved_token(request, patient_id))


@router.delete('/api/owner-account/transfers/{id}')
@router.delete('/api/owner-account/pets/{patient_id}/transfers/{id}')
def account_revoke(id: str, request: Request, patient_id: str | None = None):
    from portal import saved_token
    return revoke_transfer(saved_token(request, patient_id), id)
