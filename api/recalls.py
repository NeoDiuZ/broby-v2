"""Reviewed, bounded recall campaigns. Preparation never performs outbound I/O."""
import hashlib
import json
from datetime import date
from fastapi import APIRouter, Request
from db import all_records, connection, get, now, record, update

router = APIRouter()
PERMISSIONS = {name: {'vet', 'nurse', 'admin'} for name in (
    'recall.prepare', 'recall.cancel', 'owner.recall_preference')}


def text(value, label, maximum=160):
    from actions import fail
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= maximum:
        fail(f'{label} must contain 3–{maximum} characters')
    return value.strip()


def contact(owner):
    return {key: owner['data'].get(key, '') for key in ('name', 'phone', 'email')}


def draft_snapshot(reminder, patient, owner):
    return {'reminder': {k: reminder['data'][k] for k in ('patient_id', 'title', 'due')},
            'patient_name': patient['data']['name'], 'owner_id': owner['id'], 'contact': contact(owner)}


def eligibility(c, reminder):
    clinic, d = reminder['clinic_id'], reminder['data']
    patient = get(c, d.get('patient_id'), clinic)
    owner = get(c, patient['data'].get('owner_id'), clinic) if patient else None
    reason = ''
    if d.get('status') != 'due': reason = 'Reminder closed'
    elif not patient or not owner or owner['data'].get('merged_into'): reason = 'Patient or active primary owner unavailable'
    elif owner['data'].get('recall_opt_out'): reason = 'Owner opted out of recalls'
    elif d.get('outbox_id'): reason = 'A draft already exists; review its history before preparing another reminder'
    return patient, owner, reason


def queue_one(c, reminder, clinic, actor, campaign_id=None):
    from actions import dispatch, fail
    patient, owner, reason = eligibility(c, reminder)
    if reason: fail(reason, 409)
    d = reminder['data']
    body = f"Reminder for {patient['data']['name']}: {d['title']}, due {d['due']}. Please contact your clinic to arrange this."
    out = dispatch(c, 'message.queue', {'patient_id': patient['id'], 'body': body}, clinic, actor)
    out = update(c, out, {**out['data'], 'reminder_id': reminder['id'],
                         'recall_snapshot': draft_snapshot(reminder, patient, owner), 'campaign_id': campaign_id})
    update(c, reminder, {**d, 'outbox_id': out['id']})
    return out


def validate_draft(c, out):
    """Used before editing, opening a contact link or recording manual delivery."""
    from actions import fail
    if not out['data'].get('reminder_id'): return
    r = get(c, out['data']['reminder_id'], out['clinic_id'])
    if not r or r['data'].get('status') != 'due' or r['data'].get('outbox_id') != out['id']:
        fail('This reminder changed or closed. Cancel this draft and review the reminder.', 409)
    patient = get(c, r['data']['patient_id'], out['clinic_id'])
    owner = get(c, patient['data'].get('owner_id'), out['clinic_id']) if patient else None
    if not owner or owner['data'].get('merged_into') or owner['id'] != out['data']['owner_id'] or owner['data'].get('recall_opt_out'):
        fail('Recall recipient changed or opted out. Cancel this draft and review the owner.', 409)
    saved = out['data'].get('recall_snapshot')
    # Old drafts have no contact snapshot: require a fresh review through a new reminder.
    if not saved or saved != draft_snapshot(r, patient, owner):
        fail('Reminder or contact details changed. Cancel this draft and review the reminder.', 409)


def preview(c, clinic, p):
    from actions import fail
    from clinic_workflows import calendar_date
    start, end = calendar_date(p.get('start')), calendar_date(p.get('end'))
    if start > end or (date.fromisoformat(end)-date.fromisoformat(start)).days > 365:
        fail('Choose an inclusive period of at most 366 days')
    query = p.get('query', '')
    if not isinstance(query, str) or len(query) > 120: fail('Use a reminder search of at most 120 characters')
    query = query.strip()
    matches = sorted((r for r in all_records(c, clinic, 'reminder')
                      if start <= r['data']['due'] <= end and query.casefold() in r['data']['title'].casefold()),
                     key=lambda r: (r['data']['due'], r['id']))
    if len(matches) > 100: fail('More than 100 reminders match. Narrow the dates or reminder search before reviewing.')
    items = []
    for r in matches:
        patient, owner, reason = eligibility(c, r)
        items.append({'reminder_id': r['id'], 'reminder_version': r['version'], 'title': r['data']['title'],
                      'due': r['data']['due'], 'patient_id': r['data']['patient_id'],
                      'patient_name': patient['data']['name'] if patient else 'Unavailable',
                      'owner_id': owner['id'] if owner else None, 'contact': contact(owner) if owner else {},
                      'patient_version': patient['version'] if patient else None,
                      'owner_version': owner['version'] if owner else None, 'blocked_reason': reason})
    result = {'clinic_id': clinic, 'start': start, 'end': end, 'query': query, 'items': items}
    result['digest'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def progress(c, campaign):
    items = []
    for original in campaign['data']['items']:
        item = dict(original)
        out = get(c, item.get('outbox_id'), campaign['clinic_id'])
        if item.get('outbox_id'):
            item['status'] = out['data']['status'] if out else 'missing'
            item['blocked_reason'] = ''
            if out and item['status'] == 'pending':
                from fastapi import HTTPException
                try: validate_draft(c, out)
                except HTTPException as error: item['blocked_reason'] = error.detail
        items.append(item)
    counts = {}
    for item in items:
        state = 'needs_review' if item.get('outbox_id') and item.get('blocked_reason') else item['status']
        counts[state] = counts.get(state, 0) + 1
    return {**campaign, 'items': items, 'counts': counts}


@router.post('/api/recalls/preview')
def preview_route(request: Request, payload: dict):
    from main import identity
    from actions import authorize
    clinic, actor = identity(request)
    with connection() as c:
        authorize(c, clinic, actor, 'recall.prepare')
        return preview(c, clinic, payload)


@router.get('/api/recalls/{campaign_id}')
def progress_route(campaign_id: str, request: Request):
    from main import identity
    from actions import owned
    clinic, _ = identity(request)
    with connection() as c: return progress(c, owned(c, campaign_id, clinic, 'recall_campaign'))


@router.get('/api/outbox/{outbox_id}/delivery-review')
def delivery_review(outbox_id: str, request: Request):
    from main import identity
    from actions import owned, authorize, fail
    clinic, actor = identity(request)
    with connection() as c:
        authorize(c, clinic, actor, 'message.complete')
        out = owned(c, outbox_id, clinic, 'outbox')
        if out['data']['status'] != 'pending': fail('Only pending drafts can be delivered', 409)
        validate_draft(c, out)
        owner = owned(c, out['data']['owner_id'], clinic, 'owner')
        return {'body': out['data']['body'], 'contact': contact(owner), 'version': out['version']}


def dispatch(c, action, p, clinic, actor):
    from actions import fail, owned, version
    if action == 'owner.recall_preference':
        owner = owned(c, p.get('id'), clinic, 'owner'); version(owner, p)
        if owner['data'].get('merged_into'): fail('Select an active owner')
        if type(p.get('opt_out')) is not bool: fail('Choose whether the owner opts out of recalls')
        reason = text(p.get('reason'), 'Preference reason', 500)
        cancelled = []
        if p['opt_out']:
            for out in all_records(c, clinic, 'outbox'):
                if out['data'].get('reminder_id') and out['data']['owner_id'] == owner['id'] and out['data']['status'] == 'pending':
                    update(c, out, {**out['data'], 'status': 'cancelled', 'cancel_reason': 'Owner opted out of recalls', 'cancelled_at': now()})
                    cancelled.append(out['id'])
        history = [*owner['data'].get('recall_preferences', []), {'opt_out': p['opt_out'], 'reason': reason, 'actor': actor, 'at': now(), 'cancelled_draft_ids': cancelled}]
        return update(c, owner, {**owner['data'], 'recall_opt_out': p['opt_out'], 'recall_preferences': history})
    if action == 'recall.prepare':
        title = text(p.get('title'), 'Campaign name')
        review = preview(c, clinic, p)
        if review['digest'] != p.get('digest'): fail('Reminders or recipients changed. Preview and review this campaign again.', 409)
        ids = p.get('reminder_ids')
        eligible = {x['reminder_id'] for x in review['items'] if not x['blocked_reason']}
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)) or not set(ids).issubset(eligible):
            fail('Select at least one eligible reminder from this review')
        campaign = record(c, 'recall_campaign', clinic, {'title': title, 'status': 'prepared', 'review': review,
                          'items': [], 'prepared_by': actor, 'prepared_at': now(), 'delivery': 'manual'})
        items = []
        for item in review['items']:
            out = queue_one(c, owned(c, item['reminder_id'], clinic, 'reminder'), clinic, actor, campaign['id']) if item['reminder_id'] in ids else None
            items.append({**item, 'outbox_id': out['id'] if out else None,
                          'status': 'pending' if out else 'skipped' if item['blocked_reason'] else 'excluded'})
        return update(c, campaign, {**campaign['data'], 'items': items})
    campaign = owned(c, p.get('id'), clinic, 'recall_campaign'); version(campaign, p)
    if campaign['data']['status'] != 'prepared': fail('This campaign is already cancelled', 409)
    reason = text(p.get('reason'), 'Cancellation reason', 500)
    for item in campaign['data']['items']:
        out = get(c, item.get('outbox_id'), clinic)
        if out and out['data']['status'] == 'pending':
            update(c, out, {**out['data'], 'status': 'cancelled', 'cancel_reason': reason, 'cancelled_at': now()})
    return update(c, campaign, {**campaign['data'], 'status': 'cancelled', 'cancel_reason': reason,
                               'cancelled_by': actor, 'cancelled_at': now()})
