'use client';
import {useState} from 'react';
import {api, downloadFile} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {money} from '@/lib/types';
import {Badge, BusyButton} from './ui';

type Entry = {id:string;kind:string;invoice_id:string;invoice_number:string;patient_id:string;recorded_at:string;local_date:string;charge_cents:number;cash_cents:number;balance_change_cents:number;tax_cents:number|null;method:string;reference:string;reason:string;test_mode:boolean;source:string};
type Balance = {net_cents:number;receivable_cents:number;refund_due_cents:number};
type Report = {start:string;end:string;timezone:string;generated_at:string;entries:Entry[];total:number;offset:number;limit:number;opening:Balance;closing:Balance;net_charges_cents:number;net_cash_cents:number;known_tax_cents:number;unknown_tax_entries:number;reconciled:boolean;issue_count:number;issues:{record_id:string;message:string}[];mismatch_count:number;mismatches:{invoice_id:string;invoice_number:string;charge_difference_cents:number;cash_difference_cents:number}[];invoice_count:number};
const names:Record<string,string> = {invoice:'Invoice issued',payment:'Payment recorded',refund:'Refund recorded',credit_note:'Credit issued',credit_note_reversal:'Credit reversed',invoice_void:'Invoice voided'};

export function FinancialRegister(){
 const w=useWorkspace();
 const admin=w.snapshot?.actor.data.role==='admin';
 const zone=w.snapshot?.clinic.data.timezone||'Asia/Singapore';
 const current=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const [start,setStart]=useState(current.slice(0,7)+'-01'),[end,setEnd]=useState(current);
 const [report,setReport]=useState<Report|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 // Parent keys this component by clinic and actor, so account changes reset it.
 if(!admin)return <section className="panel section-gap"><div className="panel-heading"><h2>Financial register</h2></div><p className="integration-note">An administrator can review dated charges, recorded payments and invoice reconciliation.</p></section>;
 async function load(offset=0){
  setBusy(true);setError('');setReport(null);
  try{setReport(await api('/reports/financial?'+new URLSearchParams({start,end,offset:String(offset),limit:'50'})))}
  catch(e){setError(e instanceof Error?e.message:'The report could not be loaded.')}
  finally{setBusy(false)}
 }
 const stale=report&&(report.start!==start||report.end!==end);
 return <section className="panel section-gap financial-register">
  <div className="panel-heading"><h2>Financial register</h2><Badge>Recorded movements · SGD</Badge></div>
  <p className="integration-note">Dates use {zone}. Payments and refunds use the date Broby recorded them. Stripe test payments are labelled; this report does not verify bank settlement or determine tax treatment.</p>
  <form className="actions" onSubmit={e=>{e.preventDefault();void load()}}>
   <label>From<input aria-label="Financial period start" type="date" required value={start} onChange={e=>setStart(e.target.value)}/></label>
   <label>Through<input aria-label="Financial period end" type="date" required value={end} min={start} onChange={e=>setEnd(e.target.value)}/></label>
   <button className="secondary" disabled={busy||w.offline}>{busy?'Loading…':'Load financial register'}</button>
  </form>
  {w.offline&&<p role="status" className="muted">Reconnect to load a current financial register.</p>}
  {error&&<p role="alert" className="error">{error}</p>}
  {stale&&<p role="status">The dates changed. Load the register to update the results.</p>}
  {report&&!stale&&<>
   <div className="panel-heading"><p>{report.start} through {report.end} · {report.timezone}<br/><small>Snapshot: {new Date(report.generated_at).toLocaleString('en-SG',{timeZone:report.timezone})}</small></p>
    <BusyButton className="secondary" disabled={!report.reconciled||busy||w.offline} onClick={()=>downloadFile('/reports/financial/export?'+new URLSearchParams({start:report.start,end:report.end}),'broby-financial-register.csv')}>Export dated register</BusyButton>
   </div>
   <div className="metric-grid four">
    <div className="metric"><span>Opening net balance</span><strong>{money(report.opening.net_cents)}</strong><small>Receivable {money(report.opening.receivable_cents)} · Refund due {money(report.opening.refund_due_cents)}</small></div>
    <div className="metric"><span>Net charges in period</span><strong>{money(report.net_charges_cents)}</strong><small>Invoices, credits, reversals and dated voids</small></div>
    <div className="metric"><span>Payments less refunds</span><strong>{money(report.net_cash_cents)}</strong><small>Recorded in this period; includes labelled test entries</small></div>
    <div className="metric"><span>Closing net balance</span><strong>{money(report.closing.net_cents)}</strong><small>Receivable {money(report.closing.receivable_cents)} · Refund due {money(report.closing.refund_due_cents)}</small></div>
   </div>
   <p className="integration-note">Opening balance + net charges − net payments = closing balance. Known recorded tax change: {money(report.known_tax_cents)}. {report.unknown_tax_entries>0?`${report.unknown_tax_entries} charge entries have no tax breakdown; their tax is unknown.`:'All charge entries in this period have a recorded tax breakdown.'}</p>
   <p role="status" className={report.reconciled?'muted':'error'}>{report.reconciled?`Movement totals match all ${report.invoice_count} current invoice balances in this clinic.`:`Reconciliation needs attention: ${report.issue_count} record issues and ${report.mismatch_count} invoice differences. Totals may be incomplete; export is disabled.`}</p>
   {!!report.issue_count&&<details><summary>Record issues</summary>{report.issues.map((issue,i)=><p key={i}>{issue.message} <code>{issue.record_id}</code></p>)}{report.issue_count>report.issues.length&&<p>Showing the first {report.issues.length} issues.</p>}</details>}
   {!!report.mismatch_count&&<details><summary>Invoice differences</summary>{report.mismatches.map(row=><p key={row.invoice_id}>{row.invoice_number} · Charges differ by {money(row.charge_difference_cents)} · Payments differ by {money(row.cash_difference_cents)}</p>)}{report.mismatch_count>report.mismatches.length&&<p>Showing the first {report.mismatches.length} differences.</p>}</details>}
   <div style={{overflowX:'auto'}}><table className="financial-table"><caption>{report.total} recorded movements in this period</caption><thead><tr><th>Date</th><th>Invoice / movement</th><th>Charge</th><th>Cash</th><th>Source</th></tr></thead><tbody>{report.entries.map(e=><tr key={e.id}>
    <td>{e.local_date}<br/><small>{new Date(e.recorded_at).toLocaleTimeString('en-SG',{timeZone:report.timezone})}</small></td>
    <td><strong>{e.invoice_number}</strong><br/>{names[e.kind]}{e.test_mode&&<Badge>Test payment</Badge>}<br/><small>{e.method.replaceAll('_',' ')}</small></td>
    <td>{money(e.charge_cents)}</td><td>{money(e.cash_cents)}</td>
    <td><details><summary>View receipt</summary><p>{e.reason||'No reason recorded'}</p>{e.reference&&<p>Reference: {e.reference}</p>}<p>Recorded UTC: {e.recorded_at}</p><p>Tax: {e.tax_cents===null?'Not recorded / cash entry':money(e.tax_cents)}</p><p>Source: {e.source==='historical_audit'?'Earlier void audit receipt':'Stored movement'}</p><code>{e.id}</code><p>Invoice record: <code>{e.invoice_id}</code></p></details></td>
   </tr>)}</tbody></table></div>
   {!report.total&&<p className="muted">No financial movements were recorded in this period.</p>}
   <div className="actions"><button className="secondary" disabled={busy||report.offset===0} onClick={()=>void load(Math.max(0,report.offset-report.limit))}>Previous entries</button><span>{report.total?report.offset+1:0}–{Math.min(report.offset+report.entries.length,report.total)} of {report.total}</span><button className="secondary" disabled={busy||report.offset+report.limit>=report.total} onClick={()=>void load(report.offset+report.limit)}>Next entries</button></div>
  </>}
 </section>
}
