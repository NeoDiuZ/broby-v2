"""Strict proposals for routine workflows. Validation never executes a mutation.

Binary capture, provider dispatch and cross-clinic migration retain dedicated
review screens. These are explicit routing decisions, not untyped AI payloads.
"""
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StrictBool, StrictFloat, StrictInt, create_model, model_validator
from assistant_operations import Payload, Target, Versioned, Identifier, Text
from record_queries import RecordQuery


def calendar(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('Use a calendar date in YYYY-MM-DD form')
    return value


Day = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$'), AfterValidator(calendar)]
Time = Annotated[str, Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
Short = Annotated[str, Field(max_length=300)]
Long = Annotated[str, Field(min_length=1, max_length=20000)]
Cents = Annotated[int, Field(ge=0, le=1000000000)]
Quantity = Annotated[int, Field(ge=1, le=1000000)]
Finite = Annotated[StrictFloat | StrictInt, Field(allow_inf_nan=False)]
IDs = Annotated[list[Identifier], Field(max_length=100)]


def schema(model_name, base=Payload, **fields):
    """Typed fields remain explicit; this only removes repetitive class boilerplate."""
    return create_model(model_name, __base__=base, **fields)


class PatientCreate(Payload):
    name: Text
    species: Text
    owner_id: Identifier | None = None
    owner_name: Text | None = None
    owner_email: Short = ''
    owner_phone: Short = ''
    breed: Short = ''
    sex: Short = 'Unknown'
    weight: Annotated[Finite, Field(ge=0)] = 0
    age: Short = ''
    date_of_birth: Day | None = None
    external_id: Short = ''

    @model_validator(mode='after')
    def one_owner(self):
        if bool(self.owner_id) == bool(self.owner_name):
            raise ValueError('Select an existing owner or provide a new owner name, not both')
        if self.owner_id and (self.owner_email or self.owner_phone):
            raise ValueError('Edit the existing owner separately to change contact details')
        return self


PatientUpdate = schema('PatientUpdate', Versioned, **{
    key: (typ, None) for key, typ in {
        'name': Text, 'species': Text, 'breed': Short, 'sex': Short,
        'weight': Annotated[Finite, Field(ge=0)], 'age': Short,
        'date_of_birth': Day | None, 'owner_id': Identifier,
    }.items()
})
OwnerCreate = schema('OwnerCreate', name=(Text, ...), email=(Short, ''), phone=(Short, ''))
# All three fields are required on replacement: do not silently erase contacts.
OwnerUpdate = schema('OwnerUpdate', Versioned, name=(Text, ...), email=(Short, ...), phone=(Short, ...))
Reasoned = schema('Reasoned', Versioned, reason=(Text, ...))
Approval = schema('Approval', Versioned, approved=(bool, ...))
PatientTarget = schema('PatientTarget', patient_id=(Identifier, ...))
ConsultationCreate = schema('ConsultationCreate', patient_id=(Identifier, ...), title=(Text, 'Consultation'), template_id=(Identifier, None))
SourceAdd = schema('SourceAdd', patient_id=(Identifier, ...), text=(Long, ...), title=(Text, 'Veterinarian note'),
                   consultation_id=(Identifier, None), category=(Short, 'clinical'), section=(Text, 'Subjective'))
Observation = schema('Observation', patient_id=(Identifier, ...), source_id=(Identifier, ...),
                     name=(Text, ...), value=(Finite, ...), unit=(Text, ...),
                     low=(Finite | None, None), high=(Finite | None, None), category=(Text, 'Vitals'))
TypedObservation = schema('TypedObservation', patient_id=(Identifier, ...), source_id=(Identifier, ...),
                          code=(Identifier, ...), value=(StrictBool | Finite | Text, ...),
                          low=(Finite | None, None), high=(Finite | None, None))


class Section(Payload):
    name: Text
    text: Long
    source_ids: IDs


SummarySave = schema('SummarySave', Versioned, summary=(Annotated[list[Section], Field(min_length=1, max_length=50)], ...))
SummaryGenerate = schema('SummaryGenerate', Versioned, template_id=(Identifier, None), mode=(Literal['verbatim', 'ai'], ...))
AppointmentCreate = schema('AppointmentCreate', patient_id=(Identifier, ...), date=(Day, ...), time=(Time, ...),
                           duration=(Annotated[int, Field(ge=5, le=1440)], ...), clinician=(Identifier, ...), reason=(Text, ...), room=(Short, ''))
AppointmentSeries = schema('AppointmentSeries', AppointmentCreate, count=(Annotated[int, Field(ge=1, le=52)], ...), interval_days=(Annotated[int, Field(ge=1, le=366)], ...))
AppointmentMove = schema('AppointmentMove', Versioned, date=(Day, ...), time=(Time, ...),
                         duration=(Annotated[int, Field(ge=5, le=1440)], None), clinician=(Identifier, None), reason=(Text, None), room=(Short, None))
AppointmentStatus = schema('AppointmentStatus', Versioned, status=(Literal['scheduled', 'arrived', 'completed', 'cancelled'], ...))


class InvoiceLine(Payload):
    name: Text
    quantity: Quantity
    price_cents: Cents


InvoiceCreate = schema('InvoiceCreate', patient_id=(Identifier, ...), items=(Annotated[list[InvoiceLine], Field(min_length=1, max_length=100)], ...),
                       discount_cents=(Cents, ...), tax_bps=(Annotated[int, Field(ge=0, le=10000)], ...))
PaymentRecord = schema('PaymentRecord', Versioned, amount_cents=(Annotated[int, Field(ge=1, le=1000000000)], ...),
                       method=(Literal['cash', 'card_external', 'bank_external'], ...), reference=(Short, ''))
Refund = schema('Refund', Reasoned, amount_cents=(Annotated[int, Field(ge=1, le=1000000000)], ...))
InventoryCreate = schema('InventoryCreate', name=(Text, ...), unit=(Text, ...), stock=(Cents, ...), reorder=(Cents, ...), price_cents=(Cents, ...))
InventoryAdjust = schema('InventoryAdjust', Reasoned, stock=(Cents, ...))
InventoryReceive = schema('InventoryReceive', Versioned, quantity=(Quantity, ...), batch=(Text, ...), supplier=(Text, ...), expiry=(Day, None), purchase_order_id=(Identifier, None))
Dispense = schema('Dispense', patient_id=(Identifier, ...), inventory_id=(Identifier, ...), version=(Annotated[int, Field(ge=1)], ...),
                  quantity=(Quantity, ...), dose=(Text, ...), frequency=(Text, ...), instructions=(Long, ...))
TemplateSave = schema('TemplateSave', name=(Text, ...), description=(Short, ''), sections=(Annotated[list[Text], Field(min_length=1, max_length=50)], ...), id=(Identifier, None), version=(Annotated[int, Field(ge=1)], None))
MessageQueue = schema('MessageQueue', patient_id=(Identifier, ...), body=(Long, ...))
MessageUpdate = schema('MessageUpdate', Versioned, body=(Long, ...))
Transcribe = schema('Transcribe', Target, language=(Literal['multi', 'en', 'zh', 'ms'], ...), diarize=(bool, ...))
IntakeAccept = schema('IntakeAccept', Versioned, consultation_id=(Identifier, None))
SettingsSave = schema('SettingsSave', version=(Annotated[int, Field(ge=1)], ...), retention=(Literal['medical', 'medical_context'], ...),
                      language=(Literal['en', 'zh', 'ms', 'multi'], ...), emergency_phone=(Short, ...), reminder_days=(Annotated[int, Field(ge=0, le=365)], ...))
MemberSave = schema('MemberSave', name=(Text, ...), role=(Literal['vet', 'nurse', 'admin'], ...), active=(bool, ...), id=(Identifier, None), version=(Annotated[int, Field(ge=1)], None))
FeatureLocks = schema('FeatureLocks', version=(Annotated[int, Field(ge=1)], ...), actions=(Annotated[list[Identifier], Field(max_length=200)], ...))
OntologySave = schema('OntologySave', code=(Identifier, ...), name=(Text, ...), value_type=(Literal['number', 'text', 'boolean'], ...), unit=(Short, ...), category=(Text, ...))
LabImport = schema('LabImport', patient_id=(Identifier, ...), title=(Text, ...), csv=(Annotated[str, Field(min_length=1, max_length=1000000)], ...))
Speakers = schema('Speakers', Versioned, speaker_labels=(dict[Identifier, Annotated[str, Field(min_length=1, max_length=80)]], ...))
Automation = schema('Automation', version=(Annotated[int, Field(ge=1)], ...), auto_reminders=(bool, ...), auto_handover=(bool, ...), handover_at=(Time, ...))
DashboardSave = schema('DashboardSave', name=(Text, ...), query=(RecordQuery, ...), id=(Identifier, None), version=(Annotated[int, Field(ge=1)], None))
RecallPreference = schema('RecallPreference', Reasoned, opt_out=(bool, ...))
LeaveRequest = schema('LeaveRequest', member_id=(Identifier, ...), start=(Day, ...), end=(Day, ...), reason=(Annotated[str, Field(min_length=3, max_length=500)], ...))
LeaveReview = schema('LeaveReview', Reasoned, decision=(Literal['approved', 'rejected'], ...))


# schema, primary record kind (if id is present), description/effect
SPECS = {
    'patient.create': (PatientCreate, None, 'Create a patient with an existing owner or an explicitly named new owner. Never infer clinical facts.'),
    'patient.update': (PatientUpdate, 'patient', 'Change only supplied patient fields. Changing the primary owner revokes existing owner access links.'),
    'owner.create': (OwnerCreate, None, 'Create an owner record. No invitation or message is sent.'),
    'owner.update': (OwnerUpdate, 'owner', 'Replace name and contact fields. Preserve current contacts unless an explicit change or removal was requested.'),
    'owner.merge': (schema('OwnerMerge', Versioned, target_id=(Identifier, ...)), 'owner', 'Merge source owner into target owner, move patient links and preserve recall opt-outs. Existing clinical history is retained.'),
    'consultation.create': (ConsultationCreate, None, 'Open a consultation with the selected template. No clinical note is inferred.'),
    'consultation.approve': (Versioned, 'consultation', 'Approve the exact saved document for owner sharing. Review the entire document first.'),
    'consultation.archive': (Versioned, 'consultation', 'Archive the consultation without deleting its source records.'),
    'source.add': (SourceAdd, None, 'Record only the exact text supplied by the operator; never author clinical facts. A linked consultation becomes in progress.'),
    'observation.add': (Observation, None, 'Record an explicitly supplied numeric finding, units and optional supplied ranges with its source receipt. Do not infer values or ranges.'),
    'observation.record': (TypedObservation, None, 'Record an explicitly supplied value using an existing ontology code and its original source. Do not infer facts, convert units or invent ranges.'),
    'summary.generate': (SummaryGenerate, 'consultation', 'Queue source-backed document assembly. It remains unapproved until veterinarian review.'),
    'summary.save': (SummarySave, 'consultation', 'Save explicitly supplied section text with original source references. Does not approve or publish the document.'),
    'appointment.create': (AppointmentCreate, None, 'Book the explicitly selected patient, clinician, date, time and duration. Collision and rota checks also run at confirmation.'),
    'appointment.series': (AppointmentSeries, None, 'Book all explicitly requested occurrences atomically. A single rota or booking conflict prevents the entire series.'),
    'appointment.reschedule': (AppointmentMove, 'appointment', 'Move this appointment, preserving unspecified fields. Confirmation rechecks room and clinician availability.'),
    'appointment.update': (AppointmentStatus, 'appointment', 'Change appointment status. Reopening requires current room and clinician availability.'),
    'invoice.create': (InvoiceCreate, None, 'Issue an invoice with explicit quantities, unit prices, discount cents and tax basis points, including explicit zeros. Does not charge money.'),
    'invoice.void': (Reasoned, 'invoice', 'Void an unpaid invoice and retain a dated reasoned receipt. No money or stock is moved.'),
    'payment.record': (PaymentRecord, 'invoice', 'Record a payment already completed outside Broby. This does not charge a card or move money.'),
    'payment.refund': (Refund, 'payment', 'Record an externally completed refund. Version must be the invoice version. This does not send money; Stripe payments use their dedicated provider flow.'),
    'inventory.create': (InventoryCreate, None, 'Create inventory with explicit stock, reorder threshold and unit price in cents.'),
    'inventory.adjust': (InventoryAdjust, 'inventory', 'Record a reasoned stocktake. Stock lots are adjusted and an audit receipt is retained.'),
    'inventory.receive': (InventoryReceive, 'inventory', 'Receive an explicit batch into stock. When linked to a purchase order, increase its received quantity too.'),
    'medication.dispense': (Dispense, None, 'Consume eligible stock lots and record the exact veterinarian-supplied dose, frequency and instructions. Never infer or recommend treatment.'),
    'template.save': (TemplateSave, 'template', 'Create or replace the complete named section list. Existing consultation documents are unchanged.'),
    'template.archive': (Versioned, 'template', 'Archive this custom template. The default SOAP template cannot be archived.'),
    'reminder.queue_due': (Payload, None, 'Prepare eligible due-reminder drafts using current settings. Does not dispatch messages.'),
    'message.queue': (MessageQueue, None, 'Prepare a manual draft containing the exact operator-supplied message. Does not send it.'),
    'message.update': (MessageUpdate, 'outbox', 'Replace an unsent manual draft with the exact supplied text. Does not dispatch it.'),
    'message.cancel': (Versioned, 'outbox', 'Cancel an unsent draft and revoke its linked discharge access link, if present.'),
    'message.complete': (Versioned, 'outbox', 'Mark a draft as already sent manually. Confirm only after actual external delivery; this action does not send it.'),
    'share.create': (PatientTarget, None, 'Create a seven-day revocable owner link exposing only approved content. Anyone with that link can access it. No message is sent.'),
    'share.revoke': (schema('ShareRevoke', token=(Identifier, ...)), None, 'Revoke the exact owner link. Previously downloaded files cannot be recalled.'),
    'attachment.approve': (Approval, 'attachment', 'Allow or withdraw owner access to this exact attachment through owner links.'),
    'recording.approve': (Approval, 'recording', 'Allow or withdraw owner playback of the exact completed recording.'),
    'recording.transcribe': (Transcribe, 'recording', 'Queue speech processing using the selected language and speaker setting. Provider usage can incur cost; source audio is retained.'),
    'job.retry': (Target, None, 'Retry a failed job using its saved inputs. Existing task idempotency and provider receipt guards remain in force.'),
    'intake.accept': (IntakeAccept, 'intake', 'Copy the exact owner-reported submission into the clinical source history. It remains owner-reported information.'),
    'intake.close': (Versioned, 'intake', 'Close this owner intake without adding it to a consultation.'),
    'settings.save': (SettingsSave, None, 'Replace the displayed clinic preferences. Retention selects medical/context excerpts; it does not delete original records.'),
    'member.save': (MemberSave, 'member', 'Create or update staff access and role. Does not send an invitation; cannot remove your own administrative access.'),
    'feature_locks.save': (FeatureLocks, None, 'Replace the complete clinic restriction list. Preserve restrictions not explicitly removed. Existing master restrictions still apply.'),
    'ontology.save': (OntologySave, None, 'Add an explicitly supplied immutable observation definition. Do not invent clinical units or terminology.'),
    'lab.import': (LabImport, None, 'Import the exact supplied laboratory CSV as source-backed numeric observations. This is not a live analyser connection.'),
    'source.speakers': (Speakers, 'source', 'Replace the complete reviewed speaker-label mapping for this transcript. Does not change recorded words or audio.'),
    'automation.save': (Automation, None, 'Configure scheduled draft preparation and handover snapshots. No customer messages are automatically dispatched.'),
    'dashboard.save': (DashboardSave, 'dashboard', 'Save the exact validated record filters as a dashboard. It refreshes matching records; no clinical records change.'),
    'dashboard.delete': (Versioned, 'dashboard', 'Archive this saved dashboard without deleting any clinical records.'),
    'owner.recall_preference': (RecallPreference, 'owner', 'Record an explicit owner recall preference and reason. Opt-out cancels their pending recall drafts; it does not send a message.'),
    'recall.cancel': (Reasoned, 'recall_campaign', 'Cancel pending drafts in this campaign. Already delivered or uncertain messages are unchanged.'),
    'leave.request': (LeaveRequest, None, 'Submit full-day leave for the exact staff member and inclusive dates. Availability changes only after a separate administrator approves.'),
    'leave.review': (LeaveReview, 'staff_leave', 'Approve or reject pending leave with a reason. Approval rechecks rota and booking conflicts; you cannot approve your own request.'),
    'leave.cancel': (Reasoned, 'staff_leave', 'Withdraw pending or current/future approved leave, retaining the review history.'),
    'discharge.queue': (PatientTarget, None, 'Prepare approved care information and a revocable owner link in a manual draft. Nothing is sent.'),
}

# Operations whose meaningful review is a dedicated workflow or capture screen.
# The model sees a destination, never an executable raw payload contract.
GUIDED = {
    **{n: ('Settings', 'Use the migration preview, source file and reconciliation review.') for n in ('import.patients', 'import.records', 'migration.preview', 'migration.apply')},
    **{n: ('Patient', 'Use the recorder and verified audio chunk manifest.') for n in ('recording.create', 'recording.complete', 'recording.refine')},
    **{n: ('Billing', 'Use the provider-priced checkout/refund screen and canonical provider receipt.') for n in ('stripe.checkout', 'stripe.cancel', 'stripe.refresh', 'stripe.refund')},
    **{n: ('Messages', 'Use the restricted sender setup and delivery/recipient review.') for n in ('twilio.trial_send', 'twilio.reconcile')},
    'recall.prepare': ('Messages', 'Review the recipient preview, consent and selected batch before preparing.'),
    'schedule.configure': ('Settings', 'Review the complete staff rota and booking conflicts in the rota editor.'),
    'transfer.accept': ('Settings', 'Review clinic identity, patient matching, original sources and transfer consent.'),
    **{n: ('Settings', 'Use the two-party organization or explicit member-access review.') for n in ('organization.create', 'organization.clinic_create', 'organization.policy', 'organization.join_request', 'organization.join_review', 'organization.join_cancel', 'access.member')},
    **{n: ('Patient', 'Use the original clinical source and typed observation approval screen.') for n in ('clinical.ingest', 'clinical.approve', 'ontology.propose', 'ontology.review')},
    **{n: ('Handover', 'Read the exact current owner conversation and use its reply/escalation review.') for n in ('conversation.reply', 'conversation.acknowledge', 'conversation.close', 'conversation.policy', 'escalation.acknowledge')},
}


def catalogue():
    return {name: {'description': effect, 'payload_schema': model.model_json_schema()}
            for name, (model, _, effect) in SPECS.items()}


def prepare(c, clinic, actor, name, payload, patient_id=None):
    from fastapi import HTTPException
    from pydantic import ValidationError
    from actions import fail, owned, version
    from db import all_records, get
    from clinic_workflows import calendar_date, clinic_today

    model, kind, effect = SPECS[name]
    try:
        # Patch actions must not emit defaults for fields the operator omitted.
        p = model.model_validate(payload).model_dump(exclude_unset=True)
    except ValidationError as error:
        fields = sorted({'.'.join(map(str, item['loc'])) or 'payload' for item in error.errors()})
        fail('Check required fields, values and types: ' + ', '.join(fields))
    sources, fields = [], []

    def field(label, value):
        fields.append({'label': label, 'value': str(value)})

    def ref(id, expected, versioned=False):
        row = owned(c, id, clinic, expected)
        if versioned: version(row, p)
        target_patient = row['id'] if expected == 'patient' else row['data'].get('patient_id')
        if patient_id and target_patient and patient_id != target_patient:
            fail('This record belongs to another patient. Select that patient before preparing this action.')
        if expected == 'owner' and row['data'].get('merged_into'): fail('Choose an active owner, not a merged owner.')
        if not any(r['id'] == id for r in sources): sources.append(row)
        return row

    r = ref(p['id'], kind, 'version' in p and name != 'payment.refund') if kind and p.get('id') else None
    references = {'patient_id': 'patient', 'owner_id': 'owner', 'target_id': 'owner', 'source_id': 'source',
                  'consultation_id': 'consultation', 'template_id': 'template', 'clinician': 'member',
                  'member_id': 'member', 'inventory_id': 'inventory', 'purchase_order_id': 'purchase_order'}
    for key, expected in references.items():
        if p.get(key): ref(p[key], expected, name == 'medication.dispense' and key == 'inventory_id')
    patients = {s['id'] if s['kind'] == 'patient' else s['data'].get('patient_id') for s in sources} - {None}
    if len(patients) > 1: fail('All clinical references must belong to the same patient.')
    if r and r['data'].get('patient_id'): ref(r['data']['patient_id'], 'patient')
    if name in ('template.save', 'member.save', 'dashboard.save'):
        if bool(p.get('id')) != ('version' in p): fail('Existing records require their current id and version; new records require neither.')
    if name == 'patient.update' and not set(p) - {'id', 'version'}: fail('Specify a patient field to change.')
    if 'date_of_birth' in p: calendar_date(p['date_of_birth'], 'Date of birth', latest=clinic_today(c, clinic).date(), optional=True)
    if name == 'consultation.create': ref(p.get('template_id', 'soap-' + clinic), 'template')
    if name == 'owner.merge':
        if p['id'] == p['target_id']: fail('Choose two different owners.')
        linked = [x for x in all_records(c, clinic, 'patient') if p['id'] in [x['data']['owner_id'], *x['data'].get('additional_owner_ids', [])]]
        for patient in linked: ref(patient['id'], 'patient')
        field('Patient links moved', ', '.join(x['data']['name'] + ' (' + x['id'] + ')' for x in linked) or 'None')
    if name in ('source.add', 'observation.add', 'observation.record', 'lab.import', 'summary.save'):
        effect += ' Review every recorded word or value against the original source before confirming.'
    if name in ('observation.add', 'observation.record'):
        if p.get('low') is not None and p.get('high') is not None and p['low'] > p['high']: fail('Lower range must not exceed upper range.')
        if name == 'observation.record':
            from ontology_workflow import lookup
            term = lookup(c, clinic, p['code'])
            if not term: fail('Choose an existing observation definition.')
            typ, value = term['value_type'], p['value']
            if ((typ == 'boolean' and type(value) is not bool) or (typ == 'text' and not isinstance(value, str)) or
                    (typ == 'number' and type(value) not in (int, float))): fail('Observation value must match the definition type.')
            if typ != 'number' and (p.get('low') is not None or p.get('high') is not None): fail('Only numeric observations accept reference ranges.')
            field('Definition', term['name'] + ' · ' + term['unit'] + ' · ' + typ)
    if name == 'summary.save':
        for section in p['summary']:
            for sid in section['source_ids']:
                source = ref(sid, 'source')
                if source['data']['patient_id'] != r['data']['patient_id']: fail('A receipt belongs to another patient.')
    if name in ('summary.generate', 'consultation.approve'):
        if name == 'summary.generate': ref(p.get('template_id', r['data']['template_id']), 'template')
        if not r['data'].get('source_ids') and name == 'summary.generate': fail('Add source notes before generating a document.')
        for sid in r['data'].get('source_ids', []): ref(sid, 'source')
        if name == 'consultation.approve':
            if not r['data'].get('summary'): fail('Create a document before approving.')
            if r['data'].get('generated_revision') != r['data'].get('input_revision'): fail('New notes were added; regenerate or review and save the document first.')
            field('Document to approve', '\n\n'.join(s['name'] + '\n' + s['text'] for s in r['data']['summary']))
    if name.startswith('appointment.'):
        d = {**(r['data'] if r else {}), **p}
        member = ref(d['clinician'], 'member')
        if not member['data'].get('active'): fail('Choose an active clinician.')
        if name == 'appointment.series':
            from datetime import timedelta
            try: last = date.fromisoformat(p['date']) + timedelta(days=(p['count'] - 1) * p['interval_days'])
            except OverflowError: fail('Series exceeds the supported calendar.')
            field('Final occurrence', last.isoformat())
        if name == 'appointment.reschedule':
            for key in ('date', 'time', 'duration', 'clinician', 'reason', 'room'):
                if key in r['data']: field('Current ' + key.replace('_', ' '), r['data'][key])
    if name == 'invoice.create':
        from operations_rules import totals
        amounts = totals(p['items'], p)
        field('Tax', f"SGD {amounts['tax_cents']/100:.2f}"); field('Invoice total', f"SGD {amounts['total_cents']/100:.2f}")
    if name in ('payment.record', 'invoice.void', 'payment.refund'):
        from billing import outstanding
        from stripe_payments import guard_invoice
        invoice = ref(r['data']['invoice_id'], 'invoice', True) if name == 'payment.refund' else r
        guard_invoice(c, clinic, invoice['id'])
        if invoice['data']['status'] == 'void': fail('This invoice is void.')
        if name == 'payment.record' and p['amount_cents'] > outstanding(invoice['data']): fail('Payment exceeds outstanding balance.')
        if name == 'payment.refund':
            if r['data'].get('checkout_id'): fail('Use Billing to refund through Stripe.')
            refunded = sum(x['data']['amount_cents'] for x in all_records(c, clinic, 'refund') if x['data']['payment_id'] == r['id'])
            if p['amount_cents'] > r['data']['amount_cents'] - refunded: fail('Refund exceeds unrefunded payment.')
        if name == 'invoice.void' and (invoice['data']['paid_cents'] or any(x['data']['invoice_id'] == r['id'] for x in all_records(c, clinic, 'credit_note'))): fail('Paid invoices or invoices with credit history cannot be voided.')
        field('Invoice', invoice['data']['number']); field('Current outstanding', f"SGD {outstanding(invoice['data'])/100:.2f}")
    if name == 'inventory.receive' and p.get('purchase_order_id'):
        order = ref(p['purchase_order_id'], 'purchase_order')['data']
        if order['inventory_id'] != r['id'] or order['status'] not in ('ordered', 'partial'): fail('Choose an open order for this inventory item.')
        if p['quantity'] > order['quantity'] - order['received']: fail('Receipt exceeds unreceived purchase quantity.')
    if name == 'medication.dispense':
        item = ref(p['inventory_id'], 'inventory')
        if p['quantity'] > item['data']['stock']: fail('Insufficient stock.')
        field('Stock after dispensing', item['data']['stock'] - p['quantity'])
    if name == 'template.save' and len(set(p['sections'])) != len(p['sections']): fail('Template sections must be unique.')
    if name == 'template.archive' and r['id'] == 'soap-' + clinic: fail('The default SOAP template cannot be archived.')
    if name.startswith('message.') and r:
        if r['data']['status'] not in (('pending',) if name == 'message.complete' else ('pending', 'failed')): fail('This message is no longer editable.')
        if name != 'message.cancel':
            from recalls import validate_draft
            validate_draft(c, r)
        field('Current message', r['data']['body'])
    if name in ('message.queue', 'share.create', 'discharge.queue'):
        patient = ref(p['patient_id'], 'patient'); ref(patient['data']['owner_id'], 'owner')
    if name == 'share.revoke':
        grant = c.execute('SELECT * FROM grants WHERE token=? AND clinic_id=?', (p['token'], clinic)).fetchone()
        if not grant or grant['revoked']: fail('Choose an active owner link in this clinic.')
        ref(grant['patient_id'], 'patient'); field('Link expires', grant['expires_at'])
    if name in ('recording.approve', 'recording.transcribe') and r['data']['status'] != 'saved': fail('Finish uploading the recording first.')
    if name == 'job.retry':
        import json
        job = c.execute('SELECT * FROM jobs WHERE id=? AND clinic_id=?', (p['id'], clinic)).fetchone()
        if not job: fail('Job not found.', 404)
        if job['status'] != 'failed': fail('Only failed jobs can be retried.')
        ref(job['consultation_id'], 'consultation'); data = json.loads(job['payload'])
        if data.get('recording_id'): ref(data['recording_id'], 'recording')
        field('Job type', data.get('kind', 'Document assembly'))
    if name.startswith('intake.') and r['data']['status'] != 'new': fail('This intake was already handled.')
    if name in ('settings.save', 'automation.save'): ref('settings-' + clinic, 'settings', True)
    if name == 'feature_locks.save':
        from actions import PERMISSIONS
        from read_access import READS
        ref(clinic, 'clinic', True)
        if len(set(p['actions'])) != len(p['actions']) or any(x not in PERMISSIONS and x not in READS for x in p['actions']): fail('Use known, unique restrictions.')
    if name == 'member.save':
        if p.get('id') == actor and (p['role'] != 'admin' or not p['active']): fail('You cannot remove your own administrative access.')
        if not p.get('id') and not p['active']: fail('New staff start active. Use the staff screen to deactivate after creation.')
    if name == 'ontology.save':
        if not p['code'].replace('_', '').isalnum(): fail('Use a valid ontology code.')
        if c.execute('SELECT code FROM ontology WHERE code=?', (p['code'],)).fetchone(): fail('Observation definitions are immutable; choose a new code.')
    if name == 'lab.import':
        import csv, io
        from actions import number
        results = list(csv.DictReader(io.StringIO(p['csv'])))
        if not results or len(results) > 500: fail('Provide 1–500 lab results.')
        for row in results:
            if not row.get('name') or not row.get('unit'): fail('Every lab result needs name, value and unit.')
            number(row.get('value'), 'Value', -1e9)
            low = number(row['low'], 'Lower range', -1e9) if row.get('low') else None
            high = number(row['high'], 'Upper range', -1e9) if row.get('high') else None
            if low is not None and high is not None and low > high: fail('Lower range must not exceed upper range.')
        field('Lab results', len(results))
    if name == 'source.speakers':
        known = {str(u['speaker']) for u in r['data'].get('utterances', []) if u.get('speaker') is not None}
        if not known or not set(p['speaker_labels']).issubset(known): fail('Use speaker identifiers present in this transcript.')
    if name == 'dashboard.save':
        from record_queries import select_records
        selected = select_records(c, clinic, p['query'])
        p['query'] = selected['query']
        if patient_id and p['query'].get('patient_id') != patient_id: fail('Use this patient in the saved filter or open clinic-wide chat.')
        field('Filter', selected['filter_summary']); field('Current matches', len(selected['records']))
    if name == 'recall.cancel' and r['data']['status'] != 'prepared': fail('This campaign was already cancelled.')
    if name == 'leave.request':
        member = ref(p['member_id'], 'member')
        if not member['data'].get('active'): fail('Choose an active staff member.')
        if actor != p['member_id'] and owned(c, actor, clinic, 'member')['data']['role'] != 'admin': fail('You can only request your own leave.', 403)
        if p['start'] < clinic_today(c, clinic).date().isoformat() or p['start'] > p['end'] or (date.fromisoformat(p['end']) - date.fromisoformat(p['start'])).days > 365: fail('Use current/future inclusive leave dates within 366 days.')
        if any(x['data']['member_id'] == p['member_id'] and x['data']['status'] in ('pending', 'approved') and x['data']['start'] <= p['end'] and x['data']['end'] >= p['start'] for x in all_records(c, clinic, 'staff_leave')): fail('Leave overlaps another pending or approved request.')
    if name == 'leave.review':
        from scheduling import leave_review
        _, config, overlap, blocked = leave_review(c, clinic, actor, p)
        if p['decision'] == 'approved':
            if overlap or blocked: fail('Resolve overlapping leave or appointment conflicts before approving.')
            p['schedule_version'] = config['version'] if config else None
            if config: ref(config['id'], 'schedule')
    if name == 'leave.cancel':
        if r['data']['member_id'] != actor and owned(c, actor, clinic, 'member')['data']['role'] != 'admin': fail('You can only withdraw your own leave.', 403)
        if r['data']['status'] not in ('pending', 'approved') or r['data']['status'] == 'approved' and r['data']['end'] < clinic_today(c, clinic).date().isoformat(): fail('Only pending or current/future approved leave can be withdrawn.')
    if r:
        field('Selected record', label(r))
        for key in ('stock', 'status'):
            if key in r['data']: field('Current ' + key, r['data'][key])
    for key, value in p.items():
        if key in ('version', 'schedule_version', 'token'): continue
        if key == 'id' and r: continue
        field(key.replace('_', ' ').capitalize(), display(value, key, sources))
    if not fields: field('Clinic', owned(c, clinic, clinic, 'clinic')['data']['name'])
    return {'action': name, 'payload': p}, {'title': name.replace('.', ' · ').replace('_', ' ').capitalize(), 'fields': fields, 'effects': [effect]}, sources


def label(row):
    d = row['data']
    return str(d.get('name') or d.get('title') or d.get('number') or row['kind'].replace('_', ' ')) + ' (' + row['id'] + ')'


def display(value, key, sources):
    if isinstance(value, bool): return 'Yes' if value else 'No'
    if value is None: return 'None'
    if isinstance(value, str):
        row = next((r for r in sources if r['id'] == value), None)
        return label(row) if row else value or 'Empty'
    if key.endswith('_cents'): return f'SGD {value/100:.2f}'
    if key == 'tax_bps': return f'{value/100:g}%'
    if isinstance(value, list): return '\n\n'.join(display(v, '', sources) for v in value) or 'None'
    if isinstance(value, dict): return '\n'.join(k.replace('_', ' ').capitalize() + ': ' + display(v, k, sources) for k, v in value.items())
    return str(value)
