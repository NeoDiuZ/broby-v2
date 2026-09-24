/** Encrypted device persistence. No password or unwrapped key is stored. */
import type {Snapshot} from './types';
const STORES=['pending','audio','recordings','snapshots','drafts','vaults'];
const VERSION=2, ITERATIONS=600000, MAX_AGE=12*3600*1000;
type Sealed={iv:string;data:string};
type Scope={clinic:string;actor:string};
type Lease={username:string;issuedAt:number;expiresAt:number;scopes:Scope[];mode:string};
type Vault={id:string;salt:string;wrapped:Sealed;lease?:Sealed};
type OpenVault={owner:string;key:CryptoKey;lease:Lease};
let active:OpenVault|null=null;
let writes:Promise<unknown>=Promise.resolve();
export class DeviceLocked extends Error{}
export class PreviousPasswordRequired extends Error{}
const encode=new TextEncoder(),decode=new TextDecoder();
const b64=(bytes:Uint8Array)=>{let text='';for(let i=0;i<bytes.length;i+=32768)text+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(text)};
const bytes=(value:string)=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
export function openDB():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{
 const request=indexedDB.open('broby-v2-local',VERSION);
 request.onupgradeneeded=()=>{for(const name of STORES)if(!request.result.objectStoreNames.contains(name))request.result.createObjectStore(name,{keyPath:'id'})};
 request.onsuccess=()=>{request.result.onversionchange=()=>request.result.close();resolve(request.result)};
 request.onerror=()=>reject(request.error);request.onblocked=()=>reject(new Error('Close older Broby tabs to update device storage.'));
})}
async function readRaw(store:string,id?:string):Promise<any>{const db=await openDB();return new Promise((resolve,reject)=>{
 const tx=db.transaction(store),r=id===undefined?tx.objectStore(store).getAll():tx.objectStore(store).get(id);let value:any;
 r.onsuccess=()=>{value=r.result};tx.oncomplete=()=>{db.close();resolve(value)};tx.onabort=tx.onerror=()=>{db.close();reject(tx.error||r.error)};
})}
async function writeRaw(store:string,value:any,remove=false){const db=await openDB();return new Promise<void>((resolve,reject)=>{
 try{const tx=db.transaction(store,'readwrite');
 tx.oncomplete=()=>{db.close();resolve()};tx.onabort=tx.onerror=()=>{db.close();reject(tx.error||new Error('Device storage write failed.'))};
 if(remove)tx.objectStore(store).delete(value);else tx.objectStore(store).put(value);
 }catch(error){db.close();reject(error)}
})}
function enqueue<T>(work:()=>Promise<T>):Promise<T>{const next=writes.then(work,work);writes=next.catch(()=>{});return next}
export const flushDeviceWrites=async()=>{await writes};
async function ownerId(username:string){return b64(new Uint8Array(await crypto.subtle.digest('SHA-256',encode.encode(location.origin+'\0'+username))))}
async function passwordKey(password:string,salt:string){const material=await crypto.subtle.importKey('raw',encode.encode(password),'PBKDF2',false,['deriveKey']);return crypto.subtle.deriveKey({name:'PBKDF2',hash:'SHA-256',salt:bytes(salt),iterations:ITERATIONS},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt'])}
async function seal(key:CryptoKey,value:Uint8Array,aad:string):Promise<Sealed>{const iv=crypto.getRandomValues(new Uint8Array(12));const data=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:encode.encode(aad)},key,new Uint8Array(value));return{iv:b64(iv),data:b64(new Uint8Array(data))}}
async function unseal(key:CryptoKey,value:Sealed,aad:string){return new Uint8Array(await crypto.subtle.decrypt({name:'AES-GCM',iv:bytes(value.iv),additionalData:encode.encode(aad)},key,bytes(value.data)))}
const importDataKey=(raw:Uint8Array)=>crypto.subtle.importKey('raw',new Uint8Array(raw),{name:'AES-GCM'},false,['encrypt','decrypt']);
function current(){if(!active)throw new DeviceLocked('Unlock this device before opening saved work.');return active}
function validLease(lease:Lease){const now=Date.now();return now>=lease.issuedAt-300000&&now<lease.expiresAt&&lease.expiresAt-lease.issuedAt<=MAX_AGE}
export const deviceInfo=()=>active?{username:active.lease.username,expiresAt:active.lease.expiresAt,scopes:active.lease.scopes}:null;
export const deviceScopeAllowed=(clinic:string,actor:string)=>!!active?.lease.scopes.some(s=>s.clinic===clinic&&s.actor===actor);
export function lockDevice(){active=null;window.dispatchEvent(new Event('broby-device-locked'))}
export async function revokeOfflineAccess(){await flushDeviceWrites();for(const vault of await readRaw('vaults'))if(vault.lease){delete vault.lease;await writeRaw('vaults',vault)}localStorage.setItem('broby-lock-signal',crypto.randomUUID());lockDevice()}
export async function unlockOnline(username:string,password:string,snapshot:Snapshot,expiresAt:string,previousPassword?:string){
 await flushDeviceWrites();const owner=await ownerId(username);let vault:Vault=await readRaw('vaults',owner);let raw:Uint8Array;
 if(vault){try{raw=await unseal(await passwordKey(previousPassword||password,vault.salt),vault.wrapped,'key:'+owner)}catch{throw new PreviousPasswordRequired('Saved device work uses an earlier password. Enter that password below to keep your unsynced work. Nothing has been deleted.')}}
 else{raw=crypto.getRandomValues(new Uint8Array(32));vault={id:owner,salt:b64(crypto.getRandomValues(new Uint8Array(16))),wrapped:{iv:'',data:''}}}
 if(!vault.wrapped.data||previousPassword){vault.salt=b64(crypto.getRandomValues(new Uint8Array(16)));vault.wrapped=await seal(await passwordKey(password,vault.salt),raw,'key:'+owner)}
 const key=await importDataKey(raw);raw.fill(0);const issuedAt=Date.now();const deadline=Math.min(Date.parse(expiresAt),issuedAt+MAX_AGE);
 if(!Number.isFinite(deadline)||deadline<=issuedAt)throw new Error('Sign in again to renew device access.');
 const scopes=snapshot.mode==='local-demo'?snapshot.clinics.flatMap(c=>snapshot.records.filter(r=>r.kind==='member'&&r.clinic_id===c.id&&r.data.active).map(r=>({clinic:c.id,actor:r.id}))):snapshot.clinics.filter(c=>c.member_id).map(c=>({clinic:c.id,actor:c.member_id!}));
 if(!scopes.some(s=>s.clinic===snapshot.clinic.id&&s.actor===snapshot.actor.id))scopes.push({clinic:snapshot.clinic.id,actor:snapshot.actor.id});
 const lease={username,issuedAt,expiresAt:deadline,scopes,mode:snapshot.mode};vault.lease=await seal(key,encode.encode(JSON.stringify(lease)),'lease:'+owner);
 await writeRaw('vaults',vault);localStorage.setItem('broby-lock-signal',crypto.randomUUID());active={owner,key,lease};localStorage.setItem('broby-device-user',username);
 await migrateLegacy(snapshot);await cacheSnapshot(snapshot);
}
export async function unlockOffline(username:string,password:string){
 await flushDeviceWrites();const owner=await ownerId(username),vault:Vault=await readRaw('vaults',owner);
 if(!vault?.lease)throw new Error('Connect and sign in once before using this device offline.');
 let raw:Uint8Array,key:CryptoKey,lease:Lease;
 try{raw=await unseal(await passwordKey(password,vault.salt),vault.wrapped,'key:'+owner);key=await importDataKey(raw);raw.fill(0);lease=JSON.parse(decode.decode(await unseal(key,vault.lease,'lease:'+owner)))}catch{throw new Error('The username or device password does not match saved work.');}
 if(lease.username!==username||!validLease(lease))throw new Error('Offline access has expired. Reconnect and sign in. Your unsynced work is retained.');
 active={owner,key,lease};return lease;
}
// Blob payloads (audio) keep their original bytes and MIME type inside encryption.
async function pack(value:any):Promise<any>{if(value instanceof Blob)return{$brobyBlob:b64(new Uint8Array(await value.arrayBuffer())),type:value.type};if(Array.isArray(value))return Promise.all(value.map(pack));if(value&&typeof value==='object'){const out:Record<string,any>={};for(const [k,v]of Object.entries(value))out[k]=await pack(v);return out}return value}
function unpack(value:any):any{if(value&&typeof value==='object'&&typeof value.$brobyBlob==='string')return new Blob([bytes(value.$brobyBlob)],{type:value.type});if(Array.isArray(value))return value.map(unpack);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,unpack(v)]));return value}
export function localPut(store:string,value:any){const session=current();return enqueue(async()=>{
 if(active!==session)throw new DeviceLocked('Device locked before the write completed. Keep this page open.');
 const id=session.owner+':'+value.id,payload=encode.encode(JSON.stringify(await pack(value)));const sealed=await seal(session.key,payload,store+':'+id);
 if(active!==session)throw new DeviceLocked('Device locked before the write completed. Keep this page open.');
 await writeRaw(store,{id,owner:session.owner,sealed});
})}
export async function localAll(store:string):Promise<any[]>{const session=current();await flushDeviceWrites();const rows=await readRaw(store);const result=[];for(const row of rows){if(row.owner!==session.owner||!row.sealed)continue;const data=unpack(JSON.parse(decode.decode(await unseal(session.key,row.sealed,store+':'+row.id))));result.push(data)}if(active!==session)throw new DeviceLocked('Device locked.');return result}
export function localDelete(store:string,id:string){const session=current();return enqueue(async()=>{if(active!==session)throw new DeviceLocked('Device locked.');await writeRaw(store,session.owner+':'+id,true)})}
export async function localGet(store:string,id:string){return(await localAll(store)).find(row=>row.id===id)}
export async function cacheSnapshot(snapshot:Snapshot){if(active?.lease.mode==='local-demo'&&!deviceScopeAllowed(snapshot.clinic.id,snapshot.actor.id))active.lease.scopes.push({clinic:snapshot.clinic.id,actor:snapshot.actor.id});if(!deviceScopeAllowed(snapshot.clinic.id,snapshot.actor.id))throw new Error('This clinic has not been verified for device access. Sign in again.');await localPut('snapshots',{id:snapshot.clinic.id+':'+snapshot.actor.id,savedAt:Date.now(),snapshot});const copies=(await localAll('snapshots')).sort((a,b)=>b.savedAt-a.savedAt);for(let i=0;i<copies.length;i++)if(i>=5||Date.now()-copies[i].savedAt>MAX_AGE)await localDelete('snapshots',copies[i].id)}
export async function cachedSnapshot(clinic:string,actor:string){const session=current();if(!validLease(session.lease)||!deviceScopeAllowed(clinic,actor))return null;const row=await localGet('snapshots',clinic+':'+actor);return row&&Date.now()-row.savedAt<=MAX_AGE?row:null}
export async function getDraft(id:string){return(await localGet('drafts',id))?.value}
export const putDraft=(id:string,value:any)=>localPut('drafts',{id,value});
export const removeDraft=(id:string)=>localDelete('drafts',id);
async function migrateLegacy(snapshot:Snapshot){
 // Only migrate records whose original clinic/actor is authorized by this online
 // login. Unknown older data is retained, never claimed or erased by another user.
 const owned=(row:any)=>deviceScopeAllowed(row.clinic,row.actor);
 const recordings=(await readRaw('recordings')).filter((r:any)=>!r.sealed&&owned(r));const ids=new Set(recordings.map((r:any)=>r.id));
 for(const store of ['pending','recordings','audio'])for(const row of await readRaw(store))if(!row.sealed&&(store==='audio'?ids.has(row.recordingId):owned(row))){await localPut(store,row);await writeRaw(store,row.id,true)}
 for(const key of Object.keys(localStorage)){
  const id=key.replace(/^broby-(note|document)-/,'');const isDraft=/^broby-(note|document)-/.test(key)&&snapshot.records.some(r=>r.id===id&&r.kind==='consultation');
  if(isDraft){const raw=localStorage.getItem(key);if(raw!==null){await putDraft(key,key.startsWith('broby-document-')?JSON.parse(raw):raw);localStorage.removeItem(key)}}
  if(key==='broby-snapshot-'+snapshot.clinic.id+'-'+snapshot.actor.id)localStorage.removeItem(key);
  if(key==='broby-dashboard-'+snapshot.clinic.id){const raw=localStorage.getItem(key);if(raw){await putDraft(key,JSON.parse(raw));localStorage.removeItem(key)}}
 }
}
export async function clearDownloadedSnapshots(){for(const row of await localAll('snapshots'))await localDelete('snapshots',row.id)}

let shellStatus='Preparing offline reopening…';
export const offlineShellStatus=()=>shellStatus;
export async function prepareOfflineShell(){
 try{
  if(!('serviceWorker' in navigator))throw new Error('This browser does not support offline reopening.');
  const registration=await navigator.serviceWorker.register('/broby-sw.js',{scope:'/'});
  if(registration.active)shellStatus='App shell ready for offline reopening.';
  else{shellStatus='Saving the app shell for offline reopening…';const worker=registration.installing||registration.waiting;if(worker)worker.addEventListener('statechange',()=>{if(worker.state==='activated'){shellStatus='App shell ready for offline reopening.';window.dispatchEvent(new Event('broby-shell-status'))}else if(worker.state==='redundant'){shellStatus='Offline shell installation failed. Keep connected and reopen to retry.';window.dispatchEvent(new Event('broby-shell-status'))}})}
 }catch(e){shellStatus='Offline reopening is unavailable: '+(e as Error).message}
 window.dispatchEvent(new Event('broby-shell-status'));
}

export async function legacyDeviceRows(){let count=0;for(const store of ['pending','recordings','audio'])count+=(await readRaw(store)).filter((row:any)=>!row.sealed).length;return count+Object.keys(localStorage).filter(key=>/^broby-(note-|document-|snapshot-|dashboard-)/.test(key)).length}
