'use client';
import {useCallback,useEffect,useState} from 'react';
import {api,ApiError} from '@/lib/api';
import {BusyButton} from './ui';

type Lead = {
 id:string; contact_name:string; clinic_name:string; country:string;
 contact_channel:string; contact_handle:string; subject:string; message:string;
 status:string; created_at:string; contacted_at:string|null;
};

export function MarketingLeads(){
 const pageSize=100;
 const [leads,setLeads]=useState<Lead[]>([]);
 const [outstanding,setOutstanding]=useState(0);
 const [total,setTotal]=useState(0);
 const [offset,setOffset]=useState(0);
 const [available,setAvailable]=useState(false);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState('');
 const refresh=useCallback(async(pageOffset:number)=>{
  setLoading(true);
  try{
   const result=await api('/marketing/leads?offset='+pageOffset);
   setLeads(result.leads);setOutstanding(result.outstanding);setTotal(result.total);
   setOffset(pageOffset);setAvailable(true);setError('');
  }catch(e){
   if(e instanceof ApiError&&e.status===403){setAvailable(false);setError('');return}
   setError((e as Error).message);
  }finally{setLoading(false)}
 },[]);
 useEffect(()=>{void refresh(0)},[refresh]);
 if(!available&&!error)return null;
 return <div className="settings-section">
  <h3>Website enquiries · {outstanding} new</h3>
  <p>Requests from the public onboarding and contact forms are saved here. They do not send an email or WhatsApp message automatically.</p>
  <button className="secondary" disabled={loading} onClick={()=>void refresh(offset)}>Refresh enquiries</button>
  {error&&<p role="alert" className="error">{error}</p>}
  {!leads.length&&<p>No enquiries yet.</p>}
  {leads.map(lead=><article className="file-row" key={lead.id}>
   <div>
    <strong>{lead.contact_name}{lead.clinic_name?' · '+lead.clinic_name:''}</strong>
    <small>{lead.country} · {new Date(lead.created_at).toLocaleString('en-SG')} · {lead.status}</small>
    <p>{lead.contact_channel}: {lead.contact_handle}</p>
    {lead.subject&&<p><b>{lead.subject}</b></p>}
    {lead.message&&<p style={{whiteSpace:'pre-wrap'}}>{lead.message}</p>}
   </div>
   {lead.status==='new'&&<BusyButton onClick={async()=>{
    await api('/marketing/leads/'+lead.id+'/contacted',{method:'POST'});
    await refresh(offset);
   }}>Mark contacted</BusyButton>}
  </article>)}
  {total>pageSize&&<nav aria-label="Website enquiry pages" className="actions">
   <button className="secondary" disabled={loading||offset===0} onClick={()=>void refresh(offset-pageSize)}>Previous</button>
   <span>{offset+1}–{offset+leads.length} of {total}</span>
   <button className="secondary" disabled={loading||offset+pageSize>=total} onClick={()=>void refresh(offset+pageSize)}>Next</button>
  </nav>}
 </div>;
}
