"""Reviewed V1 consultation text imports preserve identity and private receipts."""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
import main
from test_integrity import act, err, get, isolated, rows
from v1_consultation_mapping import FIELDS, MappingError, prepare

SOURCE = '11111111-1111-4111-8111-111111111111'
FIRST = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
SECOND = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
THREAD = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'


def consultation(id=FIRST, **changes):
    row = {field: None for field in FIELDS}
    row.update(id=id, clinic_id=SOURCE, veterinarian_id='dddddddd-dddd-4ddd-8ddd-dddddddddddd',
               patient_id=THREAD, patient_name='SYNTHETIC Historical Luna', patient_species='Cat',
               owner_name='SYNTHETIC Legacy Owner', status='reviewed',
               consultation_date='2025-06-04T10:30:00+08:00', chief_complaint='Exact V1 complaint.',
               physical_exam='Exact V1 examination.', ai_diagnosis_suggestions='Historical AI suggestion; do not treat as diagnosis.',
               summary_language='en', created_at='2025-06-04T09:00:00+08:00',
               updated_at='2025-06-04T11:00:00+08:00',
               recording_session_ids=[], recording_count=0, custom_fields={'legacy': 'exact'},
               consultation_metadata={})
    return {**row, **changes}


def crosswalk(*ids, existing=None):
    patient = ({'key':'reviewed-luna', 'reason':'Staff reviewed original patient and owner identities.',
                'target_patient_id':existing['id'], 'target_name':existing['data']['name'],
                'target_species':existing['data']['species'], 'target_version':existing['version']}
               if existing else
               {'key':'reviewed-luna', 'reason':'Staff reviewed original patient and owner identities.',
                'name':'SYNTHETIC Historical Luna', 'species':'Cat',
                'owner_name':'SYNTHETIC Legacy Owner', 'reviewed_status':'active'})
    return {'source_clinic_id':SOURCE, 'target_clinic_id':'clinic-east',
            'reviewer':'clinic-east-admin', 'reviewed_at':'2026-09-25T09:00:00+08:00',
            'patients':[patient],
            'consultations':[{'id':id, 'patient_key':'reviewed-luna',
                              'reason':'Reviewed source identity and original visit chronology.'} for id in ids]}


def payload(prepared):
    return {k:prepared[k] for k in ('source_system','target_clinic_id','reference_assertions','records')}


def test_two_historical_consultations_use_one_reviewed_provisional_patient_without_publishing_ai_text():
    prepared = prepare([consultation(), consultation(SECOND, patient_id=None, patient_name='SYNTHETIC Luna prior name')],
                       crosswalk(FIRST, SECOND))
    assert prepared['review']['consultations']==2
    assert prepared['review']['missing_v1_thread_ids']==1
    assert prepared['review']['historical_ai_suggestions_for_review']==2
    preview=act('migration.preview',payload(prepared),actor='clinic-east-admin')
    assert preview['counts']=={'owner':1,'patient':1,'source':2,'event':2}
    assert not preview['existing_references']
    applied=act('migration.apply',{**payload(prepared),'expected_digest':preview['digest']},actor='clinic-east-admin')
    patient=get(applied['mapping']['patient:reviewed-luna'])
    assert patient['data']['owner_id']==applied['mapping']['owner:reviewed-luna']
    sources=[get(applied['mapping']['source:'+id]) for id in (FIRST,SECOND)]
    events=[get(applied['mapping']['event:'+id]) for id in (FIRST,SECOND)]
    assert all(r['data']['patient_id']==patient['id'] for r in sources+events)
    assert all(not r['data']['approved'] and r['data']['source_ids']==[s['id']]
               for r,s in zip(events,sources))
    assert 'Historical AI suggestions (not a V2 clinical conclusion)' in sources[0]['data']['text']
    assert sources[0]['data']['v1_original']['chief_complaint']=='Exact V1 complaint.'
    assert sources[1]['data']['v1_original']['patient_id'] is None
    assert all(r['data'].get('migration_origin',{}).get('source_system')!=prepared['source_system']
               for r in rows('consultation'))
    grant=act('share.create',{'patient_id':patient['id']})
    owner_view=TestClient(main.app).get('/api/owner/'+grant['id']).json()
    assert owner_view['events']==[]
    assert set(owner_view['patient']['data']) <= {'name','species','breed','sex','age','weight','date_of_birth','microchip_id','color'}
    assert 'Historical AI suggestion' not in json.dumps(owner_view)
    assert act('migration.preview',payload(prepared),actor='clinic-east-admin')['unchanged_count']==6


def test_existing_v2_patient_requires_exact_clinic_identity_and_fresh_review():
    current=get('luna')
    prepared=prepare([consultation()],crosswalk(FIRST,existing=current))
    data=payload(prepared)
    preview=act('migration.preview',data,actor='clinic-east-admin')
    assert preview['counts']=={'source':1,'event':1}
    assert [(r['id'],r['kind']) for r in preview['existing_references']]==[('luna','patient')]
    err(409,lambda:act('migration.preview',{**data,'target_clinic_id':'clinic-river'},actor='clinic-east-admin'))
    with db.connection(True) as c:
        patient=db.get(c,'luna')
        db.update(c,patient,{**patient['data'],'name':'Luna changed during consultation review'})
    err(409,lambda:act('migration.apply',{**data,'expected_digest':preview['digest']},actor='clinic-east-admin'))
    assert not get(preview['mapping']['source:'+FIRST])


def test_duplicate_names_do_not_merge_distinct_reviewed_patient_keys():
    review=crosswalk(FIRST)
    review['patients'].append({**review['patients'][0], 'key':'separate-animal'})
    review['consultations'].append({'id':SECOND, 'patient_key':'separate-animal',
                                    'reason':'Reviewed same names but confirmed a distinct animal.'})
    prepared=prepare([consultation(),consultation(SECOND,patient_id=None)],review)
    preview=act('migration.preview',payload(prepared),actor='clinic-east-admin')
    applied=act('migration.apply',{**payload(prepared),'expected_digest':preview['digest']},actor='clinic-east-admin')
    first=get(applied['mapping']['patient:reviewed-luna'])
    second=get(applied['mapping']['patient:separate-animal'])
    assert first['id']!=second['id'] and first['data']['owner_id']!=second['data']['owner_id']
    assert get(applied['mapping']['event:'+FIRST])['data']['patient_id']==first['id']
    assert get(applied['mapping']['event:'+SECOND])['data']['patient_id']==second['id']


@pytest.mark.parametrize('change,review_change',[
    ({'clinic_id':'22222222-2222-4222-8222-222222222222'},None),
    ({'recording_session_ids':['eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee']},None),
    ({'consultation_metadata':{'attachments':['private-file']}},None),
    ({'deleted_at':'2025-06-05T00:00:00+08:00'},None),
    ({'status':'unknown'},None),
    ({'patient_species':'Dog'},None),
    ({'new_unknown_column':'must not disappear'},None),
    ({'consultation_date':'2025-06-04'},None),
    ({'chief_complaint':{'text':'not a string'}},None),
    ({}, {'consultations':[]}),
    ({}, {'patients':[{'key':'reviewed-luna','reason':'Staff reviewed original identity.',
                       'name':'SYNTHETIC Historical Luna','species':'Cat',
                       'owner_name':'SYNTHETIC Legacy Owner','reviewed_status':'deceased'}]}),
])
def test_unreviewed_or_incomplete_v1_consultations_never_prepare_a_partial_import(change,review_change):
    review=crosswalk(FIRST)
    if review_change:
        review.update(review_change)
    with pytest.raises(MappingError):
        prepare([consultation(**change)],review)
    assert not [r for r in rows('source') if r['data'].get('migration_origin',{}).get('source_system','').startswith('broby-v1:consultations-text')]


def test_converter_writes_private_preview_and_refuses_overwrite(tmp_path):
    export=tmp_path/'approved-synthetic-consultations.json'
    review=tmp_path/'reviewed-synthetic-crosswalk.json'
    output=tmp_path/'private-preview.json'
    export.write_text(json.dumps([consultation()]))
    review.write_text(json.dumps(crosswalk(FIRST)))
    script=Path(__file__).resolve().parents[2]/'scripts/prepare-v1-consultations.py'
    command=[sys.executable,str(script),str(export),str(review),str(output)]
    assert subprocess.run(command,capture_output=True,text=True).returncode==0
    assert os.stat(output).st_mode & 0o777==0o600
    assert json.loads(output.read_text())['review']['consultations']==1
    assert subprocess.run(command,capture_output=True,text=True).returncode!=0


def test_csv_export_preserves_multiline_historical_text(tmp_path):
    export=tmp_path/'approved-synthetic-consultations.csv'
    review=tmp_path/'reviewed-synthetic-crosswalk.json'
    output=tmp_path/'private-preview.json'
    row=consultation(chief_complaint='Exact V1 complaint, first line.\nSecond line.')
    with export.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=sorted(FIELDS))
        writer.writeheader()
        writer.writerow({**row,'recording_session_ids':'[]',
                         'custom_fields':json.dumps(row['custom_fields']),
                         'consultation_metadata':'{}'})
    review.write_text(json.dumps(crosswalk(FIRST)))
    script=Path(__file__).resolve().parents[2]/'scripts/prepare-v1-consultations.py'
    result=subprocess.run([sys.executable,str(script),str(export),str(review),str(output)],capture_output=True,text=True)
    assert result.returncode==0, result.stderr
    prepared=json.loads(output.read_text())
    source=next(r for r in prepared['records'] if r['kind']=='source')
    assert source['data']['v1_original']['chief_complaint']==row['chief_complaint']
    assert row['chief_complaint'] in source['data']['text']
