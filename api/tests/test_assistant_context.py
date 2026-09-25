import json
import sqlite3
import assistant_context as context
import db


def records(count=1000):
    return [{'id':f'patient-{i}','kind':'patient','version':1,'data':{'name':f'Synthetic pet {i}','owner_id':f'owner-{i}','species':'Cat'}} for i in range(count)]+[{'id':f'owner-{i}','kind':'owner','version':1,'data':{'name':f'Synthetic owner {i}'}} for i in range(count)]


def test_large_clinic_context_keeps_exact_old_target_and_related_owner():
    chosen,scope=context.select(records(), 'Update patient-999 weight to 4.2 kg')
    assert len(chosen)<=context.MAX_RECORDS and scope['characters']<=context.MAX_CHARACTERS
    assert {'patient-999','owner-999'}<={r['id'] for r in chosen}
    assert scope['omitted_records']>0 and scope['selection_only'] is True


def test_patient_scope_and_exact_name_beat_unrelated_recent_records():
    chosen,_=context.select(records(), 'Synthetic owner 999 changed their phone number', 'patient-999')
    assert chosen[0]['id']=='owner-999'
    assert {'patient-999','owner-999'}<={r['id'] for r in chosen}


def test_large_source_fields_are_explicitly_omitted_never_truncated_as_facts():
    source={'id':'source-1','kind':'source','version':1,'data':{'patient_id':'patient-999','text':'EXACT '*10000,'title':'Original recording'}}
    chosen,scope=context.select([source,*records()], 'Read source-1', 'patient-999')
    receipt=next(r for r in chosen if r['id']=='source-1')
    assert 'text' not in receipt['data'] and receipt['omitted_fields']==['text']
    assert scope['omitted_large_fields']==1 and scope['characters']<=context.MAX_CHARACTERS


def test_small_context_retains_metadata_and_never_mutates_sources():
    source=records(4);before=json.dumps(source,sort_keys=True)
    selected,scope=context.select(source,'Show patient count')
    assert len(selected)==len(source) and scope['omitted_records']==0
    assert json.dumps(source,sort_keys=True)==before


def test_database_candidates_keep_old_exact_target_without_loading_history():
    c=sqlite3.connect(':memory:',factory=db.TransactionConnection)
    c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT,clinic_id TEXT,data TEXT,version INTEGER,created_at TEXT,updated_at TEXT)')
    old=db.record(c,'patient','clinic-east',{'name':'SYNTHETIC Ancient Pet','species':'Cat','owner_id':'ancient-owner'},'ancient-pet')
    db.record(c,'owner','clinic-east',{'name':'SYNTHETIC Ancient Owner'},'ancient-owner')
    c.execute("UPDATE records SET created_at='2000-01-01' WHERE id IN ('ancient-pet','ancient-owner')")
    for i in range(600):
        db.record(c,'source','clinic-east',{'patient_id':f'other-{i}','title':f'Unrelated source {i}','text':'private clinical history'},f'source-{i}')
    db.record(c,'patient','clinic-river',{'name':'SYNTHETIC Ancient Pet','species':'Dog'},'foreign-pet')
    candidates,total=context.candidates(c,'clinic-east','Update SYNTHETIC Ancient Pet',old['id'],(old,))
    ids={row['id'] for row in candidates}
    assert total==602 and 'ancient-pet' in ids and 'ancient-owner' in ids and 'foreign-pet' not in ids
    assert len(candidates)<total
    selected,scope=context.select([{'id':r['id'],'kind':r['kind'],'version':r['version'],'data':r['data']} for r in candidates],
                                  'Update SYNTHETIC Ancient Pet',old['id'],available_records=total)
    assert {'ancient-pet','ancient-owner'}<={r['id'] for r in selected}
    assert scope['available_records']==total and scope['omitted_records']>0
    c.close()
