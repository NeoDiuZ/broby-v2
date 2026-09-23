'use client';
import {useEffect,useState} from 'react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {navigate} from './App';
import {BusyButton,Modal} from './ui';

const labels:Record<string,string>={name:'Name',species:'Species',breed:'Breed',sex:'Sex',weight:'Weight (kg)',age:'Recorded age',date_of_birth:'Date of birth',external_id:'Source patient reference',phone:'Phone',email:'Email',quantity:'Recorded quantity',dose:'Recorded dose',frequency:'Recorded frequency',instructions:'Source instructions',prescribed_by:'Source prescriber reference'};
function Facts({data}:{data:Record<string,any>}){
 return <dl>{Object.entries(data).filter(([key,value])=>key in labels&&value!==undefined&&value!==null&&value!=='').map(([key,value])=><div key={key}><dt>{labels[key]}</dt><dd className="preserve">{String(value)}</dd></div>)}</dl>
}
function TransferContent({kind,data}:{kind:string;data:any}){
 if(kind==='identity')return <><h4>Patient details from the source clinic</h4><Facts data={data.patient}/><h4>Primary owner details from the source clinic</h4><Facts data={data.owner}/></>;
 if(kind==='medication')return <><p>Externally recorded history. This is not a new prescription or dispensing instruction.</p><Facts data={data}/></>;
 if(kind==='audio')return <><p>{data.title||'Original voice note'} · {Math.floor((data.duration||0)/60)}:{String(Math.floor((data.duration||0)%60)).padStart(2,'0')}</p><p>Complete original audio with verified checksums. {data.interrupted?'The source device reported an interruption; review the recording.':''}</p></>;
 if(kind==='file')return <p>{data.name} · {Math.ceil(data.size/1024)} KB · original file verified.</p>;
 return <><p className="preserve">{data.body||'No additional narrative supplied.'}</p>{data.observations?.map((o:any,i:number)=><div key={o.id||i} className="inline-measurement"><span>{o.name}</span><strong>{typeof o.value==='boolean'?(o.value?'Yes':'No'):String(o.value)} {o.unit}</strong><span>{o.ref_low!=null||o.ref_high!=null?`Supplied reference: ${o.ref_low??'—'}–${o.ref_high??'—'} ${o.unit}`:'No reference range supplied'}</span></div>)}</>;
}
function LocalCopy({record}:{record:any}){
 if(!record)return <p>The earlier local record is unavailable; its original accepted source information is retained above.</p>;
 const kind=({recording:'audio',attachment:'file',medication_history:'medication'} as Record<string,string>)[record.kind]||'event';
 return <><p>{record.data.title||record.data.name||'Earlier local copy'}</p><TransferContent kind={kind} data={record.data}/></>;
}

export function IncomingTransfers(){
 const w=useWorkspace(),clinic=w.snapshot?.clinic.id;
 // Remount per clinic to discard the previous clinic's preview and consent state.
 return w.snapshot?.permissions.includes('transfer.accept')?<ReceivingQueue key={clinic}/>:null;
}

function ReceivingQueue(){
 const w=useWorkspace();
 const [requests,setRequests]=useState<any[]>([]),[review,setReview]=useState<any>(null),[error,setError]=useState(''),[identity,setIdentity]=useState(false),[changes,setChanges]=useState(false);
 const refresh=async()=>{setRequests(await api('/transfers/incoming'))};
 useEffect(()=>{let active=true;void api('/transfers/incoming').then(r=>{if(active)setRequests(r)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[]);
 const run=async(work:()=>Promise<void>)=>{setError('');try{await work()}catch(e){setError((e as Error).message)}};
 return <section className="section-gap"><h3>Owner-consented incoming records</h3><p>Review identity and source changes before importing. Subsequent transfers use the source clinic’s patient ID. Records are never matched by name, and existing local records are preserved.</p>
  <BusyButton onClick={()=>run(refresh)}>Refresh transfer requests</BusyButton>
  {error&&!review&&<p role="alert" className="error">{error}</p>}
  {requests.map(r=><div className="file-row" key={r.id}><span>{r.patient_name} · from {r.source_clinic}</span><BusyButton onClick={()=>run(async()=>{setIdentity(false);setChanges(false);setReview(await api('/transfers/'+r.id+'/preview'))})}>Review transfer</BusyButton></div>)}
  {review&&<Modal title="Review incoming records" wide onClose={()=>{setReview(null);setError('')}}><div className="modal-body">
   <h3>{review.patient.name} · {review.patient.species}</h3><p>From {review.source_clinic.name} · source patient {review.source_patient_id}</p>
   <p>Owner: {review.owner.name} · {review.owner.phone||'No phone'} · {review.owner.email||'No email'}</p>
   <p>{review.destination_patient?`Add to existing receiving record: ${review.destination_patient.data.name} (${review.destination_patient.id}).`:'Create a new patient and owner. Check for an existing local patient before proceeding.'}</p>
   <p>{review.counts.new} new · {review.counts.changed} changed · {review.counts.unchanged} already copied · {review.media_bytes<1024*1024?Math.ceil(review.media_bytes/1024)+' KB':(review.media_bytes/1024/1024).toFixed(1)+' MB'}</p>
   <p>Medication history: {review.scope.medications?'included as externally recorded history; no stock movement or new prescription':'excluded'}. Original audio: {review.scope.audio?'included when finished and approved; private transcripts excluded':'excluded'}.</p>
   <p>Imported records and audio remain private to this clinic until separately approved for owner sharing. Changed records append a revision. Earlier copies and local edits remain intact; a source withdrawal does not erase accepted medical copies.</p>
   {review.items.map((item:any)=><details key={item.kind+item.origin_id}><summary>{item.state} · {item.kind} · {item.payload.title||item.payload.name||item.payload.patient?.name||'Voice note'}</summary><p>Origin {item.origin_id} · {item.payload.occurred_at||item.payload.recorded_at||'Identity at transfer'}</p><TransferContent kind={item.kind} data={item.payload}/>{item.state==='changed'&&<><h4>Previously imported source information</h4><TransferContent kind={item.kind} data={item.previous}/><h4>Current local copy (will be retained)</h4><LocalCopy record={item.destination_copy}/></>}</details>)}
   <label><input type="checkbox" checked={identity} onChange={e=>setIdentity(e.target.checked)}/>I checked the patient, owner and receiving record.</label>
   {!!review.counts.changed&&<label><input type="checkbox" checked={changes} onChange={e=>setChanges(e.target.checked)}/>I reviewed the changed information and understand it will be appended alongside earlier copies and local edits.</label>}
   {error&&<p role="alert" className="error">{error}</p>}
   <BusyButton disabled={!identity||(!!review.counts.changed&&!changes)} onClick={()=>run(async()=>{const result=await w.act('transfer.accept',{id:review.id,expected_digest:review.digest,review_changes:changes});setReview(null);await refresh();w.notify('Reviewed records imported; earlier copies and clinic stock preserved');navigate('Patient',result.id)})}>Import reviewed records</BusyButton>
   <BusyButton onClick={()=>run(async()=>{setIdentity(false);setChanges(false);setReview(await api('/transfers/'+review.id+'/preview'))})}>Reload preview</BusyButton>
  </div></Modal>}
 </section>
}
