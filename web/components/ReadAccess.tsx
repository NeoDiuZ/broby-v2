'use client';
import {useState} from 'react';
import {useWorkspace} from '@/lib/workspace';
import {READ_LABELS} from '@/lib/read-access';
import {AccountControls} from './AdvancedOperations';
import {api} from '@/lib/api';
import {revokeOfflineAccess} from '@/lib/device';
import {assertDeviceCanLock} from '@/lib/recording';
import {BusyButton} from './ui';

export function ReadAccess(){
 const w=useWorkspace(),[target,setTarget]=useState(''),[error,setError]=useState('');
 const snapshot=w.snapshot!,admin=snapshot.actor.data.role==='admin';
 if(!admin||!snapshot.read_permissions?.includes('read.staff'))return null;
 const members=w.records.filter(r=>r.kind==='member'&&r.id!==snapshot.actor.id),member=members.find(r=>r.id===target);
 const fields=(current:string[])=>Object.entries(READ_LABELS).map(([value,label])=><label className="feature-lock" key={value}><input type="checkbox" name="restriction" value={value} defaultChecked={current.includes(value)}/><span>Restrict {label.toLowerCase()}</span></label>);
 return <section className="settings-section"><h3>Read access</h3><p>These restrictions also apply to direct links, downloads and action results. Combined histories, files, saved AI conversations and full exports require access to every record area.</p><p>Connected screens refresh permissions every six seconds. A disconnected device may retain its last verified access until its sign-in expires, at most 12 hours. A restriction cannot recall a file already downloaded.</p>{error&&<p role="alert" className="error">{error}</p>}
 <details><summary>Clinic restrictions for vets and nurses</summary><form key={'clinic-'+snapshot.clinic.version} onSubmit={async e=>{e.preventDefault();const values=new FormData(e.currentTarget).getAll('restriction');setError('');try{await w.act('feature_locks.save',{version:snapshot.clinic.version,actions:[...(snapshot.clinic.data.locked_features||[]).filter((v:string)=>!READ_LABELS[v]),...values]});w.notify('Clinic read restrictions saved')}catch(e){setError((e as Error).message)}}}>{fields(snapshot.clinic.data.locked_features||[])}<button className="secondary">Save clinic read restrictions</button></form></details>
 <h4>Individual member restrictions</h4><p>Apply to the selected member, including a clinic administrator. The organization master retains access. Another administrator must change your own restrictions.</p><select aria-label="Member read access" value={target} onChange={e=>{setTarget(e.target.value);setError('')}}><option value="">Choose a member</option>{members.map(m=><option key={m.id} value={m.id}>{m.data.name} · {m.data.role}</option>)}</select>
 {member&&<form key={member.id+':'+member.version} onSubmit={async e=>{e.preventDefault();const data=new FormData(e.currentTarget);setError('');try{await w.act('access.member',{id:member.id,version:member.version,restrictions:data.getAll('restriction'),reason:data.get('reason')});w.notify('Member read restrictions saved')}catch(e){setError((e as Error).message)}}}>{fields(member.data.read_restrictions||[])}<label>Reason for this access change<input name="reason" required maxLength={500}/></label><button className="secondary">Save member read restrictions</button></form>}
 </section>;
}
export function RestrictedSettings(){
 const w=useWorkspace();
 return <section className="panel modal-body"><h1>Account and access</h1><p>Your current permissions restrict the full clinic settings view. Your own sign-in controls remain available.</p><p>Signed in as {w.snapshot?.actor.data.name}</p><AccountControls/><ReadAccess/><BusyButton onClick={async()=>{assertDeviceCanLock();await api('/logout',{method:'POST'});await revokeOfflineAccess();location.reload()}}>Sign out</BusyButton></section>;
}
