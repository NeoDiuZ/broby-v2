"""Clinic-scoped dictionary proposals; names and units never mutate historical concepts."""
import json,re
from db import record,get,update,all_records
PERMISSIONS={'ontology.propose':{'vet','nurse','admin'},'ontology.review':{'admin'}}

def definitions(c,clinic):
    terms={r['code']:dict(r) for r in c.execute('SELECT * FROM ontology')}
    for r in all_records(c,clinic,'ontology_definition'):terms[r['data']['code']]=r['data']
    return sorted(terms.values(),key=lambda r:(r['category'],r['name']))

def lookup(c,clinic,code):return next((r for r in definitions(c,clinic) if r['code']==code or code in r.get('aliases',[])),None)

def validate(p):
    from actions import require,fail
    code=require(p,'code');typ=require(p,'value_type');unit=p.get('unit','');aliases=p.get('aliases',[])
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,99}',code) or typ not in ('number','text','boolean'):fail('Invalid definition')
    if not isinstance(unit,str) or len(unit)>80 or (typ=='number' and not unit):fail('Numeric definitions need a unit')
    if not isinstance(aliases,list) or len(aliases)>30 or any(not isinstance(v,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,99}',v) for v in aliases):fail('Aliases must be stable codes')
    return {'code':code,'name':require(p,'name'),'value_type':typ,'unit':unit,'category':require(p,'category'),'aliases':sorted(set(aliases)),'definition_version':1}

def dispatch(c,a,p,clinic,actor):
    from actions import require,owned,version,fail
    if a=='ontology.propose':
        description=require(p,'description')
        if len(description)>2000:fail('Keep the definition description under 2000 characters')
        if p.get('use_ai'):
            import providers
            proposed=providers.model_json('Propose a dictionary entry, never a clinical fact or normal range. Return JSON with code (snake_case), name, value_type(number/text/boolean), unit, category, aliases(list of snake_case synonyms). Use only the requested meaning and unit. Do not convert units or infer normal ranges. The clinic administrator must accept this proposal.',{'request':description,'existing_definitions':definitions(c,clinic)})
        else:proposed=p.get('definition',{})
        definition=validate(proposed)
        return record(c,'ontology_proposal',clinic,{'description':description,'definition':definition,'status':'proposed','proposed_by':actor,'ai_assisted':bool(p.get('use_ai'))})
    if a=='ontology.review':
        r=owned(c,p['id'],clinic,'ontology_proposal');version(r,p)
        if r['data']['status']!='proposed':fail('Proposal already reviewed',409)
        status=p.get('status')
        if status not in ('accepted','rejected'):fail('Choose accepted or rejected')
        if status=='accepted':
            definition=validate(r['data']['definition']);codes={definition['code'],*definition['aliases']}
            for old in definitions(c,clinic):
                if codes & {old['code'],*old.get('aliases',[])}:fail('Code or alias already exists. Keep the existing definition or propose a new versioned code.',409)
            record(c,'ontology_definition',clinic,{**definition,'proposal_id':r['id'],'accepted_by':actor})
        return update(c,r,{**r['data'],'status':status,'reviewed_by':actor})
    fail('Unknown ontology action',404)
