"""Simulate a laboratory POST twice; no appointment, consult, form or AI required."""
import json,urllib.request
payload={'patient_id':'milo','dedupe_key':'simulator:incoming-2026-09-23','occurred_at':'2026-09-23T09:14:00Z','summary':'Simulated incoming laboratory result','actor':{'kind':'system','name':'Local laboratory simulator'},'source':{'kind':'document','id':'SIM-LAB-20260923','page':1,'text':'SYNTHETIC REPORT\nPatient: milo\nPotassium 5.0 mmol/L\nLaboratory interval 3.5–5.1 mmol/L'},'body':{'synthetic':True},'observations':[{'concept':'potassium','name':'Potassium','value':5.0,'unit':'mmol/L','ref_low':3.5,'ref_high':5.1}]}
def send():
    request=urllib.request.Request('http://127.0.0.1:8100/api/v2/ingest/lab',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-clinic-id':'clinic-east','x-actor-id':'clinic-east-vet'})
    return json.load(urllib.request.urlopen(request))
if __name__=='__main__':
    first=send();retry=send();assert first['id']==retry['id'] and retry['duplicate']
    print('One event after two deliveries:',first['id']);print('Open Patients → Milo → Timeline / Observations.')
