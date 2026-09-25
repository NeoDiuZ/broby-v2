"""Acceptance state must survive login-default drift without crossing clinic scope."""
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('continuous_fixture',Path(__file__).resolve().parents[2]/'scripts/continuous_fixture.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
BASE='https://v2.example.test'
STATE={'patient':'synthetic-patient','consultation':'synthetic-consultation','recording':'synthetic-recording','source':'synthetic-source'}
MEMBERS=[{'id':'clinic-new-default','member_id':'new-admin'},{'id':'clinic-original','member_id':'original-admin'}]


def row(clinic):
    return {'current':{'id':STATE['recording'],'kind':'recording','clinic_id':clinic,'data':{'patient_id':STATE['patient'],'consultation_id':STATE['consultation'],'transcript_source_id':STATE['source']}}}


def test_legacy_state_recovers_exact_original_clinic_after_new_default_is_added():
    calls=[]
    def history(clinic,actor,id):
        calls.append((clinic,actor,id));return row(clinic) if clinic=='clinic-original' else None
    result=helper.bind_existing_fixture(STATE,BASE,MEMBERS,history)
    assert result==helper.new_binding(BASE,'clinic-original','original-admin')
    assert len(calls)==2 and STATE=={'patient':'synthetic-patient','consultation':'synthetic-consultation','recording':'synthetic-recording','source':'synthetic-source'}


def test_persisted_binding_never_follows_current_login_default():
    state={**STATE,**helper.new_binding(BASE,'clinic-original','original-admin')};calls=[]
    def history(clinic,actor,id):calls.append(clinic);return row(clinic)
    assert helper.bind_existing_fixture(state,BASE,MEMBERS,history)['clinic']=='clinic-original'
    assert calls==['clinic-original']


@pytest.mark.parametrize('change',[{'base_url':'https://other.example.test'},{'clinic':'clinic-missing'},{'actor':'different-admin'},{'binding_version':2}])
def test_changed_host_membership_or_binding_version_fails_before_fixture_reads(change):
    state={**STATE,**helper.new_binding(BASE,'clinic-original','original-admin'),**change}
    with pytest.raises(AssertionError):helper.bind_existing_fixture(state,BASE,MEMBERS,lambda *_:pytest.fail('Unsafe fixture read'))


@pytest.mark.parametrize('field',['patient_id','consultation_id','transcript_source_id'])
def test_recording_must_match_every_saved_identity_reference(field):
    def history(clinic,*_):
        result=row(clinic);result['current']['data'][field]='other-fixture';return result
    with pytest.raises(AssertionError,match='no unique'):helper.bind_existing_fixture(STATE,BASE,MEMBERS,history)


def test_ambiguous_legacy_binding_never_chooses_the_first_clinic():
    with pytest.raises(AssertionError,match='no unique'):helper.bind_existing_fixture(STATE,BASE,MEMBERS,lambda clinic,*_:row(clinic))


def test_unavailable_bound_fixture_does_not_search_another_clinic():
    calls=[]
    def history(clinic,*_):calls.append(clinic);return None
    with pytest.raises(AssertionError,match='no unique'):helper.bind_existing_fixture({**STATE,**helper.new_binding(BASE,'clinic-original','original-admin')},BASE,MEMBERS,history)
    assert calls==['clinic-original']


def test_incomplete_binding_and_unreadable_clinic_do_not_silently_recover():
    with pytest.raises(AssertionError,match='incomplete'):helper.bind_existing_fixture({**STATE,'clinic':'clinic-original'},BASE,MEMBERS,lambda *_:pytest.fail('Partial binding must fail'))
    def denied(*_):raise PermissionError('Denied')
    with pytest.raises(PermissionError):helper.bind_existing_fixture(STATE,BASE,MEMBERS,denied)
