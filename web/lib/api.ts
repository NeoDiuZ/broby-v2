import {Command} from './types';
export class ApiError extends Error {constructor(public status:number,message:string){super(message)}}
export function identity(){return {clinic:localStorage.getItem('broby-clinic')||'clinic-east',actor:localStorage.getItem('broby-actor')||'clinic-east-vet'}}
export function headers(){const i=identity();return {'x-clinic-id':i.clinic,'x-actor-id':i.actor}}
export async function api(path:string,options:RequestInit={}){
 const r=await fetch('/api'+path,{...options,headers:{...headers(),...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers}});
 if(!r.ok){if(r.status===401)window.dispatchEvent(new Event('broby-auth-required'));let b;try{b=await r.json()}catch{b={detail:'The server could not complete this request'}}throw new ApiError(r.status,typeof b.detail==='string'?b.detail:JSON.stringify(b.detail))}
 return r.json();
}
export const command=(action:string,payload:Record<string,any>,key=crypto.randomUUID())=>api('/actions',{method:'POST',body:JSON.stringify({action,payload,key})});
export function openDB():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const r=indexedDB.open('broby-v2-local',1);r.onupgradeneeded=()=>{r.result.createObjectStore('pending',{keyPath:'id'});r.result.createObjectStore('audio',{keyPath:'id'});r.result.createObjectStore('recordings',{keyPath:'id'})};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
export async function localPut(store:string,value:any){const db=await openDB();return new Promise<void>((resolve,reject)=>{const tx=db.transaction(store,'readwrite');tx.objectStore(store).put(value);tx.oncomplete=()=>{db.close();resolve()};tx.onerror=()=>{db.close();reject(tx.error)}})}
export async function localAll(store:string):Promise<any[]>{const db=await openDB();return new Promise((resolve,reject)=>{const tx=db.transaction(store);const r=tx.objectStore(store).getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);tx.oncomplete=()=>db.close()})}
export async function localDelete(store:string,id:string){const db=await openDB();return new Promise<void>((resolve,reject)=>{const tx=db.transaction(store,'readwrite');tx.objectStore(store).delete(id);tx.oncomplete=()=>{db.close();resolve()};tx.onerror=()=>reject(tx.error)})}
export async function saveNote(payload:Record<string,any>){const i=identity();const id=crypto.randomUUID();const item={id,...i,cmd:{action:'source.add',payload,key:id},status:'pending',created:Date.now()};await localPut('pending',item);await syncPending();return id}
let syncing=false;
export async function syncPending(){if(syncing)return;syncing=true;try{const i=identity();for(const x of await localAll('pending')){if(x.clinic!==i.clinic||x.actor!==i.actor||x.status==='conflict')continue;try{await api('/actions',{method:'POST',body:JSON.stringify(x.cmd)});await localDelete('pending',x.id)}catch(e){if(e instanceof ApiError&&e.status<500)await localPut('pending',{...x,status:'conflict',error:e.message});else break}}}finally{syncing=false;window.dispatchEvent(new Event('broby-sync'))}}

export async function downloadFile(path:string,name:string){const r=await fetch('/api'+path,{headers:headers()});if(!r.ok){const b=await r.json();throw new Error(b.detail||'Download failed')}const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),3000)}
