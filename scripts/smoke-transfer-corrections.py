#!/usr/bin/env python3
"""Staged synthetic V2 acceptance; a human/browser supplies correction consent and acceptance.

prepare creates dedicated source/receiving clinics and an API-established old link.
review captures the owner's new pending correction request and both histories.
stale makes one safe synthetic owner edit and proves the saved preview is rejected.
readback verifies the separately accepted correction and a normal deduplicated repeat.
State holds synthetic owner capabilities and must remain private. No external send,
speech-provider call, existing clinical-data mutation or V1 access is performed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import uuid
import tempfile
from urllib.parse import urlsplit
import wave

import httpx

V2_HOST = 'https://frontend-production-1283.up.railway.app'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def binary_hash(value):
    return hashlib.sha256(value).hexdigest()


def synthetic_audio():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes((101).to_bytes(2, 'little', signed=True) * 8000)
    return stream.getvalue()


class Rehearsal:
    def __init__(self, args):
        self.args = args
        self.base = args.base_url.rstrip('/')
        parsed = urlsplit(self.base)
        local = args.allow_local_test and parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost') and not parsed.path
        if self.base != V2_HOST and not local:
            raise AssertionError('Use the isolated Broby V2 host; a loopback fixture requires --allow-local-test')
        self.state = json.loads(args.state.read_text()) if args.state.exists() else {}
        if self.state and self.state.get('base_url') != self.base:
            raise AssertionError('State belongs to a different host')
        self.checks = []
        self.client = httpx.Client(base_url=self.base + '/api/', headers={'Origin':self.base}, timeout=120)

    def check(self, value, label):
        if not value:
            raise AssertionError(label)
        self.checks.append(label)
        print('PASS ' + label, flush=True)

    def save(self):
        self.state['checks'] = list(dict.fromkeys(self.state.get('checks', []) + self.checks))
        self.args.state.parent.mkdir(parents=True, exist_ok=True)
        # Owner capabilities must never be created with permissive mode, even briefly.
        with tempfile.NamedTemporaryFile('w', dir=self.args.state.parent, prefix='.correction-state-', delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(self.state, stream, indent=2)
                stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, self.args.state)
            finally:
                temporary.unlink(missing_ok=True)

    def req(self, method, route, expected=200, **kwargs):
        response = self.client.request(method, route, **kwargs)
        if response.status_code != expected:
            # Neither capability paths nor provider/credential response bodies reach stdout.
            raise AssertionError(f'{method} {route.split("/")[0]}: expected HTTP {expected}, received {response.status_code}')
        return response

    def act(self, action, payload, expected=200):
        return self.req('POST', 'actions', expected=expected, json={'action':action, 'payload':payload, 'key':str(uuid.uuid4())}).json()

    def switch(self, side):
        self.client.headers.update({'x-clinic-id':self.state[side+'_clinic'], 'x-actor-id':self.state[side+'_actor']})

    def records(self):
        return self.req('GET', 'bootstrap').json()['records']

    def row(self, id):
        return next(x for x in self.records() if x['id'] == id)

    def request(self, grant, correction=False):
        return self.req('POST', 'owner/'+grant+'/transfers', json={
            'target_clinic':self.state['target_clinic'], 'consent':True,
            'include_audio':True, 'include_medications':True, 'allow_mapping_correction':correction}).json()

    def current_request(self):
        requests = self.req('GET', 'owner/'+self.state['correction_grant']+'/transfers').json()
        requests = [r for r in requests if r['target_clinic'] == self.state['target_clinic'] and r['scope'].get('mapping_correction') is True]
        self.check(len(requests) == 1, 'exactly one owner correction request exists for this fixture')
        request = requests[0]
        self.check(request['scope']['audio'] and request['scope']['medications'], 'owner explicitly included approved original audio and medication history')
        return request

    def preview(self, id, correction=True):
        params = {'target_patient_id':self.state['corrected_patient'], 'correct_mapping':'true'} if correction else {}
        return self.req('GET', 'transfers/'+id+'/preview', params=params).json()

    def native(self, patient, id):
        return self.req('GET', 'v2/patients/'+patient+'/events/'+id).json()

    def lab(self, patient, label):
        return self.act('test.lab.receive', {
            'patient_id':patient, 'dedupe_key':'synthetic-correction-'+self.state['tag']+'-'+label,
            'occurred_at':datetime.now(timezone.utc).isoformat(), 'summary':'SYNTHETIC '+label+' native history',
            'source':{'kind':'document', 'id':'synthetic-correction-'+label, 'page':1, 'text':'SYNTHETIC potassium 4.7 mmol/L; reference 3.5–5.5.'},
            'observations':[{'concept':'potassium', 'name':'Potassium', 'value':4.7, 'unit':'mmol/L', 'ref_low':3.5, 'ref_high':5.5}]})

    def upload(self, patient, name, content, approve=False):
        record = self.req('POST', 'uploads', data={'patient_id':patient}, files={'file':(name,content,'text/plain')}).json()
        if approve:
            record = self.act('attachment.approve', {'id':record['id'], 'version':record['version'], 'approved':True})
        return record

    def prepare(self, login):
        if self.state:
            raise AssertionError('Prepare requires a fresh state file; retain existing evidence')
        self.client.headers.update({'x-clinic-id':login['clinic'], 'x-actor-id':login['actor']})
        self.check(bool(self.req('GET', 'organization').json()), 'account already has an organization; no existing clinic organization is changed')
        self.state.update(base_url=self.base, tag=uuid.uuid4().hex[:8], phase='preparing')
        for side in ('source', 'target'):
            name='SYNTHETIC correction '+side+' '+self.state['tag']
            clinic=self.act('organization.clinic_create', {'name':name,'timezone':'Asia/Singapore'})
            self.state.update({side+'_clinic':clinic['id'],side+'_actor':clinic['member_id'],side+'_clinic_name':name})
            self.save()
        self.switch('source')
        patient=self.act('patient.create', {'name':'SYNTHETIC correction source '+self.state['tag'],'species':'Cat','owner_name':'SYNTHETIC source owner','owner_email':'correction-source@example.test'})
        self.state['source_patient']=patient['id']
        document=b'SYNTHETIC approved mapping-correction document: '+self.state['tag'].encode()
        source_file=self.upload(patient['id'],'SYNTHETIC-approved-source.txt',document,approve=True)
        self.state.update(source_file=source_file['id'],source_file_sha256=binary_hash(document))
        consult=self.act('consultation.create', {'patient_id':patient['id'],'title':'SYNTHETIC original generated audio'})
        recording=self.act('recording.create', {'patient_id':patient['id'],'consultation_id':consult['id'],'device':'synthetic-generated-wave','mime':'audio/wav'})
        content=synthetic_audio()
        self.req('PUT','recordings/'+recording['id']+'/chunks/0',content=content)
        saved=self.act('recording.complete',{'id':recording['id'],'expected_chunks':1,'duration':1})
        self.act('recording.approve',{'id':recording['id'],'version':saved['version'],'approved':True})
        self.state.update(source_audio=recording['id'],source_audio_sha256=binary_hash(content))
        stock=self.act('inventory.create',{'name':'SYNTHETIC source test medication','unit':'test unit','stock':10,'price_cents':0})
        medication=self.act('medication.dispense',{'patient_id':patient['id'],'inventory_id':stock['id'],'version':stock['version'],'quantity':1,'dose':'SYNTHETIC source dose','frequency':'SYNTHETIC source frequency','instructions':'SYNTHETIC historical record; not for patient use'})
        self.state['source_medication']=medication['id']
        source_lab=self.lab(patient['id'],'source')
        self.act('clinical.approve',{'id':source_lab['id'],'approved':True})
        initial_grant=self.act('share.create',{'patient_id':patient['id']})['id']
        self.state['initial_grant']=initial_grant
        self.save()
        self.switch('target')
        for side in ('previous','corrected'):
            target=self.act('patient.create',{'name':'SYNTHETIC '+side+' receiving patient '+self.state['tag'],'species':'Cat','owner_name':'SYNTHETIC '+side+' primary owner'})
            extra=self.act('owner.create',{'name':'SYNTHETIC '+side+' additional owner'})
            target=self.act('patient.owners',{'id':target['id'],'version':target['version'],'owner_id':target['data']['owner_id'],'additional_owner_ids':[extra['id']]})
            self.act('source.add',{'patient_id':target['id'],'text':'SYNTHETIC independent '+side+' clinical text; preserve exactly.'})
            local_file=self.upload(target['id'],'SYNTHETIC-'+side+'-local.txt',('SYNTHETIC preserved '+side+' local bytes').encode())
            native=self.lab(target['id'],side)
            self.state.update({side+'_patient':target['id'],side+'_extra_owner':extra['id'],side+'_native':native['id'],side+'_local_file':local_file['id']})
            self.save()
        self.act('inventory.create',{'name':'SYNTHETIC receiving stock sentinel','unit':'test unit','stock':17,'price_cents':0})
        # Establish the deliberately old link only as clearly labelled synthetic API setup.
        initial=self.request(initial_grant)
        review=self.req('GET','transfers/'+initial['id']+'/preview',params={'target_patient_id':self.state['previous_patient']}).json()
        result=self.act('transfer.accept',{'id':initial['id'],'target_patient_id':self.state['previous_patient'],'expected_digest':review['digest'],'link_existing_patient':True,'acknowledge_existing_history':True,'patient_match_reason':'SYNTHETIC API baseline deliberately establishes the previous link for a correction rehearsal.'})
        self.check(result['id']==self.state['previous_patient'], 'synthetic API baseline is linked to the previous receiving patient')
        self.state['initial_result']=result
        self.switch('source')
        grant=self.act('share.create',{'patient_id':self.state['source_patient']})
        self.state.update(correction_grant=grant['id'],owner_url=self.base+grant['url'],workspace_url=self.base+'/app',phase='awaiting_owner_consent')
        self.save()
        self.check(not self.req('GET','owner/'+grant['id']+'/transfers').json(), 'fresh owner link has no correction request; browser consent is still required')
        print('NEXT: open owner_url from the private state file, choose target_clinic_name, opt into audio/medications and patient-link correction, then request transfer. Run --phase review.',flush=True)

    def capture(self, request):
        review=self.preview(request['id'])
        self.check(review['mapping_correction_required'] and review['mapping_correction']['previous_patient']['id']==self.state['previous_patient'], 'review shows the established old link and selected corrected destination')
        self.check(review['destination_patient']['id']==self.state['corrected_patient'], 'review targets only the synthetic corrected patient')
        for side,history in [('previous','previous_history'),('corrected','receiving_history')]:
            self.check(any(x['id']==self.state[side+'_native'] and x['data'].get('native_spine') for x in review['mapping_correction'][history]['existing_records']), 'review includes '+side+' patient native clinical facts')
        self.state.update(request_id=request['id'],review=review,receiving_before=self.records())
        self.state['native_before']={side:self.native(self.state[side+'_patient'],self.state[side+'_native']) for side in ('previous','corrected')}
        self.state['files_before']={x['id']:binary_hash(self.req('GET','files/'+x['id']).content) for x in self.state['receiving_before'] if x['kind']=='attachment'}
        self.state['audio_before']={x['id']:binary_hash(self.req('GET','recordings/'+x['id']+'/audio').content) for x in self.state['receiving_before'] if x['kind']=='recording'}
        self.save()

    def review(self):
        if self.state.get('phase') not in ('awaiting_owner_consent','reviewed','stale_rejected'):
            raise AssertionError('Review requires a prepared, unaccepted browser request')
        self.switch('target');request=self.current_request()
        self.check(request['status']=='pending','owner correction request remains pending for separate browser acceptance')
        self.capture(request);self.state['phase']='reviewed';self.save()
        print('NEXT: load the correction review in the browser. Run --phase stale before browser confirmation to exercise stale-review rejection.',flush=True)

    def stale(self):
        if self.state.get('phase')!='reviewed':
            raise AssertionError('Stale check requires --phase review and a pending browser correction')
        self.switch('target');request=self.current_request()
        self.check(request['status']=='pending','request is pending before deliberate synthetic stale edit')
        owner=self.row(self.state['corrected_extra_owner'])
        self.check(owner['data']['name'].startswith('SYNTHETIC '),'stale edit is restricted to this run’s synthetic additional owner')
        saved_review=self.state['review']
        self.act('owner.update',{'id':owner['id'],'version':owner['version'],**owner['data'],'name':owner['data']['name']+' · reviewed update'})
        before=self.records()
        self.act('transfer.accept',{'id':request['id'],'target_patient_id':self.state['corrected_patient'],'previous_patient_id':self.state['previous_patient'],'correct_mapping':True,'expected_digest':saved_review['digest'],'confirm_corrected_identity':True,'acknowledge_unresolved_history':True,'correction_reason':'SYNTHETIC rejected stale-preview probe; this command must never accept.'},expected=409)
        self.check(self.records()==before,'stale acceptance returns 409 with no record, receipt or stock changes')
        self.check(self.current_request()['status']=='pending','stale request remains pending')
        self.state['rejected_digest']=saved_review['digest']
        self.capture(request)
        self.check(self.state['review']['digest']!=saved_review['digest'],'new review digest reflects the reviewed-owner change')
        self.state['phase']='stale_rejected';self.save()
        print('NEXT: attempt the old browser review to see rejection, reload it, confirm identity/history, enter a reason, then accept. Run --phase readback.',flush=True)

    def readback(self):
        if self.state.get('phase') not in ('reviewed','stale_rejected','complete'):
            raise AssertionError('Readback requires a reviewed browser fixture')
        self.switch('target');request=self.current_request()
        self.check(request['status']=='accepted','owner-consented correction was accepted separately from this script')
        result=self.act('transfer.accept',{'id':request['id']})  # Receipt replay only, after accepted status readback.
        self.check(result['id']==self.state['corrected_patient'] and result['reconciliation_status']=='unresolved','accepted correction names the intended patient and leaves reconciliation unresolved')
        self.check(result['reviewed_digest']==self.state['review']['digest'],'accepted correction matches the final captured review')
        self.check(result['files_copied']==result['audio_copied']==result['medication_histories']==1,'current approved file, original audio and medication history are copied once')
        rows=self.records();current={x['id']:x for x in rows}
        self.check(all(current.get(x['id'])==x for x in self.state['receiving_before']),'all prior patients, owners, clinical records, media metadata and stock remain byte-for-byte unchanged')
        for side in ('previous','corrected'):
            self.check(self.native(self.state[side+'_patient'],self.state[side+'_native'])==self.state['native_before'][side],side+' native PostgreSQL event, observations and source receipt remain unchanged')
        for kind,route in [('files','files/'),('audio','recordings/')]:
            expected=self.state[kind+'_before']
            self.check(all(binary_hash(self.req('GET',route+id+('/audio' if kind=='audio' else '')).content)==value for id,value in expected.items()),'all prior '+kind+' preserve their exact original bytes')
        receipt=current[result['mapping_correction_id']]
        data=receipt['data'];review=self.state['review'];context=review['mapping_correction']
        self.check(receipt['kind']=='transfer_mapping_correction' and receipt['version']==1 and data['reviewed_digest']==review['digest'] and data['reviewed_by']==result['reviewed_by'],'immutable correction receipt records reviewer and accepted digest')
        self.check(data['previous_patient_id']==self.state['previous_patient'] and data['patient_id']==self.state['corrected_patient'] and data['clinical_equivalence_asserted'] is False and data['reconciliation_status']=='unresolved','receipt preserves both identities and explicitly makes no equivalence assertion')
        self.check(data['owner_consent_scope']==review['scope'],'receipt retains the exact explicitly granted owner scope')
        reviewed=[context['previous_patient'],*context['previous_owners'],*context['previous_history']['existing_records'],review['destination_patient'],*review['destination_owners'],*context['receiving_history']['existing_records']]
        # History review intentionally strips data.path. Compare receipt fingerprints
        # against the exact reviewed records, not unredacted bootstrap attachments.
        preserved=[{'id':x['id'],'kind':x['kind'],'version':x['version'],'fingerprint':fingerprint(x)} for x in reviewed]
        self.check(data['preserved_records']==preserved,'receipt fingerprints match the exact reviewed identities and sanitized histories')
        origins=[{'kind':x['kind'],'origin_id':x['origin_id'],'fingerprint':x['fingerprint']} for x in review['items']]
        self.check(data['current_origins']==origins,'receipt retains every accepted original source fingerprint')
        copied=[x for x in rows if x['data'].get('transfer_request_id')==request['id'] and x['kind']!='transfer_mapping_correction']
        self.check(copied and all(x['data'].get('patient_id')==self.state['corrected_patient'] for x in copied),'new clinical copies belong only to the corrected destination')
        self.check(all(not x['data'].get('approved') for x in copied if x['kind'] in ('event','attachment','recording')),'new clinical events and media start private to the receiving clinic')
        for kind,route,expected in [('attachment','files/',self.state['source_file_sha256']),('recording','recordings/',self.state['source_audio_sha256'])]:
            media=[x for x in copied if x['kind']==kind]
            self.check(len(media)==1 and binary_hash(self.req('GET',route+media[0]['id']+('/audio' if kind=='recording' else '')).content)==expected,'corrected destination receives exact approved '+kind+' bytes')
        self.check(not any(x['kind']=='medication' for x in rows),'receiving correction does not dispense medication')
        for kinds,label in [({'patient','owner'},'patients and owner links'),({'inventory','stock_movement','stock_lot','medication'},'stock and dispensing')]:
            before={x['id']:x for x in self.state['receiving_before'] if x['kind'] in kinds}
            after={x['id']:x for x in rows if x['kind'] in kinds}
            self.check(before==after,'correction neither creates nor changes '+label)
        for item in review['items']:
            origin=[x for x in copied if x['data'].get('origin_id')==item['origin_id'] and x['data'].get('origin_kind')==item['kind']]
            self.check(bool(origin) and all(x['data']['origin_fingerprint']==item['fingerprint'] and x['data']['origin_revision']==item['revision'] for x in origin),'corrected '+item['kind']+' copies retain the reviewed origin fingerprint and revision')
            payload=item['payload']
            if item['kind']=='medication':
                history=[x for x in origin if x['kind']=='medication_history']
                self.check(len(history)==1 and all(history[0]['data'].get(k)==v for k,v in payload.items()),'structured medication history preserves every supplied dose, quantity, instruction and date')
            elif item['kind']=='event':
                events=[x for x in origin if x['kind']=='event']
                self.check(len(events)==1 and events[0]['data']['occurred_at']==payload['occurred_at'] and events[0]['data']['body'].startswith(payload.get('body','')),'clinical narrative and original event date survive the corrected import')
                actual=[x['data'] for x in origin if x['kind']=='observation']
                expected=[{'name':o['name'],'code':o['concept'],'value':o['value'],'value_type':o['value_type'],'unit':o['unit'],'low':o.get('ref_low'),'high':o.get('ref_high'),'observed_at':payload['occurred_at']} for o in payload.get('observations',[])]
                self.check(len(actual)==len(expected) and all(any(all(row.get(k)==v for k,v in expected_row.items()) for row in actual) for expected_row in expected),'typed observations preserve exact values, units, reference bounds and original dates')
            elif item['kind']=='file':
                files=[x for x in origin if x['kind']=='attachment']
                self.check(len(files)==1 and all(files[0]['data'].get(k)==payload[k] for k in ('name','mime','size','sha256')),'file metadata retains exact source name, type, size and checksum')
        for side in ('previous','corrected'):
            notices=[x for x in rows if x['kind']=='event' and x['data'].get('patient_id')==self.state[side+'_patient'] and x['data'].get('transfer_mapping_correction_id')==receipt['id'] and x['data'].get('reconciliation_status')=='unresolved']
            self.check(len(notices)==1 and not notices[0]['data']['approved'] and 'must not be assumed to belong' in notices[0]['data']['body'],side+' patient has a private, explicit unresolved-history notice')
            timeline=self.req('GET','v2/patients/'+self.state[side+'_patient']+'/events/'+notices[0]['id']).json()
            self.check(timeline['summary']=='Unresolved history after patient-link correction' and bool(timeline['source']),side+' correction notice and source receipt are visible in PostgreSQL timeline')
        before_repeat=self.records()
        if 'repeat_request' not in self.state:
            repeat=self.request(self.state['correction_grant'])
            self.state['repeat_request']=repeat['id'];self.save()
        if 'repeat_result' not in self.state:
            pending=next(x for x in self.req('GET','owner/'+self.state['correction_grant']+'/transfers').json() if x['id']==self.state['repeat_request'])
            if pending['status']=='accepted':
                self.state['repeat_result']=self.act('transfer.accept',{'id':pending['id']})
            else:
                repeat_review=self.preview(pending['id'],correction=False)
                self.check(repeat_review['destination_patient']['id']==self.state['corrected_patient'] and repeat_review['counts']['new']==repeat_review['counts']['changed']==0,'normal repeat uses corrected mapping and finds only unchanged origins')
                self.state['repeat_result']=self.act('transfer.accept',{'id':pending['id'],'expected_digest':repeat_review['digest']})
            self.save()
        else:
            self.check(self.act('transfer.accept',{'id':self.state['repeat_request']})==self.state['repeat_result'],'repeat request receipt replay remains idempotent')
        self.check(self.state['repeat_result']['id']==self.state['corrected_patient'] and self.state['repeat_result']['counts']['new']==self.state['repeat_result']['counts']['changed']==0,'repeat receipt confirms the corrected patient and zero new or changed origins')
        self.check(self.records()==before_repeat,'normal repeat creates no duplicate patient, facts, media, notices or stock movement')
        self.state.update(result=result,receipt=receipt,phase='complete');self.save()

    def run(self):
        credentials=json.loads(self.args.credentials.read_text())
        login=self.req('POST','login',json={key:credentials[key] for key in ('username','password')}).json()
        try:
            self.check(self.req('GET','ready').json()['pms_store']=='postgres','isolated V2 PostgreSQL stores are ready')
            if self.args.phase=='prepare':self.prepare(login)
            else:
                if not self.state:raise AssertionError('Run --phase prepare first')
                getattr(self,self.args.phase)()
            self.save()
        finally:
            self.client.post('logout');self.client.close()
        print(f'{len(self.checks)} {self.args.phase} checks passed. Browser interaction evidence must be recorded separately.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url',nargs='?',default=V2_HOST)
    parser.add_argument('--credentials',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--phase',choices=['prepare','review','stale','readback'],required=True)
    parser.add_argument('--allow-local-test',action='store_true',help='Allow only a disposable loopback V2 fixture instead of the fixed hosted V2 URL')
    args=parser.parse_args()
    try:Rehearsal(args).run()
    except (AssertionError,httpx.RequestError) as exc:
        # Transport exceptions can include capability URLs. Do not print them.
        raise SystemExit(str(exc) if isinstance(exc,AssertionError) else 'The V2 API could not be reached; private capabilities were not printed.') from None


if __name__=='__main__':main()
