'use client';
import React,{useEffect,useRef,useState} from 'react';
import {CalendarBlank,Pill,FileText,ShieldCheck,Microphone,LinkSimple} from '@phosphor-icons/react';
import {PatientMark,Badge} from '@/components/ui';
import {OwnerTransfer} from '@/components/OwnerTransfer';
import {patientAge} from '@/lib/types';

export default function Owner(){
 const [data,setData]=useState<any>(null),[error,setError]=useState(''),[token,setToken]=useState<string|null>(null),[petId,setPetId]=useState('');
 const [tab,setTab]=useState('Records'),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[share,setShare]=useState(''),[question,setQuestion]=useState(''),[answer,setAnswer]=useState<any>(null),[editing,setEditing]=useState<any>(null),[revision,setRevision]=useState(0);
 const submission=useRef({body:'',key:''});
 useEffect(()=>setToken(new URLSearchParams(location.search).get('token')||''),[]);
 const base=token?'/api/owner/'+encodeURIComponent(token):'/api/owner-account'+(petId?'/pets/'+encodeURIComponent(petId):'');
 useEffect(()=>{if(token===null)return;let live=true;setError('');setData(null);setEditing(null);setAnswer(null);setShare('');
  fetch(base).then(async r=>{const b=await r.json();if(!r.ok)throw new Error(typeof b.detail==='string'?b.detail:'Open a valid clinic link to continue.');if(live)setData(b)}).catch(e=>{if(live)setError(e.message)});
  return()=>{live=false};
 },[base,token,revision]);
 const send=async(path:string,body:any={},method='POST')=>{const r=await fetch(base+path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const b=await r.json();if(!r.ok)throw new Error(typeof b.detail==='string'?b.detail:'Check the form and try again.');return b};
 const due=data?.reminders.filter((r:any)=>r.data.status==='due')||[];
 const dueLabel=(date:string)=>date<data.today?'Overdue':date===data.today?'Due today':'Upcoming';
 return <main className="owner-page"><span className="wordmark">Broby<span>•</span></span>{!data?<p role={error?'alert':'status'}>{error||'Opening your pet’s approved record…'}</p>:<>
  {data.pets?.length>0&&<label className="demo-identity">Saved pets<select aria-label="Saved pets" value={data.patient.id} onChange={e=>{setPetId(e.target.value);setNotice('')}}>{data.pets.map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
  <OwnerTransfer key={base} base={base}/>
  <div className="owner-header"><PatientMark patient={data.patient} large/><div><Badge tone="teal"><ShieldCheck size={13}/> Shared by your clinic</Badge><h1>{data.patient.data.name}’s record</h1><p className="muted">{data.patient.data.breed} · {patientAge(data.patient.data)}</p>{data.patient.data.date_of_birth&&<p className="muted">Born {data.patient.data.date_of_birth}</p>}</div></div>
  <p className="muted section-gap">Your veterinarian’s approved notes, prescribed medications, and upcoming care.</p>
  <div className="actions section-gap"><a className="secondary" href={base+'/discharge.pdf'}>Download care instructions</a>{token&&<>
   <button className="secondary" disabled={busy} onClick={async()=>{setBusy(true);try{const saved=await fetch('/api/owner-account/claim/'+encodeURIComponent(token),{method:'POST'});if(!saved.ok)throw new Error('Could not save access. Reopen the clinic link and retry.');setPetId(data.patient.id);setToken('');history.replaceState(null,'','/owner');setNotice('This pet is saved on this browser. Open and save each clinic link to add another pet.')}catch(e){setNotice((e as Error).message)}finally{setBusy(false)}}}>Save access on this device</button>
   <button className="secondary" disabled={busy} onClick={async()=>{setBusy(true);try{const r=await send('/share');setShare(location.origin+r.url)}catch(e){setNotice((e as Error).message)}finally{setBusy(false)}}}><LinkSimple size={15}/> Create referral link</button>
  </>}</div>
  {share&&<div className="inline-notice"><label>Read-only approved records · share with the receiving clinic<input readOnly value={share}/></label><button className="secondary" onClick={()=>void navigator.clipboard.writeText(share)}>Copy</button></div>}
  {notice&&<p role="status" className="inline-notice">{notice}</p>}
  <div className="tabs owner-tabs">{['Records','Before your visit','Ask the clinic'].map(t=><button key={t} className={tab===t?'active':''} onClick={()=>setTab(t)}>{t}</button>)}</div>
  {tab==='Records'&&<>
   <section className="panel"><div className="panel-heading"><h2>Visit history</h2><FileText size={18}/></div><div className="event-list">{data.events.map((e:any)=><article className="event" key={e.id}><div className="event-content"><div className="event-top"><Badge tone="teal">Approved</Badge><time>{new Date(e.data.occurred_at).toLocaleDateString('en-SG')}</time></div><h3>{e.data.title}</h3><p className="preserve">{e.data.body}</p>{e.data.observations?.map((o:any)=><p key={o.id}>{o.name}: {typeof o.value==='boolean'?(o.value?'Yes':'No'):o.value} {o.unit}{o.ref_low!=null||o.ref_high!=null?` · supplied reference ${o.ref_low??'—'}–${o.ref_high??'—'}`:''}</p>)}</div></article>)}{!data.events.length&&<p className="muted">No visit records have been shared yet.</p>}</div></section>
   <section className="panel"><div className="panel-heading"><h2>Medications</h2><Pill size={19}/></div>{data.medications.length?data.medications.map((m:any)=><div className="owner-med" key={m.id}><strong>{m.data.name}</strong><p>{m.data.dose} · {m.data.frequency}</p><p>{m.data.instructions}</p></div>):<div className="owner-med">No medications have been recorded.</div>}</section>
   <section className="panel"><div className="panel-heading"><h2>What’s due</h2><CalendarBlank size={19}/></div>{due.length?due.map((r:any)=><div className="owner-med" key={r.id}><strong>{r.data.title}</strong><p>{r.data.due} <Badge tone={r.data.due<=data.today?'amber':'neutral'}>{dueLabel(r.data.due)}</Badge></p></div>):<div className="owner-med">No upcoming care reminders.</div>}</section>
   <section className="panel"><div className="panel-heading"><h2>Shared documents</h2><FileText size={19}/></div>{data.files?.length?data.files.map((f:any)=><div className="owner-med" key={f.id}><a href={base+'/files/'+f.id}>{f.data.name}</a></div>):<div className="owner-med">No documents shared yet.</div>}</section>
   <section className="panel"><div className="panel-heading"><h2>Your vet’s explanation</h2><Microphone size={19}/></div>{data.audio?.length?data.audio.map((r:any)=><div className="owner-med" key={r.id}><strong>Voice note {r.data.number}{r.data.title?' · '+r.data.title:''}</strong><audio controls preload="metadata" src={base+'/audio/'+r.id} aria-label={'Vet explanation '+r.data.number}/></div>):<div className="owner-med">No audio explanations shared yet.</div>}</section>
  </>}
  {tab==='Before your visit'&&<section className="panel"><div className="panel-heading"><h2>{editing?'Update your submission':'Tell the clinic what’s changed'}</h2></div>
   <form key={editing?.id||'new'} className="form" onSubmit={async e=>{
    e.preventDefault();setBusy(true);setNotice('');const form=e.currentTarget;const fields=Object.fromEntries(new FormData(form).entries());
    const body={...fields,urgent:fields.urgent==='on',...(editing?{version:editing.version}:{})};const serialized=base+JSON.stringify(body);
    if(submission.current.body!==serialized)submission.current={body:serialized,key:crypto.randomUUID()};
    try{await send('/intake'+(editing?'/'+editing.id:''),{...body,key:submission.current.key},editing?'PUT':'POST');setNotice('Your information was received and is waiting for the clinic to review.');form.reset();setEditing(null);setRevision(n=>n+1);submission.current={body:'',key:''}}catch(e){setNotice((e as Error).message)}finally{setBusy(false)}
   }}>
    <label>Reason for the visit<textarea name="reason" required maxLength={4000} rows={4} defaultValue={editing?.data.fields.reason||''}/></label>
    <label>Appetite and drinking<textarea name="appetite" maxLength={1000} defaultValue={editing?.data.fields.appetite||''}/></label>
    <label>Current medications<textarea name="medications" maxLength={2000} defaultValue={editing?.data.fields.medications||''}/></label>
    <label>Questions for your veterinarian<textarea name="questions" maxLength={2000} defaultValue={editing?.data.fields.questions||''}/></label>
    <label className="feature-lock"><input type="checkbox" name="urgent" defaultChecked={editing?.data.urgent||false}/> I want the clinic to know this is urgent</label>
    <p className="integration-note">This form is not monitored continuously. For urgent concerns, call {data.emergency_phone||'your clinic or an emergency veterinary service'} directly.</p>
    <div className="actions"><button className="primary" disabled={busy}>{busy?'Submitting…':editing?'Save changes':'Submit to clinic'}</button>{editing&&<button type="button" className="secondary" onClick={()=>setEditing(null)}>Cancel editing</button>}</div>
   </form>
   <div className="document-list"><h3>Your submissions</h3>{data.intakes?.map((r:any)=><article key={r.id} className="intake-card"><Badge>{r.data.status==='new'?'Awaiting review':r.data.status}</Badge><p className="preserve">{r.data.text}</p>{r.data.status==='new'&&<button className="secondary" onClick={()=>setEditing(r)}>Edit submission</button>}</article>)}</div>
  </section>}
  {tab==='Ask the clinic'&&<section className="panel"><div className="panel-heading"><h2>Saved care instructions</h2></div><div className="form"><p>Retrieve medication instructions and reminders already recorded by your clinic.</p><form onSubmit={async e=>{e.preventDefault();setBusy(true);try{setAnswer(await send('/help',{message:question}))}catch(e){setNotice((e as Error).message)}finally{setBusy(false)}}}><label>Your question<input value={question} onChange={e=>setQuestion(e.target.value)} required maxLength={2000} placeholder="What medication instructions were shared?"/></label><button className="primary" disabled={busy}>Show saved information</button></form>{answer&&<><p className="preserve">{answer.text}</p><p className="integration-note">{answer.notice}</p>{answer.emergency_phone&&<a href={'tel:'+answer.emergency_phone}>Call clinic: {answer.emergency_phone}</a>}</>}</div></section>}
  <p className="owner-footnote">{data.saved_access?'Saved access':'This private link'} expires {new Date(data.expires_at).toLocaleDateString('en-SG')}. Access may be revoked by the clinic. Contact your clinic for medical questions.</p>
 </>}</main>;
}
