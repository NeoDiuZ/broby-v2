'use client';
import {useEffect, useState} from 'react';
import {api, downloadFile} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {Badge, BusyButton} from './ui';

type Group = {label:string;count:number};
type StatusGroup = {total:number;by_status:Group[]};
type Report = {
  days:number;start:string;end:string;timezone:string;generated_at:string;
  patients:{total:number;linked_to_owner:number;by_species:Group[]};owners_total:number;
  consultations:StatusGroup;appointments:StatusGroup;reminders:StatusGroup;messages:StatusGroup;
  open_intakes:number;failed_or_conflicting_jobs:number;
  stock:{items:number;low:number;invalid:number};
};

export function OperationalReport({days}:{days:number}) {
  const w=useWorkspace();
  const clinic=w.snapshot?.clinic.id, actor=w.snapshot?.actor.id;
  const [data,setData]=useState<Report|null>(null);
  const [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    let live=true;
    setData(null);setError('');
    if(!w.offline)void api('/reports/operations?days='+days)
      .then((result:Report)=>{if(live)setData(result)})
      .catch((cause:Error)=>{if(live)setError(cause.message)});
    return()=>{live=false};
  },[clinic,actor,days,attempt,w.offline]);
  const current=data?.days===days?data:null;
  const largest=Math.max(1,...(current?.patients.by_species||[]).map(row=>row.count));
  return <>
    <section className="panel section-gap">
      <div className="panel-heading"><h2>Operational report</h2><div className="actions">
        <button className="text-button" disabled={w.offline} onClick={()=>setAttempt(n=>n+1)}>Refresh</button>
        <BusyButton className="secondary" disabled={!current||w.offline} onClick={()=>downloadFile('/reports/operations/export?days='+days,'broby-operational-report.csv')}>Export full report</BusyButton>
      </div></div>
      {w.offline?<p role="status" className="spine-state">Reconnect for current clinic totals.</p>:
       error?<p role="alert" className="error">{error}</p>:
       !current?<p role="status" className="spine-state">Loading clinic totals…</p>:<>
        <p className="integration-note">{current.start} through {current.end} · {current.timezone} · captured {new Date(current.generated_at).toLocaleString('en-SG',{timeZone:current.timezone})}. Patient and owner counts are all time; workflow totals use the displayed period.</p>
        <div className="metric-grid four">
          <div className="metric"><span>Registered patients</span><strong>{current.patients.total}</strong><small>{current.patients.linked_to_owner} linked to a current owner</small></div>
          <div className="metric"><span>Consultations created</span><strong>{current.consultations.total}</strong><small>{current.consultations.by_status.find(row=>row.label==='reviewed')?.count||0} reviewed</small></div>
          <div className="metric"><span>Appointments scheduled</span><strong>{current.appointments.total}</strong><small>By appointment date</small></div>
          <div className="metric"><span>Messages created</span><strong>{current.messages.total}</strong><small>Recorded drafts and delivery states</small></div>
        </div>
        <p className="integration-note">These counts come from all persisted clinic records, including records outside the browser’s currently loaded pages. A message status is a stored state, not proof of recipient delivery.</p>
      </>}
    </section>
    {current&&<div className="reports-grid">
      <section className="panel chart-panel"><div className="panel-heading"><h2>Patients by species</h2><Badge>All patients</Badge></div>
        <div className="bar-chart">{current.patients.by_species.map(row=><div className="bar-column" key={row.label}><strong>{row.count}</strong><div className={'chart-bar '+(['cat','rabbit','bird'].includes(row.label.toLowerCase())?row.label.toLowerCase():'other')} style={{height:Math.max(3,row.count/largest*190)}}/><span>{row.label}</span></div>)}</div>
        {!current.patients.by_species.length&&<p className="muted">No patients are registered.</p>}
      </section>
      <section className="panel"><div className="panel-heading"><h2>Current follow-up</h2></div><div className="quality-list">
        <div><span>Patients linked to an owner</span><strong>{current.patients.linked_to_owner} / {current.patients.total}</strong></div>
        <div><span>Low stock items</span><strong>{current.stock.low} / {current.stock.items}</strong></div>
        <div><span>Owner intakes awaiting review</span><strong>{current.open_intakes}</strong></div>
        <div><span>Failed or conflicting jobs</span><strong>{current.failed_or_conflicting_jobs}</strong></div>
      </div>{current.stock.invalid>0&&<p role="alert" className="error">{current.stock.invalid} inventory records have invalid quantities and are excluded from stock totals.</p>}</section>
    </div>}
    {current&&<section className="panel section-gap"><div className="panel-heading"><h2>Workflow status in this period</h2></div>
      <div className="quality-list">{([
        ['Appointments',current.appointments],['Reminders due',current.reminders],
        ['Messages created',current.messages],['Consultations created',current.consultations],
      ] as [string,StatusGroup][]).map(([label,group])=><div key={label}><span>{label} · {group.total}</span><strong>{group.by_status.map(row=>`${row.label}: ${row.count}`).join(' · ')||'None'}</strong></div>)}</div>
    </section>}
  </>;
}
