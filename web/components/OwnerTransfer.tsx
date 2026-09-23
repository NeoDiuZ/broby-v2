'use client';
import {useState} from 'react';
import {BusyButton} from './ui';

async function ownerApi(base:string,path:string,options:RequestInit={}){
 const response=await fetch(base+path,{...options,headers:{'Content-Type':'application/json'}});
 const body=await response.json();
 if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Unable to update the transfer.');
 return body;
}

export function OwnerTransfer({base}:{base:string}){
 const [clinics,setClinics]=useState<any[]>([]),[requests,setRequests]=useState<any[]>([]),[target,setTarget]=useState('');
 const [consent,setConsent]=useState(false),[medications,setMedications]=useState(false),[audio,setAudio]=useState(false),[notice,setNotice]=useState('');
 const refresh=async()=>{const [cs,rs]=await Promise.all([ownerApi(base,'/transfer-clinics'),ownerApi(base,'/transfers')]);setClinics(cs);setRequests(rs)};
 const run=async(work:()=>Promise<void>)=>{setNotice('');try{await work()}catch(e){setNotice((e as Error).message)}};
 return <details className="panel section-gap" onToggle={e=>{if(e.currentTarget.open)void run(refresh)}}><summary>Share with a registered clinic</summary><div className="modal-body">
  <p>Share currently approved clinical notes and files, plus your pet’s details and the primary owner’s contact information. Approved notes may mention medicines. Choose whether to also share the structured medication history and approved voice notes.</p>
  <p>The receiving clinic reviews the records before importing an independent medical copy. You can withdraw a pending request, but accepted copies remain with that clinic. Later requests add new or changed information without overwriting earlier records.</p>
  <label>Receiving clinic<select value={target} onChange={e=>{setTarget(e.target.value);setConsent(false)}}><option value="">Choose clinic</option>{clinics.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
  <label><input type="checkbox" checked={medications} onChange={e=>{setMedications(e.target.checked);setConsent(false)}}/>Include structured medication history (historical prescriptions, not new instructions)</label>
  <label><input type="checkbox" checked={audio} onChange={e=>{setAudio(e.target.checked);setConsent(false)}}/>Include approved, finished voice notes (original audio only; private transcripts are excluded)</label>
  <label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>I consent to this transfer and the selected information.</label>
  <BusyButton disabled={!target||!consent} onClick={()=>run(async()=>{await ownerApi(base,'/transfers',{method:'POST',body:JSON.stringify({target_clinic:target,consent,include_medications:medications,include_audio:audio})});await refresh();setConsent(false);setNotice('Transfer request sent to the receiving clinic’s staff queue.')} )}>Request transfer</BusyButton>
  {notice&&<p role="status">{notice}</p>}
  {requests.map(r=><div className="file-row" key={r.id}><div><strong>{clinics.find(c=>c.id===r.target_clinic)?.name||r.target_clinic}</strong><small>{r.status} · {r.scope.medications?'medication history included':'notes and files'}{r.scope.audio?' · audio included':''} · expires {new Date(r.expires_at).toLocaleString()}</small></div>{r.status==='pending'&&<BusyButton onClick={()=>run(async()=>{await ownerApi(base,'/transfers/'+r.id,{method:'DELETE'});await refresh();setNotice('Transfer request withdrawn.')} )}>Withdraw pending request</BusyButton>}</div>)}
 </div></details>
}

