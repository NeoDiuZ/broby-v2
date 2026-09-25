"""Local script phases against the real API/native store; model intent is stubbed.

Transport-only login/logout stubs keep this a local harness, not hosted or real
model acceptance. The scripted browser-save boundary is explicit below.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import httpx
import assistant,db
from test_spine import client
from test_integrity import act


def test_staged_visual_script_local_setup_evaluate_guides_and_readback(client,tmp_path,monkeypatch):
    path=Path(__file__).parents[2]/'scripts'/'smoke-assistant-visual-reads.py'
    spec=importlib.util.spec_from_file_location('visual_smoke',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with db.connection(True) as c:
        clinic=db.get(c,'clinic-east');db.update(c,clinic,{**clinic['data'],'name':'SYNTHETIC isolated chart script'})
    credentials=tmp_path/'credentials.json';credentials.write_text(json.dumps({'username':'synthetic','password':'synthetic-only'}))
    args=argparse.Namespace(base_url='http://testserver',credentials=credentials,state=tmp_path/'state.json',clinic='clinic-east',actor='clinic-east-admin',phase='setup')
    class Bridge:
        def __init__(self,**kwargs):self.headers=kwargs['headers']
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def request(self,method,path,**kwargs):
            if path in ('login','logout'):return httpx.Response(200,json={})
            return client.request(method,'/api/'+path,headers={k:v for k,v in self.headers.items() if k!='Origin'},**kwargs)
    setup=module.run(args,Bridge)
    assert setup['phase']=='setup' and len(setup['events'])==5 and args.state.stat().st_mode&0o777==0o600
    def intent(prompt,data):
        request=data['request'];patient=data['patient_id']
        if request.startswith('Open the dedicated review for '):return {'guide':request.split('for ',1)[1].split('. Do not',1)[0]}
        if request.startswith('Plot'):
            return {'read':{'kind':'observation','presentation':'trend','patient_id':patient,'code':'synthetic_trend_'+setup['tag'],'unit':'mmol/L','start':'2098-07-10','end':'2098-07-12'}}
        if data['literal_search_text']:return {'read':{'kind':'event','text_contains':data['literal_search_text']}}
        return {'read':{'kind':'observation' if 'observation record' in request else 'event','record_id':data['exact_record_id']}}
    monkeypatch.setattr(assistant.providers,'available',lambda:{'ai':True,'transcription':False})
    monkeypatch.setattr(assistant.providers,'model_json',intent)
    args.phase='evaluate';evaluated=module.run(args,Bridge)
    assert len(evaluated['answers'])==4 and evaluated['browser']['conversation_id']
    args.phase='guides';guided=module.run(args,Bridge);assert len(guided['guides'])==6
    # This is an API stand-in for the separate human browser save, never UI proof.
    dashboard=evaluated['answers']['trend']['dashboard']
    act('dashboard.save',{'name':dashboard['title'],'query':dashboard['query']},actor='clinic-east-admin')
    args.phase='readback';completed=module.run(args,Bridge)
    assert completed['phase']=='complete' and completed['saved_view_id']
    original=args.clinic;args.clinic='clinic-river'
    try:
        module.run(args,Bridge)
        raise AssertionError('Retargeted state must fail')
    except AssertionError as error:assert 'another target' in str(error)
    args.clinic=original
