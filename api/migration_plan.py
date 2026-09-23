"""Deterministic clinical migration rehearsal with explicit identity mapping and replay checks."""
import copy,hashlib,json,uuid
from db import get,record,all_records
PERMISSIONS={'migration.preview':{'admin'},'migration.apply':{'admin'}}

def plan(c,clinic,p):
    from actions import fail,require
    from import_validation import validate
    source=require(p,'source_system');items=copy.deepcopy(p.get('records'))
    if not isinstance(items,list) or not 1<=len(items)<=5000:fail('Provide 1–5000 clinical records')
    kinds={'owner','patient','source','event','observation','consultation','template','reminder'}
    if any(not isinstance(r,dict) or r.get('kind') not in kinds or not isinstance(r.get('data'),dict) or not isinstance(r.get('id'),str) or not r['id'] for r in items):fail('Only complete clinical records are supported; financial and stock imports require an agreed reconciliation contract')
    if len({r['id'] for r in items})!=len(items):fail('Duplicate source IDs')
    mapping={r['id']:str(uuid.uuid5(uuid.NAMESPACE_URL,clinic+':'+source+':'+r['id'])) for r in items}
    known={r['id']:r for r in all_records(c,clinic)}
    fields={'owner_id':'owner','patient_id':'patient','source_id':'source','consultation_id':'consultation','template_id':'template'}
    for r in items:
        original=r['id'];r['id']=mapping[original]
        d=r['data'];d['migration_origin']={'source_system':source,'source_id':original}
        for f in fields:
            if d.get(f):d[f]=mapping.get(d[f],d[f])
        for f in ('source_ids','additional_owner_ids'):
            if f in d:d[f]=[mapping.get(v,v) for v in d[f]]
        for section in d.get('summary',[]):section['source_ids']=[mapping.get(v,v) for v in section.get('source_ids',[])]
        if r['kind']=='patient':d['external_id']=source+':'+original
    by_id={**known,**{r['id']:r for r in items}}
    for r in items:
        for f,kind in fields.items():
            target=r['data'].get(f)
            if target and (target not in by_id or by_id[target]['kind']!=kind):fail('Missing or cross-clinic '+f)
        for oid in r['data'].get('additional_owner_ids',[]):
            if oid not in by_id or by_id[oid]['kind']!='owner':fail('Invalid additional owner identity')
        for sid in r['data'].get('source_ids',[]):
            if sid not in by_id or by_id[sid]['kind']!='source' or by_id[sid]['data'].get('patient_id')!=r['data'].get('patient_id'):fail('Invalid patient source receipt')
    validate(items,by_id)
    counts={};unchanged=0;new=[]
    for r in items:
        counts[r['kind']]=counts.get(r['kind'],0)+1
        old=get(c,r['id'])
        if old:
            if old['clinic_id']!=clinic or old['kind']!=r['kind'] or old['data']!=r['data']:fail('Source identity already exists with different content. Reconcile explicitly; no records were overwritten.',409)
            unchanged+=1
        else:new.append(r)
    digest=hashlib.sha256(json.dumps({'clinic':clinic,'source':source,'records':items},sort_keys=True).encode()).hexdigest()
    return {'digest':digest,'mapping':mapping,'counts':counts,'new_count':len(new),'unchanged_count':unchanged,'new_records':new,'financial_import':False,'media_import':False}

def dispatch(c,a,p,clinic,actor):
    from actions import fail
    preview=plan(c,clinic,p)
    if a=='migration.apply':
        if p.get('expected_digest')!=preview['digest']:fail('Preview changed. Review the current migration plan first.',409)
        for item in preview['new_records']:record(c,item['kind'],clinic,item['data'],item['id'])
    return {'id':preview['digest'],**{k:v for k,v in preview.items() if k!='new_records'},'applied':a=='migration.apply'}
