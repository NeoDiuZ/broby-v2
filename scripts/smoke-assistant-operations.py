#!/usr/bin/env python3
"""Opt-in hosted acceptance using synthetic fixtures and the real model.

No provider sends, supplier contact, payment or real-clinic data. Keep the state
and credentials outside git. Preparation intentionally refuses existing state.
"""
import argparse
import hashlib
import io
import json
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

import httpx

p = argparse.ArgumentParser()
p.add_argument('base_url')
p.add_argument('--credentials', type=Path, required=True)
p.add_argument('--state', type=Path, required=True)
p.add_argument('--clinic', required=True)
p.add_argument('--actor', required=True)
p.add_argument('--phase', choices=['prepare', 'evaluate', 'readback'], required=True)
args = p.parse_args()
state = json.loads(args.state.read_text()) if args.state.exists() else {}


def persist():
    args.state.write_text(json.dumps(state, indent=2)); args.state.chmod(0o600)


def check(ok, label):
    assert ok, label
    print('PASS ' + label, flush=True)
    state.setdefault('checks', []).append({'phase': args.phase, 'label': label, 'at': datetime.now(timezone.utc).isoformat()})
    persist()


with httpx.Client(base_url=args.base_url.rstrip('/') + '/api/', timeout=210) as client:
    def req(method, route, expected=200, **kwargs):
        response = client.request(method, route, **kwargs)
        assert response.status_code == expected, (method, route.split('/')[0], response.status_code)
        return response.json()

    def act(name, payload):
        return req('POST', 'actions', json={'action': name, 'payload': payload, 'key': str(uuid.uuid4())})

    def records():
        return {r['id']: r for r in req('GET', 'bootstrap')['records']}

    def remember(key, result):
        state[key] = result['id']; persist()
        return result

    def ask(case, message, name=None, patient=None):
        turn = req('POST', 'assistant', json={'message': message, 'patient_id': patient, 'key': 'operations-' + state['suffix'] + '-' + case})
        state.setdefault('turns', {})[case] = turn; persist()
        if name:
            check(turn.get('action', {}).get('action') == name and bool(turn.get('review')), case + ': real model proposes the expected reviewed operation')
        return turn

    def confirm(case, expected=200):
        turn = state['turns'][case]
        result = req('POST', f"assistant/conversations/{turn['conversation_id']}/turns/{turn['turn_id']}/confirm", expected=expected)
        state.setdefault('executions', {})[case] = result; persist()
        return result

    credentials = json.loads(args.credentials.read_text())
    req('POST', 'login', json={k: credentials[k] for k in ('username', 'password')})
    client.headers.update({'x-clinic-id': args.clinic, 'x-actor-id': args.actor})
    if args.phase == 'prepare':
        assert not state, 'Existing fixture state; do not duplicate preparation'
        state.update(suffix=uuid.uuid4().hex[:8], clinic=args.clinic, actor=args.actor, synthetic_only=True)
        persist()
        suffix = state['suffix']
        patient = remember('patient', act('patient.create', {'name': 'SYNTHETIC Operations ' + suffix, 'species': 'Dog', 'owner_name': 'SYNTHETIC Primary ' + suffix}))
        state['primary_owner'] = patient['data']['owner_id']; persist()
        remember('extra_owner', act('owner.create', {'name': 'SYNTHETIC Additional ' + suffix}))
        remember('item', act('inventory.create', {'name': 'SYNTHETIC Supply ' + suffix, 'unit': 'pack', 'stock': 0, 'reorder': 2}))
        remember('consultation', act('consultation.create', {'patient_id': state['patient'], 'title': 'SYNTHETIC audio acceptance'}))
        recording = remember('recording', act('recording.create', {'patient_id': state['patient'], 'consultation_id': state['consultation'], 'mime': 'audio/wav'}))
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000); out.writeframes(b'\x00\x00' * 8000)
        raw = wav.getvalue(); state['audio_sha256'] = hashlib.sha256(raw).hexdigest(); persist()
        req('PUT', 'recordings/' + recording['id'] + '/chunks/0', content=raw)
        act('recording.complete', {'id': recording['id'], 'expected_chunks': 1, 'duration': 1})
        check(req('GET', 'ready')['status'] == 'ready', 'synthetic patient, owners, supply and original audio are ready')
    else:
        assert state['clinic'] == args.clinic and state['actor'] == args.actor
        suffix = state['suffix']; patient = state['patient']; item = state['item']
        if args.phase == 'evaluate':
            assert not state.get('evaluate_started'), 'Evaluation already started; inspect saved evidence before resuming individual steps'
            state['evaluate_started'] = True; persist()
            before = records()
            ask('create', 'Create a reminder titled "SYNTHETIC Recall ' + suffix + '" due on 2000-01-01 for this patient.', 'reminder.create', patient)
            check(records() == before, 'asking for a reminder does not mutate clinic records')
            reminder = remember('reminder', confirm('create'))
            act('reminder.queue_due', {})
            reminder = records()[reminder['id']]; state['old_outbox'] = reminder['data']['outbox_id']; persist()
            ask('update', f"Move reminder {reminder['id']} to 2098-07-12. Keep its title unchanged.", 'reminder.update', patient)
            check(records()[reminder['id']] == reminder, 'reviewing a date change leaves the existing reminder unchanged')
            updated = confirm('update')
            check(updated['data']['title'] == reminder['data']['title'] and updated['data']['due'] == '2098-07-12' and records()[state['old_outbox']]['data']['status'] == 'cancelled', 'confirmed reminder edit preserves its title and cancels only its old unsent draft')
            ask('cancel', f"Cancel the reminder {reminder['id']}.", 'reminder.cancel', patient)
            check(confirm('cancel')['data']['status'] == 'cancelled', 'confirmed cancellation persists')
            completed = remember('completed_reminder', act('reminder.create', {'patient_id': patient, 'title': 'SYNTHETIC Complete ' + suffix, 'due': '2098-07-13'}))
            ask('complete', f"Mark reminder {completed['id']} as completed.", 'reminder.complete', patient)
            check(confirm('complete')['data']['status'] == 'completed', 'confirmed completion persists')
            ask('order', f"Create a purchase order for 10 packs of SYNTHETIC Supply {suffix} from supplier SYNTHETIC Supplier {suffix}. Record the order only.", 'purchase_order.create')
            order = remember('order', confirm('order'))
            check(order['data']['inventory_id'] == item and order['data']['quantity'] == 10 and order['data']['supplier'] == 'SYNTHETIC Supplier ' + suffix and records()[item]['data']['stock'] == 0, 'order uses exact supplied item, quantity and supplier without receiving stock')
            stock = records()[item]
            act('inventory.receive', {'id': item, 'version': stock['version'], 'quantity': 3, 'batch': 'SYNTHETIC ' + suffix, 'supplier': 'SYNTHETIC Supplier ' + suffix, 'purchase_order_id': order['id']})
            ask('cancel_order', f"Cancel the remaining balance of purchase order {order['id']}. Reason: Synthetic acceptance complete.", 'purchase_order.cancel')
            cancelled = confirm('cancel_order')
            check(cancelled['data']['status'] == 'cancelled' and cancelled['data']['received'] == 3 and records()[item]['data']['stock'] == 3, 'partial order cancellation preserves all three received packs')
            ask('rename', f"Rename recording {state['recording']} to SYNTHETIC Reviewed audio {suffix}.", 'recording.rename', patient)
            check(confirm('rename')['data']['title'] == 'SYNTHETIC Reviewed audio ' + suffix, 'recording rename persists')
            grant = act('share.create', {'patient_id': patient}); state['grant'] = grant['id']; persist()
            ask('owners', f"Add SYNTHETIC Additional {suffix} as an additional owner for this patient. Keep SYNTHETIC Primary {suffix} as primary and preserve all existing owners.", 'patient.owners', patient)
            check(req('GET', 'owner/' + grant['id'])['patient']['id'] == patient, 'reviewing ownership does not revoke existing access')
            changed = confirm('owners')
            check(changed['data']['owner_id'] == state['primary_owner'] and changed['data']['additional_owner_ids'] == [state['extra_owner']], 'ownership confirmation preserves the primary and adds the exact additional owner')
            req('GET', 'owner/' + grant['id'], expected=404)
            check(True, 'ownership change revokes the previous owner capability')
            ask('handover', "Prepare today's handover snapshot for this clinic.", 'handover.prepare')
            handover = remember('handover', confirm('handover'))
            ask('ack', f"I have reviewed handover {handover['id']}; acknowledge that exact snapshot for me.", 'handover.acknowledge')
            ack = confirm('ack')
            check(any(a['actor_id'] == args.actor for a in ack['data']['acknowledged_by']), 'handover acknowledgement records only the acting membership')
            missing = ask('missing', f"Create a purchase order for SYNTHETIC Supply {suffix} from SYNTHETIC Supplier {suffix}, but I have not decided the quantity. Do not guess it.")
            check('action' not in missing, 'missing purchase quantity produces clarification')
            stale = remember('stale_reminder', act('reminder.create', {'patient_id': patient, 'title': 'SYNTHETIC stale review', 'due': '2098-07-14'}))
            ask('stale', f"Move reminder {stale['id']} to 2098-07-15 and keep its title.", 'reminder.update', patient)
            act('reminder.cancel', {'id': stale['id'], 'version': stale['version']})
            confirm('stale', expected=409)
            check(records()[stale['id']]['data']['status'] == 'cancelled', 'a competing change blocks stale confirmation without overwriting it')
            first = state['executions']['order']; check(confirm('order') == first, 'repeated confirmation returns the same purchase order')
        else:
            current = records()
            check(current[state['reminder']]['data']['status'] == 'cancelled' and current[state['completed_reminder']]['data']['status'] == 'completed', 'reminder final states survive new authenticated session')
            check(current[state['old_outbox']]['data']['status'] == 'cancelled', 'superseded reminder draft remains cancelled')
            check(current[item]['data']['stock'] == 3 and current[state['order']]['data']['status'] == 'cancelled' and current[state['order']]['data']['received'] == 3, 'order and received stock reconcile')
            check(current[patient]['data']['owner_id'] == state['primary_owner'] and current[patient]['data']['additional_owner_ids'] == [state['extra_owner']], 'patient ownership persists')
            req('GET', 'owner/' + state['grant'], expected=404)
            audio = client.get('recordings/' + state['recording'] + '/audio')
            check(audio.status_code == 200 and hashlib.sha256(audio.content).hexdigest() == state['audio_sha256'] and current[state['recording']]['data']['title'] == 'SYNTHETIC Reviewed audio ' + suffix, 'renamed original audio remains byte-for-byte identical')
            for case in ('create', 'update', 'cancel', 'complete', 'order', 'cancel_order', 'rename', 'owners', 'handover', 'ack'):
                original = state['turns'][case]
                saved = req('GET', 'assistant/conversations/' + original['conversation_id'])['turns'][0]
                check(saved['review'] == original['review'] and saved['execution'] == state['executions'][case], case + ': saved review and execution survive reload')
            check(req('GET', 'operations/status')['sending_enabled'] is False and req('GET', 'ready')['status'] == 'ready', 'sending remains disabled and hosted storage is ready')
    state[args.phase + '_verified_at'] = datetime.now(timezone.utc).isoformat(); persist()
    req('POST', 'logout')
