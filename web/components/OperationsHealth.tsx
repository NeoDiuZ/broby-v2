'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {navigate} from './App';
import {Badge,BusyButton,Form,Modal} from './ui';

type Worker={name:string;label:string;state:string;attention:boolean;last_started_at?:string;last_success_at?:string;last_failure_at?:string;next_check_at?:string;seconds_since_progress?:number;history_saved?:boolean;heartbeat_at?:string;heartbeat_age_seconds?:number;storage_matches?:boolean;mode_matches?:boolean;history:{failures:number;last_failure_at:string|null;last_recovery_at:string|null}};
type Issue={id:string;state:string;created_at:string;consultation_id?:string;attempts?:number};
type Queue={name:string;label:string;counts:Record<string,number>;issues:Issue[]};
type AlertEvent={id:string;kind:string;status:string;attempts:number;retry_limit:number;next_attempt:number;accepted_at:string|null;last_error_code:string|null;attempt_receipts:{attempt:number;started_at:string;finished_at:string|null;outcome:string;http_status:number|null}[]};
type Incident={id:string;version:number;state:string;opened_at:string;last_seen_at:string;recovered_at:string|null;acknowledged_at:string|null;acknowledged_by:string|null;acknowledgement_reason:string|null;details:{category:string;worker?:string;queue?:string;state?:string;consecutive_failures?:number;counts?:Record<string,number>};events:AlertEvent[];review_history:{action:string;actor_id:string;reason:string;created_at:string}[]};
type Alerts={mode:string;monitor_state:string;last_scan_at:string|null;counts:Record<string,number>;delivery_counts:Record<string,number>;incidents:Incident[];incident_limit:number;scope:string};
type Health={checked_at:string;clinic_id:string;status:string;workers:Worker[];queues:Queue[];issue_limit_per_queue:number;scope:string;worker_mode?:string;operational_alerts?:Alerts};
const stateLabels:Record<string,string>={starting:'Starting',not_started:'Not started',idle:'Cycle completed',working:'Processing',retry_wait:'Waiting to retry',disabled:'Not configured',overdue:'Progress needs checking',stopped:'Stopped',ready:'Ready to process',leased:'Claimed by a worker',completed:'Completed',failed:'Failed',conflict:'Newer edits preserved',queued:'Queued',sending:'Sending',sent:'Provider sent',delivered:'Provider delivered',read:'Provider read',uncertain:'Receipt uncertain',needs_review:'Review required',blocked:'Sending blocked',undelivered:'Not delivered',canceled:'Canceled'};
const label=(state:string)=>stateLabels[state]||state;
const date=(value?:string|null)=>value?new Date(value).toLocaleString('en-SG'):'Not recorded';
const serviceNames:Record<string,string>={runtime:'Background worker process',documents:'Documents and speech',schedule:'Scheduled preparation',payments:'Stripe test reconciliation',messaging:'WhatsApp trial processing'};
const incidentTitle=(incident:Incident)=>serviceNames[incident.details.worker||incident.details.queue||'runtime'];
const receiptLabel=(state:string)=>({accepted:'Webhook accepted',queued:'Waiting to send',sending:'Request in progress',failed:'Delivery needs review',superseded:'Replaced by the observed recovery notification',superseded_unconfirmed:'Recovery observed; earlier request acceptance unknown',interrupted:'Interrupted; acceptance unknown',in_flight:'Request receipt pending',retryable_http:'Temporary HTTP failure',rejected_http:'HTTP request rejected',timeout:'Request timed out; acceptance unknown',network_error:'Connection failed; acceptance unknown',transport_error:'Request could not be confirmed'}[state]||state);

function IncidentDetails({incident}:{incident:Incident}){
 return <><p><strong>{incidentTitle(incident)}</strong> · {incident.details.category==='queue'?'Saved work needs review':'Worker progress needs review'}</p>
  <dl><dt>Incident condition</dt><dd>{incident.state==='open'?'Still observed':'Recovery observed'}</dd><dt>First observed</dt><dd>{date(incident.opened_at)}</dd><dt>Last observed</dt><dd>{date(incident.last_seen_at)}</dd>{incident.recovered_at&&<><dt>Recovery observed</dt><dd>{date(incident.recovered_at)}</dd></>}
   {incident.details.state&&<><dt>Last observed worker state</dt><dd>{label(incident.details.state)}</dd></>}
   {incident.details.consecutive_failures!==undefined&&<><dt>Consecutive failed cycles</dt><dd>{incident.details.consecutive_failures}</dd></>}
   {Object.entries(incident.details.counts||{}).map(([state,count])=><div key={state}><dt>Last observed {label(state).toLowerCase()}</dt><dd>{count}</dd></div>)}
  </dl><small>Incident reference {incident.id}</small></>;
}

export function OperationsHealth(){
 const w=useWorkspace();
 return w.snapshot?.actor.data.role==='admin'?<HealthPanel key={w.snapshot.clinic.id}/>:null;
}
function HealthPanel(){
 const w=useWorkspace();
 const [health,setHealth]=useState<Health|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const [review,setReview]=useState<{incident:Incident;event?:AlertEvent}|null>(null);
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
   <p>Worker location: <strong>{health.worker_mode==='external'?'Separate background process':'Runs with the API'}</strong>.</p>
   <div className="worker-grid">{health.workers.map(worker=><article className="worker-card" key={worker.name} aria-label={worker.label+' worker'}>
    <h4>{worker.label}</h4><Badge tone={worker.attention?'amber':worker.state==='disabled'?'neutral':'teal'}>{label(worker.state)}</Badge>
    <dl><dt>Last completed cycle</dt><dd>{date(worker.last_success_at)}</dd><dt>Last cycle started</dt><dd>{date(worker.last_started_at)}</dd>
     {worker.heartbeat_at&&<><dt>Last process heartbeat</dt><dd>{date(worker.heartbeat_at)} ({worker.heartbeat_age_seconds??0} seconds ago)</dd><dt>Shared file storage check</dt><dd>{worker.storage_matches?'Matches the API':'Does not match; inspect configuration'}</dd></>}
     {worker.next_check_at&&worker.state!=='working'&&<><dt>Next check</dt><dd>{date(worker.next_check_at)}</dd></>}
     <dt>Recorded loop failures</dt><dd>{worker.history.failures}</dd>
     {worker.history.last_failure_at&&<><dt>Last loop failure</dt><dd>{date(worker.history.last_failure_at)}</dd><dt>Last recovery</dt><dd>{date(worker.history.last_recovery_at)}</dd></>}
    </dl>
    {worker.history_saved===false&&<p className="error">The latest worker history could not be saved.</p>}
    {worker.mode_matches===false&&<p className="error">The registered worker does not match the API's separate-process setting. An operator should inspect the deployment configuration.</p>}
    {worker.state==='overdue'&&<p>{worker.heartbeat_age_seconds!==undefined&&worker.heartbeat_age_seconds>30?'The separate process heartbeat is more than 30 seconds old.':'Cycle progress has not advanced for at least five minutes.'} Work may still be running. Check its job and server logs before intervening; no duplicate worker has been started.</p>}
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
   {health.operational_alerts&&<section className="queue-health" aria-label="Operational alert incidents"><h3>Operational alert incidents</h3>
    <p>{health.operational_alerts.scope}</p>
    <p>External notifications: <strong>{health.operational_alerts.mode==='disabled'?'Disabled':health.operational_alerts.mode==='configuration_error'?'Configuration needs review':health.operational_alerts.mode==='test-loopback'?'Synthetic local webhook':'Configured webhook'}</strong>. Monitor: {label(health.operational_alerts.monitor_state)}. Last scan: {date(health.operational_alerts.last_scan_at)}.</p>
    {health.operational_alerts.mode==='disabled'&&<p>No external operational notifications are sent. Existing incident history remains available.</p>}
    <p>{health.operational_alerts.counts.open||0} open · {health.operational_alerts.counts.recovered||0} with recovery observed · {health.operational_alerts.delivery_counts.failed||0} webhook events need delivery review. Showing up to {health.operational_alerts.incident_limit} incidents.</p>
    {health.operational_alerts.incidents.map(incident=><article className="worker-card" key={incident.id}>
     <IncidentDetails incident={incident}/>
     <p>{incident.acknowledged_at?`Administrator review acknowledged ${date(incident.acknowledged_at)}.`:'No administrator acknowledgement recorded.'}</p>
     {incident.acknowledgement_reason&&<p className="preserve">Review reason: {incident.acknowledgement_reason}</p>}
     {!incident.acknowledged_at&&w.snapshot?.permissions.includes('operations.alert.acknowledge')&&<button className="secondary" onClick={()=>setReview({incident})}>Review and acknowledge incident</button>}
     {incident.events.map(event=><section key={event.id}><h4>{event.kind==='opened'?'Incident opened':'Recovery observed'} notification</h4>
      <p>{receiptLabel(event.status)} · {event.attempts} attempts recorded{event.accepted_at?` · accepted ${date(event.accepted_at)}`:''}.</p>
      {event.status==='queued'&&event.next_attempt>0&&<p>Next attempt after {date(new Date(event.next_attempt*1000).toISOString())}.</p>}
      <small>Notification reference {event.id}</small>
      <details><summary>Webhook attempt receipts</summary>{event.attempt_receipts.map(attempt=><p key={attempt.attempt}>Attempt {attempt.attempt} · {date(attempt.started_at)} · {receiptLabel(attempt.outcome)}{attempt.http_status?` (HTTP ${attempt.http_status})`:''}</p>)}<p>Up to 10 recent receipts are shown. Acceptance confirms the webhook response only.</p></details>
      {event.status==='failed'&&w.snapshot?.permissions.includes('operations.alert.retry')&&<button className="secondary" onClick={()=>setReview({incident,event})}>Review and retry notification</button>}
     </section>)}
     {incident.review_history.length>0&&<details><summary>Administrator review history</summary>{incident.review_history.map((entry,index)=><p key={index}>{date(entry.created_at)} · {entry.action==='operations.alert.retry'?'Notification retry reviewed':'Incident acknowledged'} · {entry.reason}</p>)}</details>}
    </article>)}
   </section>}
  </>}
  {review&&<Modal title={review.event?'Review operational notification retry':'Review operational incident'} onClose={()=>setReview(null)}><div className="modal-body">
   <IncidentDetails incident={review.incident}/>
   {review.event?<p>Retry the same failed notification reference {review.event.id}. Earlier receipts remain saved. The destination must have been checked by the deployment operator. A new request does not prove that anyone has responded.</p>:<p>This records your review and reason. It does not mark the condition recovered, change delivery receipts or confirm an on-call response.</p>}
   {review.event&&health?.operational_alerts?.mode==='disabled'&&<p>External notifications are disabled. This event will remain queued until a deployment operator enables the transport.</p>}
   <Form fields={[{name:'reason',label:'Reason for this review',type:'textarea',required:true,wide:true}]} submit={review.event?'Confirm notification retry':'Confirm acknowledgement'} onSubmit={async values=>{
    await w.act(review.event?'operations.alert.retry':'operations.alert.acknowledge',{id:review.incident.id,version:review.incident.version,reason:values.reason,...(review.event?{event_id:review.event.id}:{})});
    setReview(null);await refresh();w.notify(review.event?'Notification queued with its original reference':'Administrator acknowledgement recorded');
   }}/>
  </div></Modal>}
 </section>
}
