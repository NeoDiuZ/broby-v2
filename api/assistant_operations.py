"""Typed, read-only preparation for a bounded set of assistant operations.

This is not a second mutation path. Confirmation still invokes actions.execute,
which checks current permission, versions, business rules and idempotency.
"""
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(min_length=1, max_length=1000)]


class Payload(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', str_strip_whitespace=True)


class Target(Payload):
    id: Identifier


class Versioned(Target):
    version: Annotated[int, Field(ge=1)]


class ReminderFields(Payload):
    title: Text
    due: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]

    @field_validator('due')
    @classmethod
    def valid_date(cls, value):
        date.fromisoformat(value)
        return value


class ReminderCreate(ReminderFields):
    patient_id: Identifier


class ReminderUpdate(ReminderFields, Versioned):
    pass


class RecordingRename(Versioned):
    title: Annotated[str, Field(min_length=1, max_length=160)]


class PurchaseCreate(Payload):
    inventory_id: Identifier
    supplier: Annotated[str, Field(min_length=1, max_length=300)]
    quantity: Annotated[int, Field(ge=1)]


class PurchaseCancel(Versioned):
    reason: Text


class PatientOwners(Versioned):
    owner_id: Identifier
    # This replaces the whole list: omission must never remove existing owners.
    additional_owner_ids: Annotated[list[Identifier], Field(max_length=20)]

    @field_validator('additional_owner_ids')
    @classmethod
    def unique_owners(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Choose each additional owner once')
        return value


CONTRACTS = {
    'reminder.create': (ReminderCreate, 'Create a due reminder; does not send a message.'),
    'reminder.update': (ReminderUpdate, 'Replace title and due date of an open reminder. Preserve any field the operator did not ask to change. Cancels its old unsent draft.'),
    'reminder.cancel': (Versioned, 'Cancel an open reminder and its unsent draft.'),
    'reminder.complete': (Versioned, 'Mark an open reminder completed and cancel its unsent draft.'),
    'purchase_order.create': (PurchaseCreate, 'Record an order for an exact inventory item, explicitly supplied supplier and whole quantity. Does not contact the supplier or receive stock.'),
    'purchase_order.cancel': (PurchaseCancel, 'Cancel the unreceived balance of an order with an explicit reason. Received stock is unchanged.'),
    'recording.rename': (RecordingRename, 'Change a recording title; audio and transcripts are unchanged.'),
    'patient.owners': (PatientOwners, 'Replace the primary and complete additional owner list using existing active owner IDs. Preserve owners not explicitly removed. Changing ownership revokes existing owner access links.'),
    'handover.prepare': (Payload, 'Prepare or retrieve today\'s clinic-local handover snapshot. Does not send a message or acknowledge it.'),
    'handover.acknowledge': (Target, 'Record that the current operator has read the exact handover they selected. Never choose a handover on their behalf.'),
}


def catalogue():
    return {name: {'description': description, 'payload_schema': model.model_json_schema()}
            for name, (model, description) in CONTRACTS.items()}


def prepare(c, clinic, name, payload, patient_id=None):
    """Read-only validation and a deterministic, human-readable review snapshot."""
    from actions import fail, owned, version
    from clinic_workflows import clinic_today

    model, _ = CONTRACTS[name]
    try:
        p = model.model_validate(payload).model_dump()
    except ValidationError as error:
        fields = sorted({'.'.join(map(str, item['loc'])) for item in error.errors()})
        fail('Check the required fields and types: ' + ', '.join(fields))

    sources = []
    fields = []

    def field(label, value):
        fields.append({'label': label, 'value': str(value)})

    def ref(id, kind, versioned=False):
        r = owned(c, id, clinic, kind)
        if versioned:
            version(r, p)
        target_patient = r['id'] if kind == 'patient' else r['data'].get('patient_id')
        if patient_id and target_patient and target_patient != patient_id:
            fail('This record belongs to another patient. Select that patient before preparing this action.')
        if not any(s['id'] == r['id'] for s in sources):
            sources.append(r)
        return r

    if name.startswith('reminder.'):
        if name == 'reminder.create':
            patient = ref(p['patient_id'], 'patient')
            title = 'Create reminder'
        else:
            r = ref(p['id'], 'reminder', True)
            if r['data']['status'] != 'due':
                fail('This reminder is already closed. Choose an open reminder.')
            patient = ref(r['data']['patient_id'], 'patient')
            title = {'reminder.update': 'Update reminder', 'reminder.cancel': 'Cancel reminder', 'reminder.complete': 'Complete reminder'}[name]
            field('Current reminder', r['data']['title'])
            field('Current due date', r['data']['due'])
        field('Patient', patient['data']['name'])
        if name in ('reminder.create', 'reminder.update'):
            field('Title', p['title']); field('Due date', p['due'])
        effects = ['No message will be sent.']
        if name != 'reminder.create':
            effects.append('Any linked unsent reminder draft will be cancelled.')
    elif name.startswith('purchase_order.'):
        if name == 'purchase_order.create':
            r = ref(p['inventory_id'], 'inventory')
            title = 'Create purchase order'
            field('Item', r['data']['name']); field('Unit', r['data']['unit'])
            field('Supplier', p['supplier']); field('Quantity ordered', p['quantity'])
            effects = ['Records the order only. No supplier will be contacted and stock will not change.']
        else:
            r = ref(p['id'], 'purchase_order', True)
            if r['data']['status'] not in ('ordered', 'partial'):
                fail('Choose an open purchase order with an unreceived balance.')
            item = ref(r['data']['inventory_id'], 'inventory')
            title = 'Cancel purchase order'
            field('Item', item['data']['name']); field('Supplier', r['data']['supplier'])
            field('Quantity ordered', r['data']['quantity']); field('Already received', r['data']['received'])
            field('Reason', p['reason'])
            effects = ['Cancels the unreceived balance. Received stock will not change.']
    elif name == 'recording.rename':
        r = ref(p['id'], 'recording', True)
        patient = ref(r['data']['patient_id'], 'patient')
        title = 'Rename recording'
        field('Patient', patient['data']['name']); field('Current title', r['data'].get('title', 'Untitled recording'))
        field('New title', p['title'])
        effects = ['Audio, transcripts and sharing approval will not change.']
    elif name == 'patient.owners':
        r = ref(p['id'], 'patient', True)
        if p['owner_id'] in p['additional_owner_ids']:
            fail('The primary owner cannot also be an additional owner.')
        def owner(id):
            result = ref(id, 'owner')
            if result['data'].get('merged_into'):
                fail('Choose an active owner, not a merged owner.')
            return result['data']['name'] + ' (' + result['id'] + ')'
        title = 'Update patient owners'
        field('Patient', r['data']['name'])
        field('Current primary owner', owner(r['data']['owner_id']))
        field('Current additional owners', ', '.join(owner(id) for id in r['data'].get('additional_owner_ids', [])) or 'None')
        field('New primary owner', owner(p['owner_id']))
        field('New additional owners', ', '.join(owner(id) for id in p['additional_owner_ids']) or 'None')
        effects = ['Changing the owner list revokes existing owner access links. Review the complete list before confirming.']
    else:
        if name == 'handover.prepare':
            title = 'Prepare handover'
            p['expected_date'] = clinic_today(c, clinic).date().isoformat()
            field('Clinic date', p['expected_date'])
            effects = ['Keeps an existing snapshot for today, or creates one from current records. No message will be sent.']
        else:
            r = ref(p['id'], 'handover')
            title = 'Acknowledge handover'
            field('Handover', r['data']['title']); field('Date', r['data']['date'])
            effects = ['Records your acknowledgement only. Read the linked snapshot before confirming.']
    return {'action': name, 'payload': p}, {'title': title, 'fields': fields, 'effects': effects}, sources
