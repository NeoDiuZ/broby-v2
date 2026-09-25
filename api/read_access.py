"""Read capabilities share clinic/master policy with writes; no UI-only restrictions.

Mixed histories, assistant conversations, archives and sources may contain copied
facts from any area. They require the full set rather than attempting text redaction.
New routes and unclassified record kinds fail closed for restricted members.
"""
from fastapi import Request
from db import connection, get

READS = {
    'read.patients': 'Patients and owner contacts',
    'read.clinical': 'Clinical notes, measurements, files and audio',
    'read.billing': 'Invoices, payments and credits',
    'read.inventory': 'Inventory and purchasing',
    'read.schedule': 'Appointments and staff rota',
    'read.messages': 'Messages, recalls and owner submissions',
    'read.staff': 'Other staff memberships',
    'read.reports': 'Combined reports and saved views',
}
ALL = frozenset(READS)
PATIENT = frozenset({'read.patients'})
CLINICAL = PATIENT | {'read.clinical'}
BILLING = PATIENT | {'read.billing'}
SCHEDULE = PATIENT | {'read.schedule', 'read.staff'}
MESSAGES = PATIENT | {'read.messages'}
INVENTORY = frozenset({'read.inventory'})

KINDS = {
    'clinic': frozenset(), 'settings': frozenset(),
    'patient': PATIENT, 'owner': PATIENT,
    'consultation': CLINICAL, 'observation': CLINICAL, 'template': CLINICAL,
    'ontology_proposal': CLINICAL,
    # Receipts, files, event bodies and medication records can embed facts from
    # other modules. No unstructured payload is declared safe by its title alone.
    **{k: ALL for k in ('source','event','attachment','recording','medication','medication_history','handover','dashboard','transfer_import')},
    **{k: BILLING for k in ('invoice','payment','refund','invoice_void','credit_note','credit_note_reversal','stripe_checkout','stripe_refund','test_payment')},
    **{k: INVENTORY for k in ('inventory','stock_lot','stock_movement','purchase_order')},
    'appointment': SCHEDULE, 'schedule': SCHEDULE, 'staff_leave': SCHEDULE,
    **{k: MESSAGES for k in ('reminder','outbox','recall_campaign','test_message','twilio_attempt','twilio_inbound','escalation','intake')},
    'member': frozenset({'read.staff'}),
    'organization_adoption': ALL,
}

def allowed_reads(c, clinic, actor):
    from actions import owned
    from organizations import policy, master, blocked
    member = owned(c, actor, clinic, 'member')['data']
    if not member.get('active'): return set()
    org = policy(c, clinic)
    if org and master(c, org, actor): return set(ALL)
    locks = set(member.get('read_restrictions', [])) | blocked(c, clinic, actor)
    if member['role'] != 'admin':
        locks |= set(owned(c, clinic, clinic, 'clinic')['data'].get('locked_features', []))
    return set(ALL - locks)

def require(c, clinic, actor, capabilities):
    from actions import fail
    if not set(capabilities) <= allowed_reads(c, clinic, actor):
        fail('Your clinic read permissions do not allow this view. Mixed histories, files, assistant conversations and full exports require access to every record area.', 403)

def requirements(record):
    return KINDS.get(record['kind'], ALL)

def visible(record, capabilities, actor):
    return record['id'] == actor and record['kind'] == 'member' or requirements(record) <= capabilities

def filter_records(records, capabilities, actor):
    return [r for r in records if visible(r, capabilities, actor)]

def action_reads(action):
    """Write responses and mutation-key replay must not return restricted facts."""
    prefix = action.split('.')[0]
    if action.startswith('organization.join_') or action=='organization.join_review': return ALL
    if prefix in ('organization','feature_locks','settings'): return frozenset()
    if prefix in ('member','access'): return frozenset({'read.staff'})
    if prefix in ('patient','owner'): return PATIENT
    if prefix in ('invoice','payment','credit_note','stripe'): return BILLING
    if prefix in ('appointment','schedule','leave'): return SCHEDULE
    if prefix in ('inventory','purchase_order'): return INVENTORY
    if prefix in ('message','recall','reminder'): return MESSAGES
    if prefix == 'test':
        return BILLING if action.startswith('test.payment.') else MESSAGES if action.startswith('test.message.') else ALL
    # The remaining actions ingest, disclose or return composite patient facts.
    return ALL

# Every staff API route must be deliberately classified. Public owner/provider
# routes use their own capabilities/signatures and are listed by router below.
ROUTES = {
    '/api/bootstrap': frozenset(), '/api/actions': frozenset(),
    '/api/actions/catalog': frozenset(), '/api/organization': frozenset(),
    '/api/access': frozenset(),
    '/api/marketing/leads': ALL,
    '/api/marketing/leads/{lead_id}/contacted': ALL,
    '/api/account/invitations': frozenset({'read.staff'}),
    '/api/account/mfa/setup': frozenset(), '/api/account/mfa/confirm': frozenset(), '/api/account/password': frozenset(),
    '/api/patients': PATIENT, '/api/v2/patients': PATIENT, '/api/v2/patients/{id}': PATIENT,
    '/api/patients/{id}/observations': CLINICAL,
    '/api/v2/patients/{id}/observations': CLINICAL,
    '/api/v2/patients/{id}/concepts': CLINICAL, '/api/ontology': CLINICAL,
    '/api/invoices/{id}/pdf': BILLING, '/api/credit-notes/{id}/pdf': BILLING,
    '/api/credit-notes/export': BILLING,
    '/api/reports/financial': BILLING, '/api/reports/financial/export': BILLING,
    '/api/reports/operations': ALL, '/api/reports/operations/export': ALL,
    '/api/integrations/stripe/status': BILLING,
    '/api/schedule/preview': SCHEDULE, '/api/schedule/rota': SCHEDULE, '/api/schedule/leave/preview': SCHEDULE,
    '/api/recalls/preview': MESSAGES, '/api/recalls/{campaign_id}': MESSAGES,
    '/api/outbox/{outbox_id}/delivery-review': MESSAGES,
    '/api/integrations/twilio/status': MESSAGES,
    **{path: ALL for path in (
        '/api/jobs/{job_id}', '/api/uploads', '/api/files/{id}',
        '/api/recordings/{id}/chunks/{index}', '/api/recordings/{id}/manifest', '/api/recordings/{id}/audio',
        '/api/audit', '/api/import/preview', '/api/export', '/api/backup', '/api/assistant', '/api/handover',
        '/api/patients/{id}/timeline', '/api/records/{id}/history', '/api/dashboards/{id}',
        '/api/operations/status', '/api/operations/health', '/api/consultations/{id}/pdf',
        '/api/v2/overview', '/api/v2/patients/{id}/timeline', '/api/v2/patients/{id}/events/{event_id}',
        '/api/v2/sources/{id}', '/api/v2/ingest/lab', '/api/v2/events',
        '/api/integrations/test/key', '/api/integrations/test/key/{id}',
        '/api/transfers/incoming', '/api/transfers/{id}/preview',
        '/api/assistant/conversations', '/api/assistant/conversations/{id}',
        '/api/assistant/conversations/{id}/turns/{turn_id}/confirm',
        '/api/organization/join-preview', '/api/organization/adoptions', '/api/organization/adoption-preview',
        '/api/owner-conversations/{id}',
    )},
}
PUBLIC = {
    '/api/health', '/api/ready', '/api/session', '/api/login', '/api/logout',
    '/api/marketing/leads/submit',
    '/api/account/invitations/accept', '/api/integrations/test/events',
    '/api/integrations/stripe/webhook', '/api/integrations/twilio/status/{attempt_id}', '/api/integrations/twilio/inbound',
}

def external(path):
    return path in PUBLIC or path.startswith(('/api/owner/', '/api/owner-account'))

def route_policy(path):
    return frozenset() if external(path) else ROUTES.get(path)

def enforce_route(request: Request):
    from actions import fail
    path = request.scope['route'].path
    if external(path): return
    capabilities = route_policy(path)
    if capabilities is None: fail('This endpoint has no access policy', 503)
    from main import identity
    clinic, actor = identity(request)
    with connection() as c: require(c, clinic, actor, capabilities)
