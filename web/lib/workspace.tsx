'use client';
import React,{createContext,useCallback,useContext,useEffect,useRef,useState} from 'react';
import {api,command,identity,localAll,syncPending} from './api';
import {recordingStore} from './recording';
import {Snapshot,Row} from './types';
type Context={snapshot:Snapshot|null;records:Row[];error:string;loading:boolean;offline:boolean;pending:any[];refresh:()=>Promise<void>;act:(a:string,p:any)=>Promise<any>;switchIdentity:(clinic:string,actor:string)=>void;notify:(text:string)=>void;toast:string};
const C=createContext<Context>(null!);
export function Workspace({children}:{children:React.ReactNode}){
 const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[offline,setOffline]=useState(false),[pending,setPending]=useState<any[]>([]),[toast,setToast]=useState('');
 const seq=useRef(0);const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
 const notify=useCallback((text:string)=>{setToast(text);if(timer.current)clearTimeout(timer.current);timer.current=setTimeout(()=>setToast(''),5000)},[]);
 const refresh=useCallback(async()=>{const n=++seq.current;const i=identity();try{const data=await api('/bootstrap');if(n===seq.current){setSnapshot(data);setError('');setOffline(false);localStorage.setItem('broby-snapshot-'+i.clinic+'-'+i.actor,JSON.stringify(data))}}catch(e){if(n===seq.current){setError((e as Error).message);setOffline(true)}}finally{if(n===seq.current)setLoading(false);const all=await localAll('pending');if(n===seq.current)setPending(all.filter(x=>x.clinic===i.clinic&&x.actor===i.actor))}},[]);
 useEffect(()=>{const i=identity();try{const cache=localStorage.getItem('broby-snapshot-'+i.clinic+'-'+i.actor);if(cache)setSnapshot(JSON.parse(cache))}catch{};void refresh();const on=()=>{void syncPending().then(refresh)};const off=()=>setOffline(true);window.addEventListener('online',on);window.addEventListener('offline',off);const t=setInterval(()=>void refresh(),6000);return()=>{clearInterval(t);window.removeEventListener('online',on);window.removeEventListener('offline',off);if(timer.current)clearTimeout(timer.current)}},[refresh]);
 const act=useCallback(async(a:string,p:any)=>{try{const result=await command(a,p);await refresh();return result}catch(e){notify((e as Error).message);throw e}},[refresh,notify]);
 const switchIdentity=(clinic:string,actor:string)=>{if(['requesting','recording','paused','saving'].includes(recordingStore.getSnapshot().status)){notify('Finish the voice note before switching clinic or role.');return}seq.current++;localStorage.setItem('broby-clinic',clinic);localStorage.setItem('broby-actor',actor);setSnapshot(null);setLoading(true);location.hash='Home';void refresh()};
 return <C.Provider value={{snapshot,records:snapshot?.records||[],error,loading,offline,pending,refresh,act,switchIdentity,notify,toast}}>{children}</C.Provider>
}
export const useWorkspace=()=>useContext(C);
export const useRows=(kind:string)=>useWorkspace().records.filter(r=>r.kind===kind);
