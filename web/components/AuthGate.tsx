'use client';
import {useEffect,useRef,useState} from 'react';
import {unlockOnline,unlockOffline,revokeOfflineAccess,lockDevice,deviceInfo,PreviousPasswordRequired,prepareOfflineShell} from '@/lib/device';
import {recordingStore,stopRecording} from '@/lib/recording';
import {identity} from '@/lib/api';
import type {Snapshot} from '@/lib/types';
type Session={authenticated:boolean;mode:string;username?:string;expires_at?:string};
export default function AuthGate({children}:{children:React.ReactNode}){
 const [session,setSession]=useState<Session|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[unlocked,setUnlocked]=useState(false),[unavailable,setUnavailable]=useState(false),[previous,setPrevious]=useState(false),[username,setUsername]=useState('');
 const locking=useRef(false),checking=useRef<Promise<void>|null>(null);
 const [checkingSession,setCheckingSession]=useState(true);
 const sessionRequest=()=>fetch('/api/session',{cache:'no-store',signal:AbortSignal.timeout(8000)});
 async function closeDevice(revoke:boolean){if(locking.current)return;locking.current=true;try{if(['recording','paused'].includes(recordingStore.getSnapshot().status))await stopRecording()}catch{/* Existing recovery buffers retain unsaved audio. */}finally{try{if(revoke)await revokeOfflineAccess();else lockDevice();setUnlocked(false)}finally{locking.current=false}}}
 async function bootstrap(clinic?:string,actor?:string):Promise<Snapshot>{const i=identity();const r=await fetch('/api/bootstrap',{cache:'no-store',headers:{'x-clinic-id':clinic||i.clinic,'x-actor-id':actor||i.actor}});if(!r.ok)throw new Error('This account cannot open the selected clinic. Sign in again.');return r.json()}
 async function check(){
  if(checking.current)return checking.current;setCheckingSession(true);const work=(async()=>{
  try{const r=await sessionRequest();if(!r.ok)throw new Error('Server unavailable');const s:Session=await r.json();setSession(s);setUnavailable(false);
   if(!s.authenticated){await closeDevice(true)}
   else if(s.mode==='demo'){if(deviceInfo()?.username==='local-demo'){setUnlocked(true);return}const data=await bootstrap();await unlockOnline('local-demo','broby-local-demo-device-only',data,new Date(Date.now()+12*3600000).toISOString());setUnlocked(true)}
   else{setUsername(s.username||'');if(deviceInfo()?.username===s.username)setUnlocked(true)}
  }catch{setUnavailable(true);setSession(null)}finally{setCheckingSession(false)}
  })();checking.current=work;try{await work}finally{checking.current=null}
 }
 useEffect(()=>{
  setUsername(localStorage.getItem('broby-device-user')||'');void check();
  void prepareOfflineShell();
  const expired=async()=>{await closeDevice(true);setSession({authenticated:false,mode:'password'});setError('Sign in again. Unsynced work is retained on this device.')};
  const locked=()=>setUnlocked(false);
  const external=(event:StorageEvent)=>{if(event.key==='broby-lock-signal'){void closeDevice(false)}};
  const online=()=>{void check()};
  window.addEventListener('broby-auth-required',expired);window.addEventListener('broby-device-locked',locked);window.addEventListener('storage',external);window.addEventListener('online',online);
  return()=>{window.removeEventListener('broby-auth-required',expired);window.removeEventListener('broby-device-locked',locked);window.removeEventListener('storage',external);window.removeEventListener('online',online)};
 },[]);
 useEffect(()=>{if(!unlocked)return;const t=setInterval(()=>{const info=deviceInfo();if(info&&Date.now()>=info.expiresAt){void closeDevice(false);setError('Device access expired. Reconnect and sign in; saved work is retained.')}},5000);return()=>clearInterval(t)},[unlocked]);
 if(unlocked)return children;
 return <main className="login-page"><section className="panel"><span className="wordmark">Broby<span>•</span></span><h1>{unavailable?'Open saved workspace':session?.authenticated?'Unlock this device':'Welcome back'}</h1><p>{unavailable?'The server is unavailable. Use the account password from your last successful sign-in to unlock saved work.':'Sign in to your clinic account and unlock encrypted work saved on this device.'}</p><p className="muted">Offline access lasts until the last verified session expires, up to 12 hours. A reload locks this device. Unsynced notes remain encrypted.</p>
 <form className="form" onSubmit={async event=>{
  event.preventDefault();if(checkingSession||busy)return;setBusy(true);setError('');const values=Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string,string>;
  try{
   let probe:Response|null=null;try{probe=await sessionRequest()}catch{}
   if(!probe||probe.status>=500){const lease=await unlockOffline(values.username,values.password);const i=identity();if(!lease.scopes.some(s=>s.clinic===i.clinic&&s.actor===i.actor)){const first=lease.scopes[0];if(!first)throw new Error('No clinic was saved for offline use.');localStorage.setItem('broby-clinic',first.clinic);localStorage.setItem('broby-actor',first.actor)}setUnavailable(true);setUnlocked(true);return}
   const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:values.username,password:values.password,code:values.code||''})});const b=await r.json();if(!r.ok)throw new Error(b.detail||'Sign-in failed');
   const result=await fetch('/api/session',{cache:'no-store'});if(!result.ok)throw new Error('Could not verify the new session');const verified:Session=await result.json();if(!verified.authenticated||verified.username!==values.username)throw new Error('Could not verify this account');
   const i=identity();let data:Snapshot;try{data=await bootstrap(i.clinic,i.actor)}catch{data=await bootstrap(b.clinic,b.actor)}
   await unlockOnline(values.username,values.password,data,verified.expires_at!,values.previous_password||undefined);
   localStorage.setItem('broby-clinic',data.clinic.id);localStorage.setItem('broby-actor',data.actor.id);setSession(verified);setUnavailable(false);setPrevious(false);setUnlocked(true);
  }catch(e){setPrevious(e instanceof PreviousPasswordRequired);setError((e as Error).message)}finally{setBusy(false)}
 }}>
 <label>Username<input name="username" autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} required/></label>
 <label>Password<input name="password" type="password" autoComplete="current-password" required/></label>
 {!unavailable&&<label>Authenticator or recovery code (if enabled)<input name="code" inputMode="text" autoComplete="one-time-code" maxLength={10}/></label>}
 {previous&&<label>Previous password used on this device<input name="previous_password" type="password" autoComplete="off" required/></label>}
 <button className="primary" disabled={busy||checkingSession}>{checkingSession?'Checking session…':busy?'Opening saved work…':unavailable?'Unlock saved workspace':'Sign in and unlock'}</button>
 </form>{error&&<p role="alert" className="error">{error}</p>}</section></main>
}
