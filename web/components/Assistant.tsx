'use client';
import {useEffect,useRef,useState} from 'react';
import {ArrowRight,ArrowUpRight,FileText,Sparkle,X} from '@phosphor-icons/react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {Row} from '@/lib/types';
import {Badge,BusyButton,SourceModal} from './ui';
import {navigate} from './App';
import {ReferenceChart} from './ReferenceChart';

type Turn={turn_id:string;conversation_id?:string;request_key:string;message:string;patient_id?:string;status:string;text:string;created_at?:string;sources?:Row[];choices?:Row[];navigate?:string;navigate_section?:string;action?:{action:string;payload:Record<string,unknown>};review?:{title:string;fields:{label:string;value:string}[];effects:string[]};execution?:any;dashboard?:any};
type Conversation={id:string;title:string;patient_id?:string};
export default function Assistant({patientId,onClose}:{patientId?:string;onClose:()=>void}) {
 const w=useWorkspace();const [input,setInput]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const [conversations,setConversations]=useState<Conversation[]>([]),[conversationId,setConversationId]=useState<string>(),[turns,setTurns]=useState<Turn[]>([]),[selectedPatient,setSelectedPatient]=useState(patientId),[source,setSource]=useState<Row|null>(null);
 const generation=useRef(0),pending=useRef(false);
 useEffect(()=>{const n=++generation.current;void api('/assistant/conversations').then(r=>{if(n===generation.current)setConversations(r)}).catch(e=>{if(n===generation.current)setError(e.message)}).finally(()=>{if(n===generation.current)setLoading(false)});return()=>{generation.current++}},[]);
 const open=async(id:string)=>{
  if(pending.current)return;
  const n=++generation.current;setError('');setConversationId(id||undefined);setTurns([]);setInput('');setSource(null);
  if(!id){setSelectedPatient(patientId);return}
  setLoading(true);
  try {const r=await api('/assistant/conversations/'+encodeURIComponent(id));if(n===generation.current){setTurns(r.turns);setSelectedPatient(r.patient_id)}}
  catch(e){if(n===generation.current)setError((e as Error).message)}
  finally{if(n===generation.current)setLoading(false)}
 };
 const ask=async(text:string,pid=selectedPatient,retry?:Turn)=>{
  if(pending.current||loading)return;
  pending.current=true;setBusy(true);setError('');setInput('');const n=generation.current;
  const key=retry?.request_key||crypto.randomUUID();
  const draft:Turn=retry||{turn_id:key,request_key:key,message:text,patient_id:pid,status:'pending',text:''};
  setTurns(t=>retry?t.map(x=>x.turn_id===retry.turn_id?{...x,status:'pending'}:x):[...t,draft]);
  try{
   const result=await api('/assistant',{method:'POST',body:JSON.stringify({message:text,patient_id:pid,conversation_id:conversationId,key})});
   if(n!==generation.current)return;
   setConversationId(result.conversation_id);setTurns(t=>t.map(x=>x.turn_id===draft.turn_id?{...draft,...result,status:'completed'}:x));
   const list=await api('/assistant/conversations');if(n===generation.current)setConversations(list);
  }catch(e){if(n===generation.current){setError((e as Error).message);setTurns(t=>t.map(x=>x.turn_id===draft.turn_id&&x.status!=='completed'?{...x,status:'failed',text:'The answer was interrupted. Retry this question or reopen its saved conversation.'}:x))}}
  finally{pending.current=false;if(n===generation.current)setBusy(false)}
 };
 const confirm=async(turn:Turn)=>{
  if(pending.current)return;
  pending.current=true;setBusy(true);setError('');const n=generation.current;
  try{
   const result=await api('/assistant/conversations/'+encodeURIComponent(turn.conversation_id! )+'/turns/'+encodeURIComponent(turn.turn_id)+'/confirm',{method:'POST'});
   if(n===generation.current){setTurns(t=>t.map(x=>x.turn_id===turn.turn_id?{...x,execution:result}:x));await w.refresh();w.notify('Confirmed action completed')}
  }catch(e){if(n===generation.current)setError((e as Error).message)}
  finally{pending.current=false;if(n===generation.current)setBusy(false)}
 };
 return <><div className="drawer-scrim" onClick={onClose}/><aside className="assistant-drawer" aria-label="Broby assistant">
  <header><div><Sparkle size={21}/><h2>Ask Broby</h2></div><button className="icon" aria-label="Close assistant" onClick={onClose}><X size={20}/></button></header>
  <div className="assistant-scope"><Badge tone="teal">{selectedPatient?w.records.find(r=>r.id===selectedPatient)?.data.name||'Selected patient':'Clinic records'}</Badge><span>Private to your clinic login</span></div>
  <div className="assistant-history-controls"><select aria-label="Saved conversations" value={conversationId||''} disabled={busy||loading} onChange={e=>void open(e.target.value)}><option value="">New conversation</option>{conversations.map(c=><option value={c.id} key={c.id}>{c.title}</option>)}</select><button className="secondary" disabled={busy||loading} onClick={()=>void open('')}>New</button></div>
  <div className="chat-history" aria-live="polite">
   {loading&&<p>Loading saved conversations…</p>}
   {!loading&&!turns.length&&<div className="chat-welcome"><Sparkle size={30}/><h3>Your records, within reach.</h3><p>Find recorded facts or propose an action. Answers are saved so you can return later.</p>{[selectedPatient?'Show patient history':"What’s on today?",'Show outstanding invoices','Which stock is low?'].map(q=><button key={q} disabled={busy} onClick={()=>void ask(q)}>{q}<ArrowUpRight size={15}/></button>)}</div>}
   {turns.map(m=><div key={m.turn_id}><article className="chat-message user"><small>YOU</small><p className="preserve">{m.message}</p></article><article className="chat-message assistant"><small>BROBY{m.created_at?' · Saved '+new Date(m.created_at).toLocaleString('en-SG'):''}</small>
    {m.status==='pending'?<p>Checking your records…</p>:<p className="preserve">{m.execution&&m.action?'This action was completed after confirmation. The saved review below shows what was approved.':m.text}</p>}
    {m.status!=='completed'&&<button className="secondary" disabled={busy} onClick={()=>void ask(m.message,m.patient_id,m)}>Retry question</button>}
    {m.status==='completed'&&<>
     {m.choices?.map(p=><button className="secondary" disabled={busy} key={p.id} onClick={()=>{setSelectedPatient(p.id);void ask(m.message,p.id)}}>{p.data.name} · {p.data.species}</button>)}
     {!!m.sources?.length&&<div className="receipts">{m.sources.map(s=><button key={s.id} onClick={()=>setSource(s)}><FileText size={13}/>{s.data.title||s.data.name||s.kind}</button>)}</div>}
     {m.navigate&&<button className="text-button" onClick={()=>{navigate(m.navigate!,m.navigate_section);onClose()}}>Open {m.navigate_section||m.navigate}<ArrowUpRight size={14}/></button>}
     {m.dashboard&&<div className="assistant-chart"><strong>{m.dashboard.title}</strong>{m.dashboard.trend?<ReferenceChart data={m.dashboard.trend} sourceLabel="record" onPoint={id=>{const row=m.sources?.find(r=>r.id===id);if(row)setSource(row)}}/>:m.dashboard.groups.map((g:any)=><div key={g.label}><span>{g.label}</span><meter min={0} max={Math.max(1,m.dashboard.count)} value={g.count}/><b>{g.count}</b></div>)}<BusyButton disabled={busy} onClick={async()=>{await w.act('dashboard.save',{name:m.dashboard.title,query:m.dashboard.query});navigate('Reports');onClose()}}>Save this view</BusyButton></div>}
     {m.action&&(m.review?<section aria-label="Proposed change" className="action-preview"><strong>{m.review.title}</strong><dl>{m.review.fields.map(f=><div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl>{m.review.effects.map(effect=><p key={effect}>{effect}</p>)}</section>:<pre className="action-preview">{JSON.stringify(m.action,null,2)}</pre>)}
     {m.action&&(m.execution?<><p role="status">Action completed. Reopening this answer does not repeat it.</p>{m.action.action==='consultation.create'&&<button className="text-button" onClick={()=>{navigate('Consultation',m.execution.id);onClose()}}>Open consultation</button>}</>:<BusyButton className="primary" disabled={busy} onClick={()=>confirm(m)}>Confirm saved action</BusyButton>)}
    </>}
   </article></div>)}
   {error&&<p className="error" role="alert">{error}</p>}
  </div>
  <form className="chat-input" onSubmit={e=>{e.preventDefault();if(input.trim())void ask(input.trim())}}><input value={input} maxLength={4200} disabled={loading} onChange={e=>setInput(e.target.value)} placeholder="Ask about your clinic…" aria-label="Ask Broby"/><button className="primary icon" disabled={busy||loading||!input.trim()} aria-label="Send question"><ArrowRight size={19}/></button></form>
  <p className="chat-footnote">Saved answers show facts from that time. Ask again for current records. Does not diagnose or prescribe.</p>
 </aside>{source&&<SourceModal source={source} expectedVersion={source.version} onClose={()=>setSource(null)}/>}</>;
}
