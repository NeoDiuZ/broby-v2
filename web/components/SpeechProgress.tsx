'use client';
import {useEffect,useState} from 'react';
import {api} from '@/lib/api';
import {Row} from '@/lib/types';
import {useWorkspace} from '@/lib/workspace';
import {BusyButton} from './ui';

export default function SpeechProgress({recording}:{recording:Row}){
 const w=useWorkspace(),id=recording.data.refinement_job_id;
 const [job,setJob]=useState<any>(null),[error,setError]=useState('');
 useEffect(()=>{
  if(!id||recording.data.transcript_source_id)return;
  let cancelled=false;
  const load=async()=>{try{const next=await api('/jobs/'+id);if(!cancelled){setJob(next);setError('')}}catch(e){if(!cancelled)setError((e as Error).message)}};
  void load();const timer=setInterval(()=>void load(),6000);
  return()=>{cancelled=true;clearInterval(timer)};
 },[id,recording.data.transcript_source_id]);
 if(!id||recording.data.transcript_source_id)return null;
 const windows=job?.result?.windows||[];
 return <div className="speech-progress">
  <p><strong>Automatic transcript</strong> · {windows.length} section{windows.length===1?'':'s'} saved · {job?.status==='waiting'?'Waiting for more audio':job?.status||'Loading'}</p>
  <p className="muted">Preview only. It becomes one source after Finish and a check against the complete audio. Speaker numbers are separate for each section. Review all machine text.</p>
  {(job?.error||error)&&<p className="error">{error||job.error}</p>}
  {job?.status==='failed'&&w.snapshot?.permissions.includes('job.retry')&&<BusyButton className="text-button" onClick={async()=>{setJob(await w.act('job.retry',{id:job.id}))}}>Retry saved sections</BusyButton>}
  {windows.length>0&&<details><summary>Review transcript preview</summary>{windows.map((section:any)=><article key={section.index}>
   <strong>{Math.floor(section.start/60)}:{String(Math.floor(section.start%60)).padStart(2,'0')}–{Math.floor(section.end/60)}:{String(Math.floor(section.end%60)).padStart(2,'0')}</strong>
   <p className="preserve">{section.text||'No speech recognized in this section. Listen to the original before relying on this result.'}</p>
  </article>)}</details>}
 </div>;
}
