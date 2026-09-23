'use client';
import {useState} from 'react';
import {useWorkspace} from '@/lib/workspace';
import {downloadFile} from '@/lib/api';
import {cents,netCharge,outstanding,refundDue} from '@/lib/billing';
import {Row,money} from '@/lib/types';
import {Badge,Form,Modal} from './ui';

export function CreditNoteDialog({invoice:initialInvoice,credit,onClose}:{invoice:Row;credit?:Row;onClose:()=>void}){
 const w=useWorkspace();const [invoice]=useState(initialInvoice);const [review,setReview]=useState<Record<string,any>|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[key,setKey]=useState(()=>crypto.randomUUID());
 const reversed=!!credit,d=invoice.data,action=reversed?'credit_note.reverse':'credit_note.create';
 const amount=review?(reversed?credit!.data.amount_cents:review.net_cents+review.tax_cents):0;
 const after={...d,credited_cents:(d.credited_cents||0)+(reversed?-amount:amount)};
 return <Modal title={(reversed?'Reverse '+credit.data.number:'Credit note')+' · '+d.number} onClose={onClose}>
  {!review?<Form submit="Review credit change" fields={[
   ...(!reversed?[{name:'net',label:'Credit before tax (SGD)',type:'number',min:0,step:'0.01',required:true},{name:'tax',label:'Tax credit (SGD)',type:'number',min:0,step:'0.01',value:0,required:true}]:[]),
   {name:'reason',label:'Reason',type:'textarea',required:true,wide:true}
  ]} onSubmit={async values=>{
   setError('');setKey(crypto.randomUUID());
   const payload={id:credit?.id||invoice.id,version:invoice.version,reason:values.reason.trim(),...(!reversed?{net_cents:cents(values.net),tax_cents:cents(values.tax)}:{})};
   if(!reversed){const total=(payload as any).net_cents+(payload as any).tax_cents;
    if(!total)throw new Error('Enter a positive credit.');
    if((payload as any).tax_cents>(d.tax_cents||0)-(d.credited_tax_cents||0))throw new Error('Tax credit exceeds remaining recorded tax.');
    if((payload as any).net_cents>d.total_cents-(d.tax_cents||0)-((d.credited_cents||0)-(d.credited_tax_cents||0)))throw new Error('Credit exceeds the remaining charge before tax.');
   }
   setReview(payload);
  }}><p className="integration-note">{reversed?`Restores ${money(credit.data.amount_cents)} to this invoice. The issued note stays in the history.`:`Remaining charge before tax: ${money(d.total_cents-(d.tax_cents||0)-((d.credited_cents||0)-(d.credited_tax_cents||0)))}. Remaining recorded tax: ${money((d.tax_cents||0)-(d.credited_tax_cents||0))}. Enter the tax allocation approved by your clinic.`} This does not move money or return stock.</p></Form>:
  <div className="modal-body"><h3>Review before confirming</h3><dl className="credit-review">
   <dt>Invoice</dt><dd>{d.number}</dd><dt>{reversed?'Charge restored':'Credit before tax'}</dt><dd>{money(reversed?amount:review.net_cents)}</dd>
   {!reversed&&<><dt>Tax credit</dt><dd>{money(review.tax_cents)}</dd><dt>Total credit</dt><dd>{money(amount)}</dd></>}
   <dt>Reason</dt><dd className="preserve">{review.reason}</dd><dt>Net invoice charge after confirmation</dt><dd>{money(netCharge(after))}</dd>
   <dt>Outstanding after confirmation</dt><dd>{money(outstanding(after))}</dd><dt>Refund due after confirmation</dt><dd>{money(refundDue(after))}</dd>
  </dl><p>No money will be refunded and no stock will be returned. Any refund must be completed separately. The original invoice and this change remain in the audit history.</p>
  {error&&<p role="alert" className="error">{error}</p>}<div className="actions"><button className="secondary" disabled={busy} onClick={()=>setReview(null)}>Back</button><button className="primary" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await w.act(action,review,key);w.notify(reversed?'Credit note reversed; history retained':'Credit note issued; no refund sent');onClose()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>{busy?'Saving…':reversed?'Confirm reversal':'Issue credit note'}</button></div></div>}
 </Modal>;
}

export function CreditNotes(){
 const w=useWorkspace();const [reversing,setReversing]=useState<Row|null>(null);
 const notes=w.records.filter(r=>r.kind==='credit_note'),reversals=w.records.filter(r=>r.kind==='credit_note_reversal');
 const invoice=reversing?w.records.find(r=>r.id===reversing.data.invoice_id):null;
 return <section className="panel section-gap"><div className="panel-heading"><div><h2>Credit notes</h2><p>Charge corrections, with payment and stock changes handled separately.</p></div><button className="secondary" onClick={()=>void downloadFile('/credit-notes/export','broby-credit-notes.csv').catch(e=>w.notify(e.message))}>Export credit register</button></div>
  <div className="document-list">{!notes.length&&<p>No credit notes issued.</p>}{notes.map(note=>{const d=note.data,rev=reversals.find(r=>r.data.credit_note_id===note.id);return <article className="history-entry" key={note.id}>
   <div className="title-row"><strong>{d.number} · {d.invoice_number} · {money(d.amount_cents)}</strong><Badge tone={rev?'neutral':'teal'}>{rev?'Reversed':'Issued'}</Badge></div>
   <p>{d.patient_name} · {new Date(note.created_at).toLocaleString('en-SG')}</p><p>Before tax {money(d.net_cents)} · Tax credit {money(d.tax_cents)}</p><p className="preserve">{d.reason}</p>
   {rev&&<p className="preserve">Reversed {new Date(rev.created_at).toLocaleString('en-SG')}: {rev.data.reason}</p>}
   <div className="actions"><button className="secondary small" onClick={()=>void downloadFile('/credit-notes/'+note.id+'/pdf',d.number+'.pdf').catch(e=>w.notify(e.message))}>Download {d.number}</button>
   {!rev&&w.snapshot?.permissions.includes('credit_note.reverse')&&<button className="text-button" onClick={()=>setReversing(note)}>Reverse {d.number}</button>}</div>
  </article>})}</div>{reversing&&invoice&&<CreditNoteDialog invoice={invoice} credit={reversing} onClose={()=>setReversing(null)}/>}</section>;
}
