"""Clinic workflow completion. Mutations run inside the shared action transaction."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

from db import all_records, connection, get, now, record, uid, update

PERMISSIONS = {
    'patient.owners': {'vet', 'nurse', 'admin'},
    'recording.rename': {'vet', 'nurse', 'admin'},
    'source.speakers': {'vet', 'nurse', 'admin'},
    'reminder.update': {'vet', 'nurse', 'admin'},
    'reminder.cancel': {'vet', 'nurse', 'admin'},
    'automation.save': {'admin'},
    'handover.prepare': {'vet', 'nurse', 'admin'},
    'handover.acknowledge': {'vet', 'nurse', 'admin'},
    'discharge.queue': {'vet', 'admin'},
}


def clinic_today(c, clinic, instant=None):
    practice = get(c, clinic, clinic)
    tz = ZoneInfo(practice['data'].get('timezone', 'Asia/Singapore'))
    return (instant or datetime.now(timezone.utc)).astimezone(tz)


def calendar_date(value, label='Date', *, latest=None, optional=False):
    from actions import fail
    if optional and value in (None, ''):
        return None
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        parsed = date.fromisoformat(value)
        if latest and parsed > latest:
            fail(f'{label} cannot be in the future')
        return parsed.isoformat()
    except (ValueError, TypeError):
        fail(f'{label} must be a valid calendar date')


def owner_ids(patient):
    d = patient['data']
    return list(dict.fromkeys([x for x in [d.get('owner_id'), *d.get('additional_owner_ids', [])] if x]))


def revoke_patient_access(c, clinic, patient_id):
    # An old household link must not silently follow an ownership transfer.
    c.execute('UPDATE grants SET revoked=1 WHERE clinic_id=? AND patient_id=?', (clinic, patient_id))


def cancel_reminder_draft(c, reminder):
    out = get(c, reminder['data'].get('outbox_id'), reminder['clinic_id'])
    if out and out['data']['status'] in ('pending', 'failed'):
        update(c, out, {**out['data'], 'status': 'cancelled', 'cancel_reason': 'Reminder changed or closed'})


def queue_due(c, clinic, actor, instant=None):
    from actions import owned
    from recalls import eligibility, queue_one
    settings = owned(c, 'settings-' + clinic, clinic, 'settings')['data']
    cutoff = (clinic_today(c, clinic, instant).date() + timedelta(days=settings.get('reminder_days', 7))).isoformat()
    created = []
    for r in all_records(c, clinic, 'reminder'):
        d = r['data']
        if d['status'] != 'due' or d['due'] > cutoff or d.get('outbox_id'):
            continue
        if eligibility(c, r)[2]: continue
        out = queue_one(c, r, clinic, actor)
        created.append(out['id'])
    return {'id': uid(), 'count': len(created)}


def prepare_handover(c, clinic, instant=None):
    from reads import handover
    day = clinic_today(c, clinic, instant).date().isoformat()
    id = 'handover:' + clinic + ':' + day
    existing = get(c, id, clinic)
    if existing:
        return existing
    snapshot = handover(c, clinic, instant=instant)
    patients={r['id']:r['data']['name'] for r in all_records(c,clinic,'patient')}
    for section,items in list(snapshot.items()):
        if isinstance(items,list):
            snapshot[section]=[{**r,'data':{**r['data'],'patient_name':patients.get(r['data'].get('patient_id'),'')}} for r in items]
    return record(c, 'handover', clinic, {'date': day, 'title': 'Morning handover · ' + day,
                  'snapshot': snapshot, 'acknowledged_by': [], 'prepared_at': now()}, id)


def dispatch(c, action, p, clinic, actor):
    from actions import owned, require, version, fail, dispatch as base
    if action == 'patient.owners':
        r = owned(c, p['id'], clinic, 'patient'); version(r, p)
        primary = require(p, 'owner_id')
        extra = p.get('additional_owner_ids', [])
        if not isinstance(extra, list) or len(extra) > 20 or any(not isinstance(x, str) for x in extra):
            fail('Choose up to 20 additional owners')
        ids = list(dict.fromkeys([primary, *extra]))
        for id in ids:
            if owned(c, id, clinic, 'owner')['data'].get('merged_into'):
                fail('Select an active owner')
        if set(owner_ids(r)) != set(ids) or primary != r['data'].get('owner_id'):
            revoke_patient_access(c, clinic, r['id'])
        return update(c, r, {**r['data'], 'owner_id': primary, 'additional_owner_ids': [x for x in ids if x != primary]})
    if action == 'recording.rename':
        r = owned(c, p['id'], clinic, 'recording'); version(r, p)
        title = require(p, 'title')
        if not isinstance(title, str) or len(title) > 160: fail('Use a title of at most 160 characters')
        return update(c, r, {**r['data'], 'title': title})
    if action == 'source.speakers':
        r = owned(c, p['id'], clinic, 'source'); version(r, p)
        known = {str(u['speaker']) for u in r['data'].get('utterances', []) if u.get('speaker') is not None}
        labels = p.get('speaker_labels')
        if not known or not isinstance(labels, dict) or not set(labels).issubset(known):
            fail('Labels must refer to the speakers in this transcript')
        if any(not isinstance(v, str) or not v.strip() or len(v) > 80 for v in labels.values()):
            fail('Speaker labels must contain 1–80 characters')
        return update(c, r, {**r['data'], 'speaker_labels': {k: v.strip() for k, v in labels.items()}, 'speakers_reviewed_by': actor})
    if action in ('reminder.update', 'reminder.cancel'):
        r = owned(c, p['id'], clinic, 'reminder'); version(r, p)
        if r['data']['status'] != 'due': fail('This reminder is already closed', 409)
        cancel_reminder_draft(c, r)
        d = {**r['data']}
        if action == 'reminder.cancel': d['status'] = 'cancelled'
        else:
            d.update(title=require(p, 'title'), due=calendar_date(require(p, 'due'), 'Due date'))
            d.pop('outbox_id', None)
        return update(c, r, d)
    if action == 'automation.save':
        r = owned(c, 'settings-' + clinic, clinic, 'settings'); version(r, p)
        for key in ('auto_reminders', 'auto_handover'):
            if type(p.get(key)) is not bool: fail('Automation settings must be true or false')
        at = p.get('handover_at', '07:00')
        if not isinstance(at, str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', at): fail('Choose a valid handover time')
        return update(c, r, {**r['data'], 'auto_reminders': p['auto_reminders'], 'auto_handover': p['auto_handover'], 'handover_at': at, 'automation_actor': actor})
    if action == 'handover.prepare':
        instant = clinic_today(c, clinic)
        if p.get('expected_date') is not None and p['expected_date'] != instant.date().isoformat():
            fail('The clinic date changed after this review. Prepare a new handover proposal.', 409)
        return prepare_handover(c, clinic, instant)
    if action == 'handover.acknowledge':
        r = owned(c, p['id'], clinic, 'handover')
        acknowledgements = r['data'].get('acknowledged_by', [])
        if any(x['actor_id'] == actor for x in acknowledgements): return r
        return update(c, r, {**r['data'], 'acknowledged_by': [*acknowledgements, {'actor_id': actor, 'at': now()}]})
    if action == 'discharge.queue':
        from portal import view
        from actions import authorize
        authorize(c, clinic, actor, 'share.create'); authorize(c, clinic, actor, 'message.queue')
        patient = owned(c, require(p, 'patient_id'), clinic, 'patient')
        link = base(c, 'share.create', {'patient_id': patient['id']}, clinic, actor)
        g = c.execute('SELECT * FROM grants WHERE token=?', (link['id'],)).fetchone()
        data = view(c, g)
        # Compose from approved data server-side; never copy private source notes.
        body = f"{patient['data']['name']} — approved care information\n\n"
        body += '\n\n'.join(e['data']['title'] + '\n' + e['data']['body'] for e in data['events'][:5])
        body += '\n\n' + '\n'.join(f"{m['data']['name']}: {m['data']['dose']} · {m['data']['frequency']}. {m['data']['instructions']}" for m in data['medications'])
        body += '\n\n' + '\n'.join(f"Due {r['data']['due']}: {r['data']['title']}" for r in data['reminders'] if r['data']['status'] == 'due')
        import runtime
        origin = sorted(runtime.allowed_origins())[0]
        body += '\n\nApproved documents, audio and printable care information: ' + origin + link['url']
        out = base(c, 'message.queue', {'patient_id': patient['id'], 'body': body.strip()}, clinic, actor)
        return update(c, out, {**out['data'], 'grant_token': link['id'], 'share_url': link['url']})
    fail('Unknown workflow action', 404)


def tick(instant=None):
    """One transaction serializes schedules across retries/restarts. No outbound I/O."""
    from actions import authorize
    from fastapi import HTTPException
    with connection(True) as c:
        clinics = [r[0] for r in c.execute("SELECT id FROM records WHERE kind='clinic'")]
        for clinic in clinics:
            settings = get(c, 'settings-' + clinic, clinic)
            if not settings: continue
            d = settings['data']; actor = d.get('automation_actor')
            if not actor: continue
            try:
                authorize(c, clinic, actor, 'automation.save')
                if d.get('auto_reminders'):
                    authorize(c, clinic, actor, 'reminder.queue_due'); authorize(c, clinic, actor, 'message.queue')
                    result = queue_due(c, clinic, actor, instant)
                    if result['count']:
                        c.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (uid(), clinic, actor, 'reminder.schedule', result['id'], now()))
                local = clinic_today(c, clinic, instant)
                if d.get('auto_handover') and local.strftime('%H:%M') >= d.get('handover_at', '07:00'):
                    authorize(c, clinic, actor, 'handover.prepare')
                    prepare_handover(c, clinic, instant)
            except HTTPException:
                # Revoked/inactive scheduler membership disables its work.
                continue
