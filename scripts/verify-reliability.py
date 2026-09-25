#!/usr/bin/env python3
"""Reproducible local HTTP load, process-loss and complete restore acceptance.

Creates its own database, authenticated API process and synthetic files. It can
never target a hosted deployment. Provider calls and outgoing messages are off.
"""
import argparse, hashlib, json, os, secrets, socket, subprocess, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv/bin/python'
if not PYTHON.is_file():
    PYTHON=Path(sys.executable)
p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
p.add_argument('--patients',type=int,default=1000)
p.add_argument('--requests',type=int,default=160)
p.add_argument('--concurrency',type=int,default=8)
p.add_argument('--skip-restore',action='store_true',help='Run load and crash recovery without the separate backup/restore drill')
a=p.parse_args()
if not 20<=a.patients<=20000 or not 8<=a.requests<=5000 or not 2<=a.concurrency<=32:
    raise SystemExit('Use 20–20000 patients, 8–5000 requests, 2–32 concurrent clients')
out=a.output.resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
source_url=make_url(os.environ.get('BROBY_TEST_SPINE_URL') or dotenv_values(ROOT/'.env')['BROBY_SPINE_URL'])
if source_url.host not in ('localhost','127.0.0.1','::1'):raise SystemExit('Only a local disposable PostgreSQL target is allowed')
name='broby_accept_'+uuid.uuid4().hex[:16]
url=source_url.set(database=name)
admin=create_engine(source_url.set(database='postgres'),isolation_level='AUTOCOMMIT')
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}/api/'
password=secrets.token_urlsafe(32)
env={**os.environ,'PYTHONPATH':str(ROOT/'api'),'BROBY_SPINE_URL':url.render_as_string(hide_password=False),
     'BROBY_PMS_URL':url.render_as_string(hide_password=False),'BROBY_PMS_STORE':'postgres','BROBY_PMS_SCHEMA':'broby_pms',
     'BROBY_DATA_DIR':str(out/'data'),'BROBY_ENVIRONMENT':'local','BROBY_AUTH_MODE':'password',
     'BROBY_ADMIN_USERNAME':'synthetic-reliability','BROBY_ADMIN_PASSWORD':password,
     'BROBY_ALLOWED_ORIGINS':base.removesuffix('/api/'),'BROBY_ENABLE_AI':'0','BROBY_SEED_DEMO':'1',
     'BROBY_BACKUP_API_URL':base+'health',
     'BROBY_STRIPE_SECRET_KEY':'','STRIPE_SECRET_KEY':'','TWILIO_ACCOUNT_SID':'','BROBY_TWILIO_SEND_ENABLED':'0'}
# Remove inherited integration credentials rather than accidentally scheduling a provider.
for key in list(env):
    if ('STRIPE' in key or 'TWILIO' in key or key in ('ANTHROPIC_API_KEY','DEEPGRAM_API_KEY')) and key not in ('BROBY_TWILIO_SEND_ENABLED',):env.pop(key,None)
report={'scope':'Local isolated PostgreSQL + real HTTP; synthetic data; providers disabled',
        'patients_added':a.patients,'concurrency':a.concurrency,'requests':a.requests,'checks':[]}
process=None;created=False


def check(value,label):
    if not value:raise AssertionError(label)
    report['checks'].append(label);print('PASS '+label,flush=True)
    (out/'results.json').write_text(json.dumps(report,indent=2))


def python(code):
    result=subprocess.run([str(PYTHON),'-c',code],cwd=ROOT,env=env,capture_output=True,text=True)
    if result.returncode:
        (out/'subprocess-error.txt').write_text(result.stderr)
        raise RuntimeError('Isolated fixture process failed; see private subprocess-error.txt')
    return json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else None


def start(hold=False):
    global process
    runner="import uvicorn,main;uvicorn.run(main.app,host='127.0.0.1',port="+str(port)+",log_level='warning')"
    if hold:
        runner="import jobs,time;from pathlib import Path\ndef held(*args):\n Path("+repr(str(out/'claimed'))+").write_text('claimed')\n while True:time.sleep(1)\njobs.run_claimed=held\n"+runner
    with (out/'server.log').open('ab') as log:
        process=subprocess.Popen([str(PYTHON),'-c',runner],cwd=ROOT,env=env,stdout=log,stderr=log)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Isolated API stopped during startup')
        try:
            if httpx.get(base+'ready',timeout=2).status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(.2)
    raise RuntimeError('Isolated API readiness timed out')


def stop(kill=False):
    global process
    if process and process.poll() is None:
        process.kill() if kill else process.terminate()
        process.wait(timeout=20)
    process=None


try:
    with admin.connect() as c:c.exec_driver_sql('CREATE DATABASE '+name)
    created=True
    migrated=subprocess.run([str(PYTHON),'-m','spine.migrate'],cwd=ROOT/'api',env=env,capture_output=True)
    if migrated.returncode:raise RuntimeError('Isolated clinical migration failed')
    python('''import db,auth,json
from datetime import datetime
from zoneinfo import ZoneInfo
from spine.projection import setup_queue
db.init();auth.setup_tables();setup_queue()
with db.connection(True) as c:
 today=datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
 for i in range('''+str(a.patients)+'''):
  owner=db.record(c,'owner','clinic-east',{'name':f'SYNTHETIC Load owner {i}','email':'','phone':''})
  patient=db.record(c,'patient','clinic-east',{'name':f'SYNTHETIC Load pet {i:05}','species':'Cat','owner_id':owner['id'],'weight':4.2,'breed':'','sex':'Unknown','age':''})
  source=db.record(c,'source','clinic-east',{'patient_id':patient['id'],'text':'Exact synthetic load finding.','title':'Synthetic source','category':'clinical','section':'Subjective','author':'Synthetic operator'})
  db.event(c,'clinic-east',patient['id'],'clinical','Synthetic event','Exact synthetic load finding.',[source['id']])
  if i%10==0:
   db.record(c,'appointment','clinic-east',{'patient_id':patient['id'],'date':today,'time':'09:00','duration':30,'status':'scheduled','clinician':'synthetic-scale-vet','reason':'SYNTHETIC load appointment'})
   db.record(c,'outbox','clinic-east',{'patient_id':patient['id'],'status':'pending','body':'SYNTHETIC unsent load draft'})
  if i%20==0:
   db.record(c,'inventory','clinic-east',{'name':f'SYNTHETIC load stock {i}','unit':'pack','stock':1,'reorder':2})
print(json.dumps({'seeded':True}))''')
    start(hold=True)
    with httpx.Client(base_url=base,timeout=60) as client:
        def req(method,route,expected=200,**kw):
            r=client.request(method,route,**kw)
            if r.status_code!=expected:raise AssertionError((method,route.split('/')[0],r.status_code))
            return r.json()
        def action(name,payload,key=None):return req('POST','actions',json={'action':name,'payload':payload,'key':key or str(uuid.uuid4())})
        check(httpx.get(base+'bootstrap').status_code==401,'anonymous access rejected')
        req('POST','login',json={'username':'synthetic-reliability','password':password})
        check(client.get('bootstrap',headers={'x-clinic-id':'clinic-river'}).status_code==403,'cross-clinic access rejected under real password sessions')
        initial=req('GET','bootstrap')
        check(len([r for r in initial['records'] if r['kind']=='patient'])==a.patients+8,'all synthetic patients available through authenticated bootstrap')
        original={r['id']:r for r in initial['records'] if r['id'] in ('milo','luna','bella-cat','owner-milo')}
        patient=action('patient.create',{'name':'SYNTHETIC Recovery patient','species':'Cat','owner_name':'SYNTHETIC Recovery owner'})
        consult=action('consultation.create',{'patient_id':patient['id'],'title':'SYNTHETIC Crash recovery'})
        source=action('source.add',{'patient_id':patient['id'],'consultation_id':consult['id'],'text':'Exact source survives abrupt process loss.'})
        consult=next(r for r in req('GET','bootstrap')['records'] if r['id']==consult['id'])
        attachment=req('POST','uploads',data={'patient_id':patient['id']},files={'file':('synthetic.txt',b'Exact original attachment bytes.','text/plain')})
        recording=action('recording.create',{'patient_id':patient['id'],'consultation_id':consult['id']})
        # Upload durability bytes; no speech provider or decoding is involved.
        req('PUT','recordings/'+recording['id']+'/chunks/0',content=b'SYNTHETIC durable audio bytes')
        action('recording.complete',{'id':recording['id'],'expected_chunks':1,'duration':1})
        job=action('summary.generate',{'id':consult['id'],'version':consult['version'],'mode':'verbatim'})
        deadline=time.monotonic()+10
        while not (out/'claimed').exists() and time.monotonic()<deadline:time.sleep(.1)
        check((out/'claimed').exists(),'real worker claimed durable job before forced process loss')
        crashed_at=time.monotonic();stop(kill=True);start()
        check(req('GET','session').get('authenticated') is True,'original password session survives abrupt API restart')
        # The restarted worker must wait for the original 90-second lease, not steal it.
        check(req('GET','jobs/'+job['id'])['status']=='running','unexpired job lease remains fenced after restart')
        projection_start=time.monotonic();page=req('GET','v2/patients',params={'limit':50})
        report['initial_projection_seconds']=round(time.monotonic()-projection_start,3)
        check(len(page['items'])==50 and bool(page['next_cursor']),'patient directory returns bounded cursor pages')
        view=action('dashboard.save',{'name':'SYNTHETIC scale appointment view','query':{'kind':'appointment','species':'Cat','clinician':'synthetic-scale-vet','group_by':'species'}})
        expected_appointments=(a.patients+9)//10
        saved=req('GET','dashboards/'+view['id'])['result']
        check(saved['count']==expected_appointments and saved['groups']==[{'label':'Cat','count':expected_appointments}],
              'saved appointment query counts every exact synthetic clinic patient link')
        operations=req('GET','reports/operations?days=30')
        check(operations['patients']['total']==a.patients+9 and operations['appointments']['total']>=expected_appointments and
              operations['stock']['items']>=((a.patients+19)//20),
              'operational report counts complete synthetic clinic records')
        endpoints=['bootstrap','v2/patients?limit=50&q=SYNTHETIC','v2/patients/luna/timeline?limit=25',
                   'operations/health','reports/operations?days=30','dashboards/'+view['id']]
        def read(i):
            route=endpoints[i%len(endpoints)];began=time.monotonic();r=client.get(route)
            return route,r.status_code,time.monotonic()-began,len(r.content)
        began=time.monotonic()
        with ThreadPoolExecutor(max_workers=a.concurrency) as pool:results=list(pool.map(read,range(a.requests)))
        report['read_seconds']=round(time.monotonic()-began,3)
        report['read_metrics']={}
        for endpoint in endpoints:
            subset=[r for r in results if r[0]==endpoint];durations=sorted(r[2] for r in subset)
            report['read_metrics'][endpoint]={'requests':len(subset),'p50_ms':round(durations[len(durations)//2]*1000,1),'p95_ms':round(durations[min(len(durations)-1,int(len(durations)*.95))]*1000,1),'max_ms':round(durations[-1]*1000,1),'max_bytes':max(r[3] for r in subset)}
        check(all(r[1]==200 for r in results),'concurrent authenticated read workload has no HTTP errors')
        stock=action('inventory.create',{'name':'SYNTHETIC Concurrent supply','unit':'pack','stock':40,'reorder':2,'price_cents':100})
        def dispense(i):return client.post('actions',json={'action':'medication.dispense','payload':{'patient_id':patient['id'],'inventory_id':stock['id'],'version':stock['version'],'quantity':1,'dose':'Synthetic explicit dose','frequency':'Synthetic explicit frequency','instructions':'Synthetic explicit instructions'},'key':'stock-race-'+str(i)})
        with ThreadPoolExecutor(max_workers=a.concurrency) as pool:responses=list(pool.map(dispense,range(16)))
        check(sum(r.status_code==200 for r in responses)==1 and sum(r.status_code==409 for r in responses)==15,'competing stock writes produce one dispense and 15 stale-write rejections')
        invoice=action('invoice.create',{'patient_id':patient['id'],'items':[{'name':'Synthetic service','quantity':1,'price_cents':1000}]})
        body={'action':'payment.record','payload':{'id':invoice['id'],'version':invoice['version'],'amount_cents':100,'method':'cash'},'key':'same-payment-retry'}
        with ThreadPoolExecutor(max_workers=a.concurrency) as pool:payments=list(pool.map(lambda _:client.post('actions',json=body),range(16)))
        check(all(r.status_code==200 for r in payments) and len({r.json()['id'] for r in payments})==1,'16 simultaneous payment retries create exactly one payment')
        def booking(i):return client.post('actions',json={'action':'appointment.create','payload':{'patient_id':patient['id'],'date':'2098-09-01','time':'10:00','duration':30,'reason':'Synthetic collision','clinician':'clinic-east-vet'},'key':'booking-race-'+str(i)})
        with ThreadPoolExecutor(max_workers=a.concurrency) as pool:bookings=list(pool.map(booking,range(16)))
        check(sum(r.status_code==200 for r in bookings)==1 and sum(r.status_code==409 for r in bookings)==15,'16 competing bookings reserve the clinician once')
        deadline=crashed_at+110
        while time.monotonic()<deadline:
            recovered=req('GET','jobs/'+job['id'])
            if recovered['status']=='completed':break
            time.sleep(.5)
        check(recovered['status']=='completed','expired crash lease recovers automatically without a manual retry')
        report['crash_to_completed_seconds']=round(time.monotonic()-crashed_at,3)
        final={r['id']:r for r in req('GET','bootstrap')['records']}
        check(all(final[id]==r for id,r in original.items()),'unrelated original patient and owner records remain byte-for-byte equal')
        check(final[stock['id']]['data']['stock']==39 and final[invoice['id']]['data']['paid_cents']==100,'stock and invoice balances reconcile after concurrent writes')
        check(final[consult['id']]['version']==consult['version']+1 and final[consult['id']]['data']['summary'][0]['text']=='Exact source survives abrupt process loss.','recovered job saves the exact source once')
        check(client.get('files/'+attachment['id']).content==b'Exact original attachment bytes.','original attachment bytes survive restart')
        check(client.get('recordings/'+recording['id']+'/audio').content==b'SYNTHETIC durable audio bytes','original audio bytes survive restart')
        report['records_verified']=len(final)
    stop()
    if a.skip_restore:
        report['restore_skipped']=True
    else:
        for script,args in [('backup-local.py',[out/'backup']),('verify-backup.py',[out/'backup',out/'restored'])]:
            result=subprocess.run([str(PYTHON),str(ROOT/'scripts'/script),*map(str,args)],cwd=ROOT,env=env,capture_output=True,text=True)
            (out/(script+'.log')).write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(script+' failed; inspect private acceptance log')
        restored=json.loads((out/'restored/verification.json').read_text());report['restore']=restored
        check(restored['exact_snapshot_values_verified'] and restored['verified_binary_receipts']==2,'complete database snapshot and indexed audio/file receipts restore exactly')
        # Detect damage before a restore database is allocated.
        manifest=json.loads((out/'backup/manifest.json').read_text())
        first=next(iter(manifest['files']))
        damaged=out/'backup/data'/first;original=damaged.read_bytes();damaged.write_bytes(original+b'damaged')
        result=subprocess.run([str(PYTHON),str(ROOT/'scripts/verify-backup.py'),str(out/'backup'),str(out/'corrupt-restored')],cwd=ROOT,env=env,capture_output=True)
        damaged.write_bytes(original)
        check(result.returncode!=0 and not (out/'corrupt-restored').exists(),'corrupted backup is rejected before restoration')
    report['completed']=True
finally:
    stop()
    if created:
        with admin.connect() as c:c.exec_driver_sql('DROP DATABASE '+name+' WITH (FORCE)')
    admin.dispose()
    report['isolated_database_removed']=True
    (out/'results.json').write_text(json.dumps(report,indent=2));(out/'results.json').chmod(0o600)
print(json.dumps(report,indent=2),flush=True)
