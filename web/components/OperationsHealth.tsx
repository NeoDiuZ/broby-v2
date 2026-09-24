'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {navigate} from './App';
import {Badge,BusyButton} from './ui';

type Worker={name:string;label:string;state:string;attention:boolean;last_started_at?:string;last_success_at?:string;last_failure_at?:string;next_check_at?:string;seconds_since_progress?:number;history_saved?:boolean;history:{failures:number;last_failure_at:string|null;last_recovery_at:string|null}};
type Issue={id:string;state:string;created_at:string;consultation_id?:string;attempts?:number};
type Queue={name:string;label:string;counts:Record<string,number>;issues:Issue[]};
type Health={checked_at:string;clinic_id:string;status:string;workers:Worker[];queues:Queue[];issue_limit_per_queue:number;scope:string};
const stateLabels:Record<string,string>={starting:'Starting',not_started:'Not started',idle:'Cycle completed',working:'Processing',retry_wait:'Waiting to retry',disabled:'Not configured',overdue:'Progress needs checking',stopped:'Stopped',ready:'Ready to process',leased:'Claimed by a worker',completed:'Completed',failed:'Failed',conflict:'Newer edits preserved',queued:'Queued',sending:'Sending',sent:'Provider sent',delivered:'Provider delivered',read:'Provider read',uncertain:'Receipt uncertain',needs_review:'Review required',blocked:'Sending blocked',undelivered:'Not delivered',canceled:'Canceled'};
const label=(state:string)=>stateLabels[state]||state;
const date=(value?:string|null)=>value?new Date(value).toLocaleString('en-SG'):'Not recorded';

export function OperationsHealth(){
 const w=useWorkspace();
 return w.snapshot?.actor.data.role==='admin'?<HealthPanel key={w.snapshot.clinic.id}/>:null;
}
function HealthPanel(){
 const w=useWorkspace();
 const [health,setHealth]=useState<Health|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const mounted=useRef(false),busy=useRef(false);
 const refresh=useCallback(async()=>{
  if(busy.current)return;
  busy.current=true;setLoading(true);
  try{const result:Health=await api('/operations/health');if(mounted.current){setHealth(result);setError('')}}
  catch(e){if(mounted.current)setError((e as Error).message)}
  finally{busy.current=false;if(mounted.current)setLoading(false)}
 },[]);
 useEffect(()=>{mounted.current=true;void refresh();const timer=setInterval(()=>void refresh(),15000);return()=>{mounted.current=false;clearInterval(timer)}},[refresh]);
 return <section className="operations-health" aria-label="Background service health">
  <div className="panel-heading"><h3>Background service health</h3><BusyButton disabled={loading} onClick={refresh}>Refresh service health</BusyButton></div>
  <p>Check worker progress separately from the saved outcome of each job. This view refreshes every 15 seconds while open.</p>
  {error&&<p role="alert" className="error">Health could not be refreshed: {error}. {health?'The last check below may be out of date.':'No current worker status is available.'}</p>}
  {!health&&!error&&<p role="status">Checking background services…</p>}
  {health&&<><p>Checked {date(health.checked_at)} · <strong>{health.status==='needs_attention'?'Review required':'No worker or queue warnings at this check'}</strong></p>
   <p className="integration-note">{health.scope}</p>
   <div className="worker-grid">{health.workers.map(worker=><article className="worker-card" key={worker.name} aria-label={worker.label+' worker'}>
    <h4>{worker.label}</h4><Badge tone={worker.attention?'amber':worker.state==='disabled'?'neutral':'teal'}>{label(worker.state)}</Badge>
    <dl><dt>Last completed cycle</dt><dd>{date(worker.last_success_at)}</dd><dt>Last cycle started</dt><dd>{date(worker.last_started_at)}</dd>
     {worker.next_check_at&&worker.state!=='working'&&<><dt>Next check</dt><dd>{date(worker.next_check_at)}</dd></>}
     <dt>Recorded loop failures</dt><dd>{worker.history.failures}</dd>
     {worker.history.last_failure_at&&<><dt>Last loop failure</dt><dd>{date(worker.history.last_failure_at)}</dd><dt>Last recovery</dt><dd>{date(worker.history.last_recovery_at)}</dd></>}
    </dl>
    {worker.history_saved===false&&<p className="error">The latest worker history could not be saved.</p>}
    {worker.state==='overdue'&&<p>Progress has not advanced for at least five minutes. Work may still be running. Check its job and server logs before intervening; no duplicate worker has been started.</p>}
    {worker.state==='retry_wait'&&<p>A loop check failed. It will retry with a bounded delay; task safeguards and provider receipts still apply.</p>}
    {['stopped','not_started'].includes(worker.state)&&<p>This worker is unavailable. An operator should inspect the deployment.</p>}
    {worker.state==='disabled'&&<p>This provider is not configured for processing. This is not a delivery check.</p>}
   </article>)}</div>
   <h3>Work in this clinic</h3><p>Counts cover all saved work, including earlier failures. Up to {health.issue_limit_per_queue} recent issues per queue are listed. Waiting for an active claim or scheduled retry is not counted as overdue work.</p>
   {health.queues.map(queue=><section className="queue-health" key={queue.name} aria-label={queue.label+' queue'}><h4>{queue.label}</h4>
    {Object.keys(queue.counts).length?<dl className="queue-counts">{Object.entries(queue.counts).map(([state,count])=><div key={state}><dt>{label(state)}</dt><dd>{count}</dd></div>)}</dl>:<p>No saved work in this queue.</p>}
    {queue.issues.map(issue=><div className="job-row" key={issue.id}><div><strong>{label(issue.state)}</strong><small>{date(issue.created_at)} · reference {issue.id}</small>{issue.attempts!==undefined&&<small>{issue.attempts} processing attempts</small>}</div>
     {queue.name==='documents'&&issue.consultation_id&&<button className="secondary" onClick={()=>navigate('Consultation',issue.consultation_id)}>Open consultation</button>}
     {queue.name==='documents'&&issue.state==='failed'&&w.snapshot?.permissions.includes('job.retry')&&<BusyButton onClick={async()=>{await w.act('job.retry',{id:issue.id});await refresh();w.notify('Job queued for a guarded retry')}}>Retry failed job</BusyButton>}
    </div>)}
    {queue.name==='payments'&&queue.issues.length>0&&<button className="secondary" onClick={()=>navigate('Billing')}>Review in Billing</button>}
    {queue.name==='messaging'&&queue.issues.length>0&&<p>Review the WhatsApp trial in Integrations. Uncertain messages are never resent automatically.</p>}
   </section>)}
  </>}
 </section>
}
