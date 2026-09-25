#!/usr/bin/env python3
"""Staged API setup/readback for fresh SYNTHETIC V2 clinician reconciliation.

Successful clinical.reconcile is NEVER called by this script. A clinician/browser
must inspect the complete evidence and choose each record disposition and reason.
No external messages, transcription, AI provider requests, or V1 access are made.
Uses smoke-transfer-corrections.py's guarded V2 client and private state writer.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import httpx

spec=importlib.util.spec_from_file_location('correction_smoke',Path(__file__).with_name('smoke-transfer-corrections.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


class Reconciliation(base.Rehearsal):
    def archive(self):
        return self.req('GET','export').json()['records']

    def clinical_review(self):
        return self.req('GET','clinical-reconciliation/'+self.state['correction_id']).json()

    def capture(self):
        review=self.clinical_review()
        self.check(bool(review['groups']) and bool(review['unresolved_legacy_records']), 'complete origin groups and unresolved legacy evidence are both visible')
        self.check(any(g['patient_id']==self.state['previous_patient'] and g['origin']['kind']=='file' for g in review['groups']), 'previous-patient file group can be reviewed independently')
        self.check(bool(review['known_onward_copies']), 'review identifies known independent onward copies')
        self.state['clinical_review']=review
        self.state['target_before']=self.archive()
        self.state['media_before']={r['id']:base.binary_hash(self.req('GET','files/'+r['id'] if r['kind']=='attachment' else 'recordings/'+r['id']+'/audio').content) for r in self.state['target_before'] if r['kind'] in ('attachment','recording')}
        self.switch('source');self.state['source_before']=self.archive();self.switch('target')
        self.save()

    def prepare(self, login):
        # Baseline mapping and correction are fixture setup, never clinician
        # adjudication. All patients/owners/clinics are created afresh by this run.
        super().prepare(login)
        self.switch('target')
        pending=self.request(self.state['correction_grant'],correction=True)
        review=self.preview(pending['id'])
        result=self.act('transfer.accept',{'id':pending['id'],'target_patient_id':self.state['corrected_patient'],'previous_patient_id':self.state['previous_patient'],'correct_mapping':True,'expected_digest':review['digest'],'confirm_corrected_identity':True,'acknowledge_unresolved_history':True,'correction_reason':'SYNTHETIC API fixture setup only. Historical clinical identity remains unresolved for separate browser adjudication.'})
        self.state['correction_id']=result['mapping_correction_id']
        old=self.state['previous_patient']
        records=self.records()
        copied=[r for r in records if r['data'].get('patient_id')==old and r['data'].get('origin_clinic_id')==self.state['source_clinic']]
        original_file=next(r for r in copied if r['kind']=='attachment')
        original_audio=next(r for r in copied if r['kind']=='recording')
        source=next(r for r in copied if r['kind']=='source' and r['data'].get('origin_kind')=='file')
        for row in (original_file,original_audio):self.act(row['kind']+'.approve',{'id':row['id'],'version':row['version'],'approved':True})
        consult=self.act('consultation.create',{'patient_id':old,'title':'SYNTHETIC derived history '+self.state['tag']})
        consult=self.act('summary.save',{'id':consult['id'],'version':consult['version'],'summary':[{'name':'Plan','text':'SYNTHETIC copied clinical wording; independent identity review is required.','source_ids':[source['id']]}]})
        consult=self.act('consultation.approve',{'id':consult['id'],'version':consult['version']})
        derivative=self.upload(old,'SYNTHETIC-derived-untraceable.txt',b'SYNTHETIC saved derivative without source lineage; do not infer patient identity.',approve=True)
        reminder=self.act('reminder.create',{'patient_id':old,'title':'SYNTHETIC historical clinical recall','due':'2099-01-05'})
        outbox=self.act('message.queue',{'patient_id':old,'body':'SYNTHETIC historical clinical message. Manual preview must be withheld after identity hold.'})
        old_grant=self.act('share.create',{'patient_id':old})['id']
        wrong_grant=self.act('share.create',{'patient_id':self.state['corrected_patient']})['id']
        # Deterministic guided action; no successful action confirmation or
        # external AI request. Persisted answer must later be qualified.
        answer=self.req('POST','assistant',json={'message':'start consultation','patient_id':old,'key':'synthetic-recon-'+self.state['tag']}).json()
        onward=self.req('POST','owner/'+old_grant+'/transfers',json={'target_clinic':self.state['source_clinic'],'consent':True,'include_audio':True,'include_medications':True}).json()
        self.switch('source');out_review=self.req('GET','transfers/'+onward['id']+'/preview').json()
        received=self.act('transfer.accept',{'id':onward['id'],'expected_digest':out_review['digest']})
        child_file=next(r for r in self.records() if r['kind']=='attachment' and r['data'].get('patient_id')==received['id'] and r['data'].get('origin_id')==original_file['id'])
        self.act('attachment.approve',{'id':child_file['id'],'version':child_file['version'],'approved':True})
        onward_grant=self.act('share.create',{'patient_id':received['id']})['id']
        self.state.update(original_file=original_file['id'],original_audio=original_audio['id'],derived_file=derivative['id'],derived_consultation=consult['id'],reminder_id=reminder['id'],outbox_id=outbox['id'],old_owner_grant=old_grant,wrong_owner_grant=wrong_grant,onward_patient=received['id'],onward_file=child_file['id'],onward_owner_grant=onward_grant,saved_answer=answer,owner_url=self.base+'/owner?token='+old_grant,onward_owner_url=self.base+'/owner?token='+onward_grant,patient_url=self.base+'/app#Patient/'+old,phase='awaiting_clinician_review')
        self.switch('target');self.capture()
        self.check(not self.clinical_review()['decisions'],'fresh fixture has no clinician dispositions')
        self.save()
        print('NEXT: select target_clinic_name in the workspace, open patient_url from private state, and inspect original evidence. Run --phase review, load browser review, then --phase stale before confirming. No successful clinician disposition has been submitted.',flush=True)

    def review(self):
        self.check(self.state['phase'] in ('awaiting_clinician_review','reviewed','awaiting_stale_browser_rejection'),'fixture is awaiting a separate clinician decision')
        self.switch('target');self.capture();self.state['phase']='reviewed';self.save()
        print('NEXT: load the review in the browser. Select the previous patient file group and inspect all source/receiving records. Run --phase stale before browser confirmation.',flush=True)

    def stale(self):
        self.check(self.state['phase']=='reviewed','a complete review was captured before the synthetic stale mutation')
        self.switch('target');owner=self.row(self.state['corrected_extra_owner'])
        self.check(owner['data']['name'].startswith('SYNTHETIC '),'only this fresh fixture owner is changed')
        old_digest=self.state['clinical_review']['digest']
        self.act('owner.update',{'id':owner['id'],'version':owner['version'],**owner['data'],'name':owner['data']['name']+' · stale review probe'})
        self.capture();self.check(old_digest!=self.state['clinical_review']['digest'],'review digest changed after the explicit synthetic owner edit')
        self.check(not self.clinical_review()['decisions'],'stale mutation created no clinician decision')
        self.state.update(phase='awaiting_stale_browser_rejection',rejected_digest=old_digest);self.save()
        print('NEXT: confirm the OLD browser review to see409. Reload; choices must clear. Inspect again and record individual clinician dispositions in the browser. Then run --phase readback.',flush=True)

    def readback(self):
        self.switch('target');review=self.clinical_review()
        receipts=[r for r in review['decisions'] if r['data']['correction_id']==self.state['correction_id']]
        self.check(bool(receipts),'clinician dispositions were recorded separately in the browser')
        self.check(any(d['patient_id']==self.state['previous_patient'] and d['disposition']=='wrong_patient' for r in receipts for d in r['data']['decisions']),'browser explicitly identified at least one previous-patient group as wrong-patient')
        self.check(all(r['data']['clinical_equivalence_asserted'] is False for r in receipts),'receipts make no inferred clinical-equivalence claim')
        self.check(any(r['data']['reviewed_digest']==self.state['clinical_review']['digest'] for r in receipts),'successful receipt matches the final captured complete review')
        current={r['id']:r for r in self.archive()}
        self.check(all(current.get(r['id'])==r for r in self.state['target_before']),'all pre-review receiving records remain unchanged')
        for id,sha in self.state['media_before'].items():
            row=current[id]
            if row['data'].get('patient_id')==self.state['previous_patient']:
                route='clinical-reconciliation/patients/'+self.state['previous_patient']+'/media/'+id+'?acknowledge_historical=true'
                response=self.req('GET',route);self.check(response.headers.get('x-broby-clinical-status')=='historical-unverified','historical media is explicitly qualified')
            else:response=self.req('GET','files/'+id if row['kind']=='attachment' else 'recordings/'+id+'/audio')
            self.check(base.binary_hash(response.content)==sha,'preserved media retains exact original bytes')
        bootstrap=self.req('GET','bootstrap').json()
        self.check(self.state['previous_patient'] in bootstrap['clinical_verification']['restricted_patients'] and self.state['corrected_patient'] not in bootstrap['clinical_verification']['restricted_patients'],'hold applies to previous patient and leaves separately unheld corrected patient visible')
        for route in ('files/'+self.state['original_file'],'recordings/'+self.state['original_audio']+'/audio','files/'+self.state['derived_file'],'consultations/'+self.state['derived_consultation']+'/pdf','consultations/'+self.state['derived_consultation']+'/text?version='+str(current[self.state['derived_consultation']]['version']),'outbox/'+self.state['outbox_id']+'/delivery-review'):
            self.req('GET',route,expected=409)
        self.check(True,'direct current media, derived files, PDF/text exports and manual delivery preview are blocked')
        for grant,expected in ((self.state['old_owner_grant'],409),(self.state['wrong_owner_grant'],404)):
            self.req('GET','owner/'+grant+'/files/'+self.state['original_file'],expected=expected)
            self.req('GET','owner/'+grant+'/audio/'+self.state['original_audio'],expected=expected)
        owner=self.req('GET','owner/'+self.state['old_owner_grant']).json()
        self.check(owner['clinical_review_notice'] and not owner['files'] and not owner['audio'],'authorized owner sees a hold notice without disputed media')
        self.req('GET','owner/'+self.state['old_owner_grant']+'/discharge.pdf',expected=409)
        answer=self.state['saved_answer'];turns=self.req('GET','assistant/conversations/'+answer['conversation_id']).json()['turns']
        self.check(any(t.get('clinical_reconciliation') and not t.get('action') for t in turns),'saved assistant answer/action is visibly withheld')
        self.req('POST','assistant/conversations/'+answer['conversation_id']+'/turns/'+answer['turn_id']+'/confirm',expected=409)
        consult=current[self.state['derived_consultation']]
        self.act('summary.generate',{'id':consult['id'],'version':consult['version']},expected=409)
        self.check(True,'new AI work and old assistant confirmation are rejected before provider use')
        self.switch('source');source={r['id']:r for r in self.archive()}
        self.check(all(source.get(r['id'])==r for r in self.state['source_before']),'original source and independent onward records remain unchanged')
        onward=self.req('GET','owner/'+self.state['onward_owner_grant']).json()
        self.check(onward['clinical_review_notice'] and not onward['files'],'known onward owner view remains restricted for separate receiving-clinic review')
        self.req('GET','files/'+self.state['onward_file'],expected=409)
        archive=self.req('GET','clinical-reconciliation/patients/'+self.state['onward_patient']+'/history').json()
        self.check(archive['status']=='unresolved' and archive['qualifications'] and not archive['current_clinical_use'],'independent receiving clinic retains qualified unresolved forensic access')
        self.state['phase']='complete';self.save()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url',nargs='?',default=base.V2_HOST)
    parser.add_argument('--credentials',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--phase',choices=('prepare','review','stale','readback'),required=True)
    parser.add_argument('--allow-local-test',action='store_true')
    args=parser.parse_args()
    try:Reconciliation(args).run()
    except (AssertionError,httpx.RequestError) as exc:
        raise SystemExit(str(exc) if isinstance(exc,AssertionError) else 'V2 API unavailable; private capability URLs were not printed.') from None


if __name__=='__main__':main()
