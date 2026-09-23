"""Normalize clinical imports before the transaction writes any records."""
from datetime import date

def validate(items, by_id):
    from actions import fail,number,integer
    defaults={
        'owner':{'email':'','phone':''},
        'patient':{'breed':'','sex':'Unknown','weight':0,'age':'','external_id':''},
        'source':{'title':'Imported source','section':'Subjective','category':'clinical','author':'Imported','consultation_id':None},
        'event':{'source_ids':[],'approved':False,'occurred_at':date.today().isoformat()},
        'observation':{'low':None,'high':None,'category':'Clinical','value_type':'number'},
        'consultation':{'title':'Imported consultation','status':'in_progress','summary':[],'source_ids':[],'input_revision':0,'generated_revision':0,'date':date.today().isoformat()},
        'reminder':{'status':'due'},'template':{},
    }
    required={'owner':['name'],'patient':['name','species','owner_id'],'source':['patient_id','text'],'event':['patient_id','category','title','body'],'observation':['patient_id','name','source_id','value'],'consultation':['patient_id','template_id'],'reminder':['patient_id','title','due'],'template':['name','sections']}
    for r in items:
        kind=r['kind'];d=r['data'];r['data']={**defaults[kind],**d};d=r['data']
        if not isinstance(r['id'],str) or not r['id'].strip():fail('Record IDs must be non-empty strings')
        for key in required[kind]:
            if key not in d or d[key] is None or (isinstance(d[key],str) and not d[key].strip()):fail(f'Missing {key} on {r["id"]}')
        for key in ('source_id','consultation_id'):
            target=by_id.get(d.get(key))
            if target and target['data'].get('patient_id')!=d.get('patient_id'):fail('Cross-patient clinical reference')
        if kind=='patient':d['weight']=number(d['weight'],'Weight')
        if kind=='source' and not isinstance(d['text'],str):fail('Source text must be text')
        if kind=='event':d['approved']=False # Imports require explicit review before owner sharing.
        if kind=='observation':
            if d['value_type']=='number':
                d['value']=number(d['value'],'Observation',-1e9)
                if not isinstance(d.get('unit'),str) or not d['unit'].strip():fail('Numeric observations need a unit')
                for key in ('low','high'):
                    if d[key] is not None:d[key]=number(d[key],'Reference range',-1e9)
                if d['low'] is not None and d['high'] is not None and d['low']>d['high']:fail('Invalid reference range')
            elif d['value_type']=='text':
                if not isinstance(d['value'],str):fail('Text observation required')
                d['unit']=d.get('unit','')
            elif d['value_type']=='boolean':
                if type(d['value']) is not bool:fail('Boolean observation required')
                d['unit']=''
            else:fail('Invalid observation type')
        if kind=='template' and (not isinstance(d['sections'],list) or not d['sections'] or not all(isinstance(x,str) and x.strip() for x in d['sections'])):fail('Template sections must be a non-empty list of names')
        if kind=='consultation':
            d['status']='in_progress';d['input_revision']=integer(d['input_revision'],'Input revision');d['generated_revision']=integer(d['generated_revision'],'Generated revision')
            if not isinstance(d['summary'],list):fail('Summary must be a list of sections')
            for section in d['summary']:
                if not isinstance(section,dict) or not isinstance(section.get('name'),str) or not isinstance(section.get('text'),str):fail('Invalid summary section')
                for sid in section.get('source_ids',[]):
                    target=by_id.get(sid)
                    if not target or target['kind']!='source' or target['data'].get('patient_id')!=d['patient_id']:fail('Invalid summary receipt')
        if kind in ('consultation','reminder'):
            try:date.fromisoformat(d['date'] if kind=='consultation' else d['due'])
            except (ValueError,TypeError):fail('Invalid record date')
