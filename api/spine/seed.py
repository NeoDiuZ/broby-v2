"""Repeatable synthetic, consultation-independent lab history for local acceptance."""
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2]/'.env')
import db,auth
from .projection import setup_queue,sync
from .database import session
from .contracts import LabInput
from .service import ingest

def seed():
    db.init();auth.setup_tables();setup_queue();sync('clinic-east');sync('clinic-river')
    reports=[('2026-06-18T09:14:00Z',4.1),('2026-07-18T09:14:00Z',4.6),('2026-08-18T09:14:00Z',5.8),('2026-09-18T09:14:00Z',4.8)]
    ids=[]
    with session() as s,s.begin():
        for i,(when,value) in enumerate(reports):
            p=LabInput(patient_id='milo',dedupe_key='synthetic-lab-history:'+str(i),occurred_at=when,summary='Synthetic laboratory report · potassium',actor={'kind':'system','name':'Demo laboratory import'},source={'kind':'document','id':'DEMO-LAB-'+str(i+1),'page':1,'text':f'SYNTHETIC LABORATORY REPORT — not a real patient result\nPatient ID: milo\nSample taken: {when}\nPotassium: {value} mmol/L\nReporting laboratory reference interval: 3.5–5.1 mmol/L'},body={'accession':'DEMO-LAB-'+str(i+1),'synthetic':True},observations=[{'concept':'potassium','name':'Potassium','value':value,'unit':'mmol/L','ref_low':3.5,'ref_high':5.1}])
            ids.append(ingest(s,'clinic-east',p)['id'])
    return ids
if __name__=='__main__':print('Synthetic laboratory events ready:',len(seed()))
