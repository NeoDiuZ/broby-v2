'use client';
import {useEffect,useRef,useState} from 'react';
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
 if(record.kind==='source')return <p className="preserve">{record.data.text}</p>;
 if(record.kind==='medication')return <><p>Recorded dispensing in this clinic.</p><Facts data={record.data}/></>;
 if(record.kind==='observation')return <p>{record.data.name}: {String(record.data.value)} {record.data.unit} · supplied range {record.data.low??'—'}–{record.data.high??'—'}</p>;
 if(record.kind==='consultation')return <><p>{record.data.title} · {record.data.status}</p>{record.data.summary?.map((s:any,i:number)=><p className="preserve" key={i}>{s.name}: {s.text}</p>)}</>;
 if(record.kind==='attachment')return <p>Stored receiving file: {record.data.name} · {Math.ceil(record.data.size/1024)} KB. Open Documents to inspect its contents.</p>;
 if(record.kind==='recording')return <p>Stored receiving voice note: {record.data.title||'Voice note'} · {record.data.status}. Open its visit to listen.</p>;
 const kind=record.kind==='medication_history'?'medication':'event';
 return <><p>{record.data.title||record.data.name||'Earlier local copy'}</p><TransferContent kind={kind} data={record.data}/></>;
}

export function IncomingTransfers(){
 const w=useWorkspace(),clinic=w.snapshot?.clinic.id;
 // Remount per clinic to discard the previous clinic's preview and consent state.
 return w.snapshot?.permissions.includes('transfer.accept')?<ReceivingQueue key={clinic}/>:null;
}

function ReceivingQueue(){
 const w=useWorkspace();
 const [requests,setRequests]=useState<any[]>([]),[review,setReview]=useState<any>(null),[error,setError]=useState('');
 const [identity,setIdentity]=useState(false),[changes,setChanges]=useState(false),[baseline,setBaseline]=useState(false),[reason,setReason]=useState('');
 const [selected,setSelected]=useState(''),[search,setSearch]=useState(''),[history,setHistory]=useState(false),[loading,setLoading]=useState(false),[saving,setSaving]=useState(false);
 const sequence=useRef(0);
 const resetAcknowledgements=()=>{setIdentity(false);setChanges(false);setBaseline(false);setHistory(false);setReason('')};
 const loadReview=async(id:string,target='')=>{
  const current=++sequence.current; resetAcknowledgements(); setLoading(true); setError('');
  try {
   const result=await api('/transfers/'+id+'/preview'+(target?'?target_patient_id='+encodeURIComponent(target):''));
   if(current===sequence.current){setReview(result);setSelected(result.existing_patient_review_required?result.destination_patient.id:'')}
  } catch(e) {if(current===sequence.current)setError((e as Error).message)}
  finally {if(current===sequence.current)setLoading(false)}
 };
 const refresh=async()=>{setRequests(await api('/transfers/incoming'))};
 useEffect(()=>{let active=true;void api('/transfers/incoming').then(r=>{if(active)setRequests(r)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false;sequence.current++}},[]);
 const run=async(work:()=>Promise<void>)=>{setError('');try{await work()}catch(e){setError((e as Error).message)}};
 const names=new Map(w.records.filter(r=>r.kind==='owner').map(r=>[r.id,r.data.name]));
 const patients=w.records.filter(r=>r.kind==='patient');
 const matches=patients.filter(r=>[r.data.name,r.data.species,r.data.external_id,r.id,names.get(r.data.owner_id),...(r.data.additional_owner_ids||[]).map((id:string)=>names.get(id))].join(' ').toLowerCase().includes(search.toLowerCase()));
 const options=matches.slice(0,50);
 const selectedPatient=patients.find(r=>r.id===selected);
 if(selectedPatient&&!options.some(r=>r.id===selected))options.unshift(selectedPatient);
 const matching=!!review?.existing_patient_review_required;
 const selectionMatches=review?.destination_mode==='linked'||selected===(matching?review?.destination_patient.id:'');
 const canImport=identity&&selectionMatches&&!loading&&!saving&&(!review?.counts.changed||changes)&&(!review?.baseline_required||(baseline&&reason.trim().length>=10))&&(!matching||(history&&reason.trim().length>=10));
 const close=()=>{if(saving)return;sequence.current++;setLoading(false);setReview(null);setError('');setSelected('');setSearch('')};
 const importReviewed=async()=>{
  if(!canImport)return;
  setSaving(true);setError('');
  try {
   const result=await w.act('transfer.accept',{id:review.id,expected_digest:review.digest,review_changes:changes,
    ...(review.baseline_required?{establish_baseline:baseline,baseline_reason:reason}:{}),
    ...(matching?{target_patient_id:review.destination_patient.id,link_existing_patient:identity,acknowledge_existing_history:history,patient_match_reason:reason}:{})});
   setReview(null);setSelected('');setSearch('');void refresh().catch(()=>{});
   w.notify(matching?'Records added to the reviewed existing patient; local details and history preserved':'Reviewed records imported; earlier copies and clinic stock preserved');navigate('Patient',result.id);
  } catch(e) {setError((e as Error).message)} finally {setSaving(false)}
 };
 return <section className="section-gap"><h3>Owner-consented incoming records</h3><p>Review identity and source changes before importing. For a first transfer, choose a new patient or explicitly review an existing clinic patient. Later transfers follow that saved link. Names alone never establish a match.</p>
  <BusyButton onClick={()=>run(refresh)}>Refresh transfer requests</BusyButton>
  {error&&!review&&<p role="alert" className="error">{error}</p>}
  {requests.map(r=><div className="file-row" key={r.id}><span>{r.patient_name} · from {r.source_clinic}</span><BusyButton disabled={loading||saving} onClick={()=>loadReview(r.id)}>Review transfer</BusyButton></div>)}
  {review&&<Modal title="Review incoming records" wide onClose={close}><div className="modal-body">
   <h3>{review.patient.name} · {review.patient.species}</h3><p>From {review.source_clinic.name} · source patient {review.source_patient_id}</p>
   <h4>Source patient details</h4><Facts data={review.patient}/>
   <h4>Source primary owner</h4><Facts data={review.owner}/>
   {review.destination_mode!=='linked'&&<fieldset disabled={saving} className="transfer-destination">
    <legend>Choose the receiving record</legend>
    <p>Check the patient and owners, including any differences. Selecting a patient does not change records; load its review before confirming. Existing local details and history will be retained.</p>
    <label>Find an existing clinic patient<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Patient, owner or reference"/></label>
    <label>Receiving patient<select value={selected} onChange={e=>{sequence.current++;setLoading(false);setSelected(e.target.value);resetAcknowledgements();setError('')}}>
     <option value="">Create a new patient and owner</option>
     {options.map(p=><option key={p.id} value={p.id}>{p.data.name} · {p.data.species} · {names.get(p.data.owner_id)||'Owner not recorded'} · {p.id.slice(0,8)}</option>)}
    </select></label>
    {matches.length>50&&<p>Showing the first 50 results. Refine the search to find the correct patient.</p>}
    <BusyButton disabled={loading||saving} onClick={()=>loadReview(review.id,selected)}>Load receiving record review</BusyButton>
    {!selectionMatches&&<p role="status">Load the selected receiving record before importing.</p>}
   </fieldset>}
   <p>{review.destination_patient?`Reviewed receiving record: ${review.destination_patient.data.name} (${review.destination_patient.id}).`:'This preview creates a new patient and owner.'}</p>
   {review.destination_patient&&<section className="transfer-destination"><h4>Current receiving patient details</h4><Facts data={review.destination_patient.data}/>
    {(review.destination_owners||[review.destination_owner]).filter(Boolean).map((owner:any,i:number)=><div key={owner.id}><h4>{i===0?'Current primary owner':'Additional receiving owner'}</h4><Facts data={owner.data}/></div>)}
   </section>}
   {review.patient_link&&<p>This patient link was reviewed on {new Date(review.patient_link.reviewed_at).toLocaleString('en-SG')}. Reason: {review.patient_link.reason}</p>}
   {matching&&<section className="transfer-destination">
    <h3>Review the existing patient’s history</h3>
    <p>Confirm these records belong to the same animal. The clinic’s patient details, all owner links, files, stock and history will stay intact. Incoming approved facts are appended and may overlap with independently recorded facts. This does not merge owners, prove legal identity or mark clinical facts as equivalent.</p>
    <p>{review.existing_patient_review.existing_records.length} existing clinical records for this patient:</p>
    {review.existing_patient_review.existing_records.map((record:any)=><details key={record.id}><summary>{record.kind} · {record.data.title||record.data.name||'Existing record'}</summary><p>Receiving record {record.id} · version {record.version} · {record.updated_at}</p><LocalCopy record={record}/></details>)}
    {!review.existing_patient_review.existing_records.length&&<p>No clinical history is recorded for this receiving patient.</p>}
    <label>Patient match review reason<textarea disabled={saving||loading} value={reason} onChange={e=>setReason(e.target.value)} minLength={10} maxLength={1000} placeholder="Explain the identity evidence checked and any differences between these records."/></label>
    <label><input type="checkbox" disabled={saving||loading} checked={history} onChange={e=>setHistory(e.target.checked)}/>I reviewed the existing history and accept possible duplicate facts. Existing records and owner links will be preserved.</label>
   </section>}
   {review.baseline_required&&<section className="panel">
    <h3>Review earlier copies before starting a new baseline</h3>
    <p>This patient was imported before exact source revisions were saved. We cannot prove which current facts match the earlier copies. Accepting will append all currently shared records to this same patient and may create duplicates. Every earlier copy and local edit will remain intact.</p>
    <p>{review.baseline.earlier_requests.length} earlier accepted transfers · {review.baseline.existing_records.length} existing clinical records below. Future transfers will compare against the new baseline.</p>
    {review.baseline.existing_records.map((record:any)=><details key={record.id}><summary>{record.kind} · {record.data.title||record.data.name||'Earlier record'}</summary><p>Receiving record {record.id} · version {record.version} · {record.updated_at}</p><LocalCopy record={record}/></details>)}
    {!review.baseline.existing_records.length&&<p>No earlier clinical records are available for comparison. Check this receiving patient before continuing.</p>}
    <label>Baseline review reason<textarea disabled={saving||loading} value={reason} onChange={e=>setReason(e.target.value)} minLength={10} maxLength={1000} placeholder="Explain why you are accepting the current source as a new baseline."/></label>
    <label><input type="checkbox" disabled={saving||loading} checked={baseline} onChange={e=>setBaseline(e.target.checked)}/>I reviewed the earlier records and accept that this new baseline may duplicate them. Nothing earlier will be replaced or treated as a verified match.</label>
   </section>}
   <p>{review.counts.new} new · {review.counts.changed} changed · {review.counts.unchanged} already copied · {review.media_bytes<1024*1024?Math.ceil(review.media_bytes/1024)+' KB':(review.media_bytes/1024/1024).toFixed(1)+' MB'}</p>
   <p>Medication history: {review.scope.medications?'included as externally recorded history; no stock movement or new prescription':'excluded'}. Original audio: {review.scope.audio?'included when finished and approved; private transcripts excluded':'excluded'}.</p>
   <p>Imported records and audio remain private to this clinic until separately approved for owner sharing. Changed records append a revision. Earlier copies and local edits remain intact; a source withdrawal does not erase accepted medical copies.</p>
   {review.items.map((item:any)=><details key={item.kind+item.origin_id}><summary>{item.state} · {item.kind} · {item.payload.title||item.payload.name||item.payload.patient?.name||'Voice note'}</summary><p>Origin {item.origin_id} · {item.payload.occurred_at||item.payload.recorded_at||'Identity at transfer'}</p><TransferContent kind={item.kind} data={item.payload}/>{item.state==='changed'&&<><h4>Previously imported source information</h4><TransferContent kind={item.kind} data={item.previous}/><h4>Current local copy (will be retained)</h4><LocalCopy record={item.destination_copy}/></>}</details>)}
   <label><input type="checkbox" disabled={saving||loading||!selectionMatches} checked={identity} onChange={e=>setIdentity(e.target.checked)}/>{matching?'I confirm these are the same patient and have checked the source and all receiving owner details.':'I checked the patient, owner and receiving record.'}</label>
   {!!review.counts.changed&&<label><input type="checkbox" disabled={saving||loading} checked={changes} onChange={e=>setChanges(e.target.checked)}/>I reviewed the changed information and understand it will be appended alongside earlier copies and local edits.</label>}
   {loading&&<p role="status">Loading current source and receiving records…</p>}
   {error&&<p role="alert" className="error">{error}</p>}
   <BusyButton disabled={!canImport} onClick={importReviewed}>{matching?'Link patient and import reviewed records':review.baseline_required?'Establish reviewed baseline':'Import reviewed records'}</BusyButton>
   <BusyButton disabled={loading||saving} onClick={()=>loadReview(review.id,review.destination_mode==='linked'?'':selected)}>Reload preview</BusyButton>
  </div></Modal>}
 </section>
}
