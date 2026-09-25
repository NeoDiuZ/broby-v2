'use client';
import {useEffect,useState} from 'react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {Badge,BusyButton,Form} from './ui';

export function ClinicalEscalations({onReview}:{onReview:(id:string)=>void}){
 const w=useWorkspace(),[data,setData]=useState<any>(null),[error,setError]=useState(''),[revision,setRevision]=useState(0);
 const clinic=(w.snapshot?.clinic.id||'')+':'+(w.snapshot?.actor.id||''),policy=w.records.find(r=>r.kind==='owner_policy'),settings=policy?.data.escalation||{};
 useEffect(()=>{let live=true,busy=false;setData(null);const load=()=>{if(busy)return;busy=true;void api('/clinical-escalations').then(value=>{if(live){setData(value);setError('')}}).catch(e=>{if(live){setData(null);setError(e.message)}}).finally(()=>{busy=false})};load();const timer=setInterval(()=>{if(document.visibilityState==='visible')load()},5000);return()=>{live=false;clearInterval(timer)}},[clinic,revision]);
 const members=w.records.filter(r=>r.kind==='member'&&r.data.active&&['vet','nurse','admin'].includes(r.data.role)).map(r=>({value:r.id,label:r.data.name+' · '+r.data.role}));
 const routes=(data?.routes||[]).map((alias:string)=>({value:alias,label:alias}));
 return <section className="section-gap" aria-label="Clinical staff notifications"><div className="section-heading"><h3>Clinical staff notifications</h3><Badge>{data?.mode==='disabled'?'Disabled':data?.monitor_state==='fresh'?'Dispatcher checked':'Dispatcher needs attention'}</Badge></div>
 <p>These notifications ask named clinic staff to review an owner conversation. They do not assess symptoms, give advice, or prove an emergency response. A receiver accepting a notification is separate from a staff acknowledgement.</p>
 <p>Receiver messages contain an incident reference only. Sign in, select {w.snapshot?.clinic.data.name||'this exact clinic'}, open Handover, and match that reference before reviewing the conversation.</p>
 {error&&<p role="alert" className="error">{error}</p>}{data&&<><p>Transport: {data.mode} · dispatcher: {data.monitor_state.replaceAll('_',' ')}{data.heartbeat_at?' · last checked '+new Date(data.heartbeat_at).toLocaleString():''}. {settings.enabled?'Clinic policy enabled for new owner questions only.':'Clinic notification policy is disabled.'}</p>
 <BusyButton onClick={async()=>setRevision(n=>n+1)}>Refresh notification receipts</BusyButton>
 <p>{data.unresolved_count} unresolved notification incident(s). Showing {data.incidents.length}, with unresolved incidents first.{data.truncated?' More incidents exist than this bounded view can show. Use the owner conversation queue to review remaining work; absence from this list does not mean resolved.':''}</p>
 {data.incidents.map((incident:any)=><article className="intake-card" key={incident.id}><h4>Staff review notification · {incident.state.replaceAll('_',' ')}</h4><small>Incident {incident.id}</small><p>Primary: {incident.policy.primary_name} via {incident.policy.primary_route} · acknowledgement due {new Date(incident.primary_due_at).toLocaleString()}</p><p>Backup: {incident.policy.backup_name} via {incident.policy.backup_route} · acknowledgement due {new Date(incident.backup_due_at).toLocaleString()}</p>
 {incident.blocked_reason&&<p role="alert">Dispatch blocked: {incident.blocked_reason.replaceAll('_',' ')}. The clinic must follow its fallback arrangements.</p>}
 {incident.clinical_reconciliation&&<p role="alert" className="inline-notice">{incident.clinical_reconciliation.notice}</p>}
 {incident.state==='manual_fallback'&&<p role="alert"><strong>No staff acknowledgement was recorded by either deadline.</strong> {incident.clinical_reconciliation?'Staff follow-up is still required; current clinical instructions remain on hold.':"Follow the clinic's explicit fallback instructions now."} This state stays open until a reviewed staff acknowledgement or closure.</p>}
 {incident.clinical_reconciliation?<details><summary>Retained policy and review wording · historical evidence only</summary><p>Recorded fallback wording: {incident.policy.fallback_instructions}</p>{incident.acknowledgement_reason&&<p>Historical review reason: {incident.acknowledgement_reason}</p>}</details>:<><p>Clinic fallback instructions: {incident.policy.fallback_instructions}</p>{incident.acknowledgement_reason&&<p>Staff review reason: {incident.acknowledgement_reason}</p>}</>}
 {incident.acknowledged_at&&<p>Staff acknowledgement recorded {new Date(incident.acknowledged_at).toLocaleString()} by {w.records.find(r=>r.id===incident.acknowledged_by)?.data.name||incident.acknowledged_by}. This records follow-up responsibility, not clinical resolution.</p>}
 <ul>{incident.events.map((event:any)=><li key={event.id}>{event.stage.replaceAll('_',' ')} → {event.recipient} · {event.status==='accepted'?'Receiver accepted; clinical response not verified':event.status.replaceAll('_',' ')} · {event.attempts} attempt(s){event.last_error_code?' · '+event.last_error_code.replaceAll('_',' '):''}<details><summary>Delivery receipts · {event.id}</summary>{event.receipts.map((receipt:any)=><p key={receipt.attempt}>Attempt {receipt.attempt}: {receipt.outcome.replaceAll('_',' ')}{receipt.http_status?' · HTTP '+receipt.http_status:''} · {receipt.finished_at||receipt.started_at}</p>)}</details></li>)}</ul>
 <button className="secondary" onClick={()=>onReview(incident.thread_id)}>Read conversation and record staff review</button></article>)}
 {!data.incidents.length&&<p>No clinical notification incidents have been created. Enabling a policy does not send old conversations.</p>}
 {w.snapshot?.actor.data.role==='admin'&&<details><summary>Review clinic notification policy</summary><p>Choose distinct active primary and backup staff, known destination aliases, both acknowledgement timeouts, and the fallback staff must follow. Membership alone is not permission to notify someone: explicitly confirm clinic authority for the selected recipients. Saving applies to future owner questions; current incident deadlines and recipients remain recorded. Disabling stops pending sends. Changing or removing a destination blocks earlier queued sends.</p>
 <Form key={policy?.version||0} submit="Save reviewed notification policy" fields={[
 {name:'enabled',label:'External staff notifications',value:settings.enabled?'true':'false',options:[{value:'false',label:'Disabled'},{value:'true',label:'Enabled for future owner questions'}],required:true},
 {name:'primary_member_id',label:'Named primary',value:settings.primary_member_id,options:members},
 {name:'primary_route',label:'Primary destination alias',value:settings.primary_route,options:routes},
 {name:'primary_timeout_seconds',label:'Primary acknowledgement timeout (seconds)',type:'number',min:1,value:settings.primary_timeout_seconds??''},
 {name:'backup_member_id',label:'Named backup',value:settings.backup_member_id,options:members},
 {name:'backup_route',label:'Backup destination alias',value:settings.backup_route,options:routes},
 {name:'backup_timeout_seconds',label:'Backup acknowledgement timeout after primary deadline (seconds)',type:'number',min:1,value:settings.backup_timeout_seconds??''},
 {name:'fallback_instructions',label:'Exact clinic instructions if both acknowledgement deadlines expire',type:'textarea',value:settings.fallback_instructions||'',wide:true},
 {name:'recipient_authority_confirmed',label:'Notification authority for both named recipients',options:[{value:'false',label:'Not confirmed'},{value:'true',label:'Clinic explicitly authorizes these recipient notifications'}]},
 {name:'reason',label:'Policy review reason',required:true,wide:true},
 ]} onSubmit={async p=>{const enabled=p.enabled==='true';await w.act('conversation.policy',{version:policy?.version||0,ack_minutes:policy?.data.ack_minutes??null,reason:p.reason,escalation:enabled?{enabled:true,primary_member_id:p.primary_member_id,backup_member_id:p.backup_member_id,primary_route:p.primary_route,backup_route:p.backup_route,primary_timeout_seconds:Number(p.primary_timeout_seconds),backup_timeout_seconds:Number(p.backup_timeout_seconds),fallback_instructions:p.fallback_instructions,recipient_authority_confirmed:p.recipient_authority_confirmed==='true'}:{enabled:false}});setRevision(n=>n+1);w.notify('Reviewed notification policy saved for future questions')}}/>
 </details>}</>}
 </section>;
}
