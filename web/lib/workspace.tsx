'use client';
import React,{createContext,useCallback,useContext,useEffect,useRef,useState} from 'react';
import {api,command,identity,localAll,syncPending,ApiError} from './api';
import {cacheSnapshot,cachedSnapshot,deviceScopeAllowed, revokeOfflineAccess} from './device';
import {recordingStore} from './recording';
import {Snapshot,Row} from './types';
type Context={snapshot:Snapshot|null;records:Row[];error:string;loading:boolean;offline:boolean;pending:any[];cachedAt:number|null;refresh:()=>Promise<void>;act:(a:string,p:any,key?:string)=>Promise<any>;switchIdentity:(clinic:string,actor:string)=>void;notify:(text:string)=>void;toast:string};
const C=createContext<Context>(null!);
export function Workspace({children}:{children:React.ReactNode}){
 const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[offline,setOffline]=useState(false),[pending,setPending]=useState<any[]>([]),[toast,setToast]=useState(''),[cachedAt,setCachedAt]=useState<number|null>(null);
 const seq=useRef(0),timer=useRef<ReturnType<typeof setTimeout>|null>(null),inflight=useRef(false);
 const notify=useCallback((text:string)=>{setToast(text);if(timer.current)clearTimeout(timer.current);timer.current=setTimeout(()=>setToast(''),5000)},[]);
 const refresh=useCallback(async()=>{
  if(inflight.current)return;inflight.current=true;const n=++seq.current,i=identity();
  try{const data=await api('/bootstrap');if(n===seq.current){setSnapshot(data);setError('');setOffline(false);setCachedAt(null);await syncPending();try{await cacheSnapshot(data)}catch(e){setError('Connected, but device copy could not be saved: '+(e as Error).message)}}}
  catch(e){if(n===seq.current){if(e instanceof ApiError&&[401,403].includes(e.status)){setSnapshot(null);setError(e.message);await revokeOfflineAccess();window.dispatchEvent(new Event('broby-auth-required'))}else{setOffline(true);try{const cache=await cachedSnapshot(i.clinic,i.actor);if(n===seq.current){setSnapshot(cache?.snapshot||null);setCachedAt(cache?.savedAt||null);setError(cache?'Showing saved data. Reconnect for current records and server actions.':'No current device copy is available for this clinic. Reconnect to load it.')}}catch(error){setError((error as Error).message)}}}}
  finally{if(n===seq.current)setLoading(false);try{const all=await localAll('pending');if(n===seq.current)setPending(all.filter(x=>x.clinic===i.clinic&&x.actor===i.actor))}catch{}inflight.current=false}
 },[]);
 useEffect(()=>{void refresh();const on=()=>{void refresh().then(()=>syncPending()).then(refresh).catch(()=>{})};const off=()=>setOffline(true);window.addEventListener('online',on);window.addEventListener('offline',off);const t=setInterval(()=>void refresh(),6000);return()=>{seq.current++;clearInterval(t);window.removeEventListener('online',on);window.removeEventListener('offline',off);if(timer.current)clearTimeout(timer.current)}},[refresh]);
 const act=useCallback(async(a:string,p:any,key?:string)=>{if(offline)throw new Error('Reconnect before making this change. Typed notes and voice notes can be saved on this device.');try{const result=await command(a,p,key);await refresh();return result}catch(e){notify((e as Error).message);throw e}},[refresh,notify,offline]);
 const switchIdentity=(clinic:string,actor:string)=>{if(['requesting','recording','paused','saving'].includes(recordingStore.getSnapshot().status)){notify('Finish the voice note before switching clinic or role.');return}if(offline&&!deviceScopeAllowed(clinic,actor)){notify('This clinic is not available offline. Reconnect and sign in.');return}seq.current++;localStorage.setItem('broby-clinic',clinic);localStorage.setItem('broby-actor',actor);setSnapshot(null);setLoading(true);location.hash='Home';inflight.current=false;void refresh()};
 return <C.Provider value={{snapshot,records:snapshot?.records||[],error,loading,offline,pending,cachedAt,refresh,act,switchIdentity,notify,toast}}><React.Fragment key={snapshot?snapshot.clinic.id+':'+snapshot.actor.id+':'+[...snapshot.permissions,...(snapshot.read_permissions||[])].sort().join(','):'locked'}>{children}</React.Fragment></C.Provider>
}
export const useWorkspace=()=>useContext(C);
export const useRows=(kind:string)=>useWorkspace().records.filter(r=>r.kind===kind);
