'use client';
import {useState} from 'react';
import {useWorkspace} from '@/lib/workspace';
import {Row,money} from '@/lib/types';
import {Badge,BusyButton,Empty,Form,Modal} from './ui';

const active=new Set(['creating','open','cancel_requested','needs_review']);
export function StripeCheckoutButton({invoice}:{invoice:Row}) {
 const w=useWorkspace();
 if(!w.snapshot?.integrations.payments||!w.snapshot.permissions.includes('stripe.checkout'))return null;
 const existing=w.records.find(r=>r.kind==='stripe_checkout'&&r.data.invoice_id===invoice.id&&active.has(r.data.status));
 return <BusyButton className="secondary small" disabled={!!existing} onClick={async()=>{
  await w.act('stripe.checkout',{invoice_id:invoice.id,version:invoice.version});
  w.notify('Test checkout requested. Open it from Online payments below when ready.');
 }}>{existing?'Checkout in progress':'Create test checkout'}</BusyButton>;
}

export function StripePayments() {
 const w=useWorkspace();const [refunding,setRefunding]=useState<Row|null>(null);
 const checkouts=w.records.filter(r=>r.kind==='stripe_checkout');
 const configured=w.snapshot?.integrations.payments;
 const permission=(a:string)=>w.snapshot?.permissions.includes(a);
 if(!configured&&!checkouts.length)return <p className="integration-note">Online payments are not connected for this clinic. You can record payments already received elsewhere.</p>;
 return <section className="panel section-gap" aria-label="Online payments">
  <div className="panel-heading"><div><h2>Online payments</h2><p>Stripe sandbox · synthetic invoices only</p></div><Badge tone="amber">Test payments</Badge></div>
  <div className="modal-body"><p className="integration-note">Use Stripe test cards only. No real money moves. A successful Stripe payment updates this test invoice after verification. Returning from Checkout alone does not mark it paid.</p>
  {!configured&&<p className="error">Stripe is currently unavailable for this clinic. Existing payment history is preserved.</p>}
  <div className="document-list">{checkouts.map(r=>{const d=r.data;const invoice=w.records.find(i=>i.id===d.invoice_id);const requests=w.records.filter(v=>v.kind==='stripe_refund'&&v.data.checkout_id===r.id);return <article className="history-entry" key={r.id}>
   <div className="title-row"><div><strong>{invoice?.data.number||d.invoice_number} · {money(d.amount_cents)}</strong><p>{w.records.find(p=>p.id===d.patient_id)?.data.name}</p></div><Badge tone={d.status==='paid'?'teal':'amber'}>{d.status.replaceAll('_',' ')}</Badge></div>
   {d.error&&<p className="error" role="alert">{d.error}</p>}
   {d.verified_at&&<small>Last checked with Stripe: {new Date(d.verified_at).toLocaleString('en-SG')}</small>}
   <div className="actions">
    {d.checkout_url&&d.status==='open'&&<a className="primary small" href={d.checkout_url} target="_blank" rel="noopener noreferrer">Open test checkout</a>}
    {configured&&permission('stripe.refresh')&&<BusyButton onClick={async()=>{await w.act('stripe.refresh',{id:r.id});w.notify('Stripe verification queued')}}>Check payment</BusyButton>}
    {configured&&active.has(d.status)&&d.status!=='cancel_requested'&&permission('stripe.cancel')&&<BusyButton onClick={async()=>{await w.act('stripe.cancel',{id:r.id});w.notify('Cancellation requested. Waiting for Stripe confirmation.')}}>Cancel checkout</BusyButton>}
    {configured&&d.status==='paid'&&permission('stripe.refund')&&d.refunded_cents<d.amount_cents&&<button className="secondary" onClick={()=>setRefunding(r)}>Refund test payment</button>}
   </div>
   {d.refunded_cents>0&&<p>Verified refunds: {money(d.refunded_cents)}</p>}
   {requests.map(v=><p key={v.id}>Refund {money(v.data.amount_cents)} · {v.data.status.replaceAll('_',' ')}{v.data.error?' · '+v.data.error:''}</p>)}
  </article>})}</div>
  {!checkouts.length&&<Empty title="No online payments yet" text="Create a test checkout from an outstanding invoice above."/>}
  </div>
  {refunding&&<Modal title="Refund Stripe test payment" onClose={()=>setRefunding(null)}>
   <Form submit="Request test refund" fields={[{name:'amount',label:'Refund amount (SGD)',required:true,type:'number',min:.01,step:'0.01'},{name:'reason',label:'Reason',required:true,wide:true}]} onSubmit={async p=>{
    await w.act('stripe.refund',{id:refunding.id,amount_cents:Math.round(Number(p.amount)*100),reason:p.reason});
    setRefunding(null);w.notify('Test refund requested. The invoice updates when Stripe confirms success.');
   }}><p className="integration-note">This refunds only a Stripe sandbox payment. Failed or pending refunds do not reduce the recorded payment.</p></Form>
  </Modal>}
 </section>;
}
