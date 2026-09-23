'use client';
import {useEffect,useRef,useState} from 'react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {Badge,BusyButton} from './ui';

type Status={configured:boolean;sending_enabled:boolean;recipient?:string;sender?:string;content_sid?:string;template_text?:string;opted_out?:boolean;callback_count?:number};
export function TwilioTrial(){
 const w=useWorkspace(),clinic=w.snapshot?.clinic.id,actor=w.snapshot?.actor.id;
 const allowed=w.snapshot?.permissions.includes('twilio.trial_send');
 const [status,setStatus]=useState<Status|null>(null),[error,setError]=useState('');const generation=useRef(0);
 useEffect(()=>{const n=++generation.current;setStatus(null);setError('');if(allowed)void api('/integrations/twilio/status').then(s=>{if(n===generation.current)setStatus(s)}).catch(e=>{if(n===generation.current)setError(e.message)});return()=>{generation.current++}},[allowed,clinic,actor]);
 if(!allowed)return null;
 const messages=w.records.filter(r=>r.kind==='whatsapp_trial'),inbound=w.records.filter(r=>r.kind==='whatsapp_trial_inbound');
 return <section className="panel section-gap" aria-label="WhatsApp trial"><div className="panel-heading"><div><h2>WhatsApp connection test</h2><p>One configured recipient · provider templates only</p></div><Badge tone="amber">Trial</Badge></div><div className="modal-body">
  <p>Customer sending is disabled. This test does not send patient drafts or clinical information.</p>
  {error&&<p role="alert" className="error">{error}</p>}
  {status&&!status.configured&&<p>Connect the trial sender, recipient and approved template before testing delivery.</p>}
  {status?.configured&&<><p>From {status.sender} to {status.recipient}</p><p className="preserve">Template: {status.template_text}</p><p>{status.opted_out?'Recipient opted out':status.sending_enabled?'Trial sending enabled (maximum 10 requested messages per day)':'Trial sending disabled'}</p><BusyButton disabled={!status.sending_enabled} onClick={async()=>{await w.act('twilio.trial_send',{recipient:status.recipient,content_sid:status.content_sid,template_text:status.template_text});w.notify('Trial request saved. Delivery must be confirmed by the provider.')}}>Send this template to the test recipient</BusyButton></>}
  {messages.map(r=><article className="history-entry" key={r.id}><div className="title-row"><strong>{r.data.template_text}</strong><Badge tone={['delivered','read'].includes(r.data.status)?'teal':'amber'}>{r.data.status}</Badge></div><p>{r.data.recipient} · {new Date(r.created_at).toLocaleString('en-SG')}</p>{r.data.error&&<p className="error">{r.data.error}</p>}{r.data.verified_at&&<small>Verified with Twilio: {new Date(r.data.verified_at).toLocaleString('en-SG')}</small>}{r.data.provider_sid&&<BusyButton onClick={async()=>{await w.act('twilio.reconcile',{id:r.id});w.notify('Provider verification queued')}}>Check delivery</BusyButton>}</article>)}
  {!!inbound.length&&<><h3>Incoming test messages</h3><p>These messages are not assigned to a patient and do not trigger automated replies.</p>{inbound.map(r=><article className="history-entry" key={r.id}><small>{new Date(r.created_at).toLocaleString('en-SG')}</small><p className="preserve">{r.data.body}</p>{r.data.media_count!=='0'&&<p>Media received by the provider; attachment import is not enabled in this trial.</p>}</article>)}</>}
 </div></section>;
}
