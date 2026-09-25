"""Pin a continuous-speech fixture to its verified V2 host and membership.

Legacy states are recovered only by an exact, unique recording/consultation/patient
relationship in authorized clinics. Login defaults never select an existing fixture.
"""

BINDING_KEYS=('base_url','clinic','actor','binding_version')


def new_binding(base_url,clinic,actor):
    return {'base_url':base_url.rstrip('/'),'clinic':clinic,'actor':actor,'binding_version':1}


def bind_existing_fixture(state,base_url,memberships,history):
    """history(clinic,actor,recording_id) must return a same-clinic history or None404.

    Authentication/authorization/network failures must raise; they cannot prove a
    fixture is absent or justify falling back to a different clinic.
    """
    if any(not isinstance(state.get(k),str) or not state[k] for k in ('patient','consultation','recording')):
        raise AssertionError('Saved continuous fixture identity is incomplete; no audio or provider action was started')
    linked={entry['id']:entry.get('member_id') for entry in memberships if isinstance(entry,dict) and isinstance(entry.get('id'),str) and isinstance(entry.get('member_id'),str)}
    present=[key in state for key in BINDING_KEYS]
    if any(present) and not all(present):
        raise AssertionError('Saved fixture binding is incomplete; explicit review is required')
    bound=all(present)
    if bound:
        if state['binding_version']!=1 or state['base_url']!=base_url.rstrip('/'):
            raise AssertionError('Saved fixture belongs to a different host or binding version')
        if not isinstance(state['clinic'],str) or linked.get(state['clinic'])!=state['actor']:
            raise AssertionError('Saved fixture membership changed or is unavailable; no default-clinic fallback is allowed')
        candidates=[(state['clinic'],state['actor'])]
    else:
        candidates=sorted(linked.items())
    matches=[]
    for clinic,actor in candidates:
        result=history(clinic,actor,state['recording'])
        if result is None:continue
        row=result.get('current',{});data=row.get('data',{})
        if (row.get('id')==state['recording'] and row.get('kind')=='recording' and row.get('clinic_id')==clinic
            and data.get('patient_id')==state['patient'] and data.get('consultation_id')==state['consultation']
            and (not state.get('source') or data.get('transcript_source_id')==state['source'])):
            matches.append(new_binding(base_url,clinic,actor))
    if len(matches)!=1:
        raise AssertionError('Saved fixture has no unique verified clinic/recording relationship; no audio or provider action was started')
    return matches[0]
