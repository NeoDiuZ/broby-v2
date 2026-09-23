'use client';

import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {Row} from '@/lib/types';
import {Receipt} from '@/lib/spine';
import {useWorkspace} from '@/lib/workspace';
import {BusyButton, Form, Modal, Badge} from './ui';
import {ReceiptView} from './PatientSpine';
import {navigate} from './App';

export function PatientOwners({patient}:{patient:Row}) {
  const w=useWorkspace();
  const [open,setOpen]=useState(false),[error,setError]=useState('');
  const owners=w.records.filter(r=>r.kind==='owner'&&!r.data.merged_into);
  const ids=[patient.data.owner_id,...(patient.data.additional_owner_ids||[])];
  return <section className="panel"><h2>Owners & contacts</h2>
    {ids.map((id:string)=><p key={id}>{owners.find(o=>o.id===id)?.data.name||'Owner'}{id===patient.data.owner_id?' · Primary':''}</p>)}
    {w.snapshot?.permissions.includes('patient.owners')&&<button className="text-button" onClick={()=>setOpen(true)}>Manage owners</button>}
    {open&&<Modal title="Patient owners" onClose={()=>setOpen(false)}><form className="form" onSubmit={async e=>{
      e.preventDefault();setError('');const fields=new FormData(e.currentTarget);
      try{await w.act('patient.owners',{id:patient.id,version:patient.version,owner_id:fields.get('owner_id'),additional_owner_ids:fields.getAll('additional_owner_ids')});setOpen(false);w.notify('Owner links saved')}catch(e){setError((e as Error).message)}
    }}><label>Primary owner<select name="owner_id" defaultValue={patient.data.owner_id}>{owners.map(o=><option key={o.id} value={o.id}>{o.data.name}</option>)}</select></label>
      <fieldset><legend>Additional owners</legend>{owners.map(o=><label className="feature-lock" key={o.id}><input type="checkbox" name="additional_owner_ids" value={o.id} defaultChecked={patient.data.additional_owner_ids?.includes(o.id)}/>{o.data.name}</label>)}</fieldset>
      <p className="integration-note">Changing owners revokes existing owner links and saved access for this pet. Create fresh links after confirming the new relationships.</p>
      {error&&<p role="alert" className="error">{error}</p>}<button className="primary">Save owner links</button>
    </form></Modal>}
  </section>;
}

export function RenameRecording({recording}:{recording:Row}) {
  const w=useWorkspace(),[open,setOpen]=useState(false);
  if(!w.snapshot?.permissions.includes('recording.rename'))return null;
  return <><button className="text-button" onClick={()=>setOpen(true)}>Rename</button>{open&&<Modal title={'Rename voice note '+recording.data.number} onClose={()=>setOpen(false)}>
    <Form fields={[{name:'title',label:'Voice note title',value:recording.data.title||'',required:true,wide:true}]} onSubmit={async p=>{await w.act('recording.rename',{...p,id:recording.id,version:recording.version});setOpen(false)}}/>
  </Modal>}</>;
}

export function SpeakerLabels({source}:{source:Row}) {
  const w=useWorkspace();
  const ids=Array.from(new Set<string>((source.data.utterances||[]).filter((u:any)=>u.speaker!=null).map((u:any)=>String(u.speaker))));
  if(!ids.length||!w.snapshot?.permissions.includes('source.speakers'))return null;
  return <details><summary>Review speaker labels</summary><Form key={source.id+':'+source.version} submit="Save speaker labels"
    fields={ids.map(id=>({name:id,label:'Speaker '+id,value:source.data.speaker_labels?.[id]||'Speaker '+id,required:true}))}
    onSubmit={async labels=>{await w.act('source.speakers',{id:source.id,version:source.version,speaker_labels:labels});w.notify('Speaker labels saved; original transcript preserved')}}>
    <p className="integration-note">Listen before assigning names. These labels do not change the original transcript or the provider’s speaker identifiers.</p>
  </Form></details>;
}

export function AutomationPreferences() {
  const w=useWorkspace();const settings=w.records.find(r=>r.kind==='settings');
  if(!settings||!w.snapshot?.permissions.includes('automation.save'))return null;
  const booleanOptions=[{value:'false',label:'Off'},{value:'true',label:'On'}];
  return <section className="settings-section"><h3>Scheduled clinic preparation</h3>
    <Form key={settings.id+':automation:'+settings.version} submit="Save schedule" fields={[
      {name:'auto_reminders',label:'Automatically prepare reminder drafts',value:String(!!settings.data.auto_reminders),options:booleanOptions},
      {name:'auto_handover',label:'Prepare daily handover in Broby',value:String(!!settings.data.auto_handover),options:booleanOptions},
      {name:'handover_at',label:'Handover time · '+(w.snapshot?.clinic.data.timezone||'Asia/Singapore'),type:'time',value:settings.data.handover_at||'07:00',required:true},
    ]} onSubmit={async p=>{await w.act('automation.save',{...p,version:settings.version,auto_reminders:p.auto_reminders==='true',auto_handover:p.auto_handover==='true'});w.notify('Clinic schedule saved')}}>
      <p className="integration-note">Reminders become drafts for staff to review and deliver manually. Handover appears in Broby. Your existing WhatsApp connection is unchanged.</p>
    </Form>
  </section>;
}

export function HandoverArchive() {
  const w=useWorkspace(),[selected,setSelected]=useState<Row|null>(null);
  const handovers=w.records.filter(r=>r.kind==='handover');
  const current=selected?w.records.find(r=>r.id===selected.id)||selected:null;
  return <section className="panel section-gap"><div className="panel-heading"><h2>Prepared handovers</h2><BusyButton onClick={async()=>{setSelected(await w.act('handover.prepare',{}))}}>Prepare today’s handover</BusyButton></div>
    <div className="document-list">{handovers.map(r=><button className="visit-row" key={r.id} onClick={()=>setSelected(r)}><span>{r.data.title}</span><Badge>{r.data.acknowledged_by.some((x:any)=>x.actor_id===w.snapshot?.actor.id)?'Acknowledged':'Needs review'}</Badge></button>)}
      {!handovers.length&&<p className="muted">No prepared handovers yet. Enable a schedule in clinic settings or prepare one now.</p>}</div>
    {current&&<Modal title={current.data.title} onClose={()=>setSelected(null)} wide><div className="modal-body"><p>Saved at {new Date(current.created_at).toLocaleString('en-SG')}. The main handover screen shows the latest state.</p>
      {Object.entries(current.data.snapshot).filter(([key,value])=>Array.isArray(value)).map(([key,value])=><section key={key}><h3>{key.replaceAll('_',' ')}</h3>{(value as Row[]).length?(value as Row[]).map(r=><p key={r.id}>{r.data.patient_name||w.records.find(p=>p.id===r.data.patient_id)?.data.name||''}{r.data.patient_id?' · ':''}{r.data.time?r.data.time+' · ':''}{r.data.title||r.data.name||r.data.reason||r.data.recipient||r.data.text} {r.data.due||''}</p>):<p className="muted">None at preparation time.</p>}</section>)}
      <BusyButton className="primary" onClick={async()=>{await w.act('handover.acknowledge',{id:current.id});w.notify('Handover acknowledged')}}>Acknowledge handover</BusyButton>
    </div></Modal>}
  </section>;
}

export function ClinicalOverview({days}:{days:number}) {
  const w=useWorkspace();const clinic=w.snapshot?.clinic.id;
  const [data,setData]=useState<any>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[receipt,setReceipt]=useState<Receipt|null>(null);
  useEffect(()=>{let live=true;setError('');setData(null);api('/v2/overview?days='+days).then(r=>{if(live)setData(r)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[clinic,days,attempt]);
  return <section className="panel section-gap"><div className="panel-heading"><h2>Clinical record overview</h2><button className="text-button" onClick={()=>setAttempt(n=>n+1)}>Refresh clinical overview</button></div>
    {error?<p role="alert" className="error">{error}</p>:!data?<p role="status" className="spine-state">Loading clinical records…</p>:<>
      <div className="metric-grid"><div className="metric"><span>Patient records</span><strong>{data.patient_count}</strong></div><div className="metric"><span>Events · last {days} days</span><strong>{data.event_count}</strong></div></div>
      <div className="assistant-chart">{data.categories.map((g:any)=><div key={g.name}><span>{g.name.replaceAll('_',' ')}</span><meter min={0} max={Math.max(1,data.event_count)} value={g.count}/><b>{g.count}</b></div>)}</div>
      <div className="panel-heading"><h3>Values outside supplied ranges</h3><Badge>Latest {data.flagged_limit} maximum</Badge></div><div className="table-wrap"><table><thead><tr><th>Patient</th><th>Measurement</th><th>Value</th><th>Supplied range</th><th>Evidence</th></tr></thead><tbody>{data.flagged.map((r:any,i:number)=><tr key={r.event_id+':'+i}>
        <td><button className="text-button" onClick={()=>navigate('Patient',r.patient_id)}>{r.patient_name}</button></td><td>{r.name}</td><td>{r.value} {r.unit} <Badge tone="amber">{r.flag}</Badge></td><td>{r.ref_low??'—'}–{r.ref_high??'—'} {r.unit}</td><td>{r.source?<button className="text-button" onClick={()=>setReceipt(r.source)}>Open source</button>:'Source needed'}</td>
      </tr>)}</tbody></table>{!data.flagged.length&&<p className="spine-state">No values outside supplied ranges in this period.</p>}</div><p className="panel-bottom">Includes imported laboratory events. These are numeric comparisons, without clinical interpretation.</p>
    </>}{receipt&&<ReceiptView receipt={receipt} onClose={()=>setReceipt(null)}/>}</section>;
}
