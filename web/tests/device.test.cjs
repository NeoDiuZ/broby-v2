const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const {IDBFactory}=require('fake-indexeddb');
const source=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/device.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function setup(db=new IDBFactory(),saved=new Map()){
 const exports={},localStorage={getItem:k=>saved.get(k)??null,setItem:(k,v)=>{saved.set(k,String(v));localStorage[k]=String(v)},removeItem:k=>{saved.delete(k);delete localStorage[k]}};for(const[k,v]of saved)localStorage[k]=v;
 let clock=Date.now();const events=[];
 vm.runInNewContext(source,{exports,require,crypto:require('node:crypto').webcrypto,indexedDB:db,location:{origin:'https://synthetic.example'},localStorage,window:{dispatchEvent:e=>events.push(e.type)},Event,Blob,TextEncoder,TextDecoder,Uint8Array,atob,btoa,Date:class extends Date{static now(){return clock}}});
 const snapshot={mode:'password',clinic:{id:'clinic-a'},actor:{id:'actor-a'},clinics:[{id:'clinic-a',member_id:'actor-a'}],records:[{id:'consult-a',kind:'consultation'}],jobs:[],permissions:['source.add']};
 const expiry=()=>new Date(clock+3600000).toISOString();
 const login=(user='alice',pw='synthetic existing password',s=snapshot,old)=>exports.unlockOnline(user,pw,s,expiry(),old);
 async function raw(store,id,value){const d=await exports.openDB();return new Promise((resolve,reject)=>{const tx=d.transaction(store,value===undefined?'readonly':'readwrite');const r=value===undefined?(id?tx.objectStore(store).get(id):tx.objectStore(store).getAll()):tx.objectStore(store).put(value);let out;r.onsuccess=()=>out=r.result;tx.oncomplete=()=>{d.close();resolve(out)};tx.onabort=tx.onerror=()=>{d.close();reject(tx.error)}})}
 return{r:exports,login,raw,db,saved,events,snapshot,localStorage,advance:ms=>clock+=ms};
}
test('all clinical stores persist authenticated ciphertext, including exact Blob bytes',async()=>{
 const t=setup();await t.login();const data={id:'local-note',text:'SYNTHETIC private note',blob:new Blob([new Uint8Array([0,255,17,92])],{type:'audio/webm'})};
 for(const store of ['pending','recordings','audio','drafts']){await t.r.localPut(store,data);const raw=await t.raw(store);assert(!JSON.stringify(raw).includes(data.text));assert(!JSON.stringify(raw).includes('audio/webm'));const row=(await t.r.localAll(store))[0];assert.equal(row.text,data.text);assert.deepEqual([...new Uint8Array(await row.blob.arrayBuffer())],[0,255,17,92]);assert.equal(row.blob.type,'audio/webm')}
 const meta=await t.raw('vaults');assert(!JSON.stringify(meta).includes('synthetic existing password'));assert(!JSON.stringify(meta).includes('alice'));
});
test('fresh process requires unlock, rejects wrong password and restores saved copy',async()=>{
 const t=setup();await t.login();await t.r.putDraft('note','SYNTHETIC draft');const next=setup(t.db,t.saved);
 await assert.rejects(next.r.localAll('drafts'),/Unlock/);await assert.rejects(next.r.unlockOffline('alice','wrong'),/does not match/);
 await next.r.unlockOffline('alice','synthetic existing password');assert.equal(await next.r.getDraft('note'),'SYNTHETIC draft');assert.equal((await next.r.cachedSnapshot('clinic-a','actor-a')).snapshot.clinic.id,'clinic-a');
});
test('accounts cannot read, overwrite or delete another account pending data',async()=>{
 const t=setup();await t.login();await t.r.localPut('pending',{id:'shared-id',text:'Alice draft'});await t.login('bob','a different existing password');assert.equal((await t.r.localAll('pending')).length,0);
 await t.r.localPut('pending',{id:'shared-id',text:'Bob draft'});await t.r.localDelete('pending','shared-id');await t.r.unlockOffline('alice','synthetic existing password');assert.equal((await t.r.localAll('pending'))[0].text,'Alice draft');
});
test('ciphertext changes fail closed, and authenticated store/row binding prevents swaps',async()=>{
 const t=setup();await t.login();await t.r.putDraft('note','SYNTHETIC secret');let row=(await t.raw('drafts'))[0];await t.raw('pending',null,row);await assert.rejects(t.r.localAll('pending'));
 row.sealed.data=(row.sealed.data.startsWith('A')?'B':'A')+row.sealed.data.slice(1);await t.raw('drafts',null,row);await assert.rejects(t.r.localAll('drafts'));
});
test('password change requires old device password and preserves pending audio',async()=>{
 const t=setup();await t.login();await t.r.localPut('audio',{id:'audio',blob:new Blob(['keep original'])});
 await assert.rejects(t.login('alice','new synthetic password'),/earlier password/);await t.login('alice','new synthetic password',t.snapshot,'synthetic existing password');t.r.lockDevice();
 await assert.rejects(t.r.unlockOffline('alice','synthetic existing password'),/does not match/);await t.r.unlockOffline('alice','new synthetic password');assert.equal(await (await t.r.localAll('audio'))[0].blob.text(),'keep original');
});
test('offline expiry and clock rollback refuse reopening without deleting unsynced work',async()=>{
 const t=setup();await t.login();await t.r.putDraft('note','keep');t.advance(3600001);t.r.lockDevice();await assert.rejects(t.r.unlockOffline('alice','synthetic existing password'),/expired/);assert.equal((await t.raw('drafts')).length,1);
 t.advance(-4000000);await assert.rejects(t.r.unlockOffline('alice','synthetic existing password'),/expired/);
});
test('sign-out revokes offline access but next verified online sign-in recovers drafts',async()=>{
 const t=setup();await t.login();await t.r.putDraft('note','keep');await t.r.revokeOfflineAccess();await assert.rejects(t.r.unlockOffline('alice','synthetic existing password'),/Connect and sign in/);await t.login();assert.equal(await t.r.getDraft('note'),'keep');assert(t.saved.has('broby-lock-signal'));
});
test('server scope boundary blocks a clinic or role not in the last verified membership',async()=>{
 const t=setup();await t.login();assert.equal(await t.r.cachedSnapshot('clinic-b','actor-b'),null);await assert.rejects(t.r.cacheSnapshot({...t.snapshot,actor:{id:'actor-other'}}),/not been verified/);
});
test('legacy notes, drafts and original audio migrate only for verified actor scopes',async()=>{
 const t=setup();await t.raw('pending',null,{id:'mine',clinic:'clinic-a',actor:'actor-a',text:'private queued'});await t.raw('pending',null,{id:'other',clinic:'clinic-b',actor:'actor-b',text:'other account'});
 await t.raw('recordings',null,{id:'rec',clinic:'clinic-a',actor:'actor-a'});await t.raw('audio',null,{id:'rec:0',recordingId:'rec',blob:new Blob(['legacy audio'])});
 t.localStorage.setItem('broby-note-consult-a','legacy draft');t.localStorage.setItem('broby-note-other','other draft');t.localStorage.setItem('broby-snapshot-clinic-a-actor-a','old stale');
 await t.login();assert.equal((await t.r.localAll('pending'))[0].text,'private queued');assert.equal((await t.raw('pending')).filter(r=>!r.sealed).length,1);assert.equal(await (await t.r.localAll('audio'))[0].blob.text(),'legacy audio');assert.equal(await t.r.getDraft('broby-note-consult-a'),'legacy draft');assert.equal(t.localStorage.getItem('broby-note-consult-a'),null);assert.equal(t.localStorage.getItem('broby-note-other'),'other draft');assert.equal(t.localStorage.getItem('broby-snapshot-clinic-a-actor-a'),null);
});
test('draft writes preserve call order; clearing snapshots keeps all unsynced queues',async()=>{
 const t=setup();await t.login();await Promise.all([t.r.putDraft('n','one'),t.r.putDraft('n','two'),t.r.putDraft('n','three')]);assert.equal(await t.r.getDraft('n'),'three');await t.r.localPut('pending',{id:'p',text:'queued'});await t.r.clearDownloadedSnapshots();assert.equal((await t.r.localAll('snapshots')).length,0);assert.equal(await t.r.getDraft('n'),'three');assert.equal((await t.r.localAll('pending')).length,1);
});
test('locking prevents queued writes from crossing an account boundary',async()=>{
 const t=setup();await t.login();const pending=t.r.putDraft('n','private');t.r.lockDevice();await assert.rejects(pending,/locked/);await t.login('bob','bob test password');assert.equal((await t.r.localAll('drafts')).length,0);
});
test('unreasonably long server expiry is capped at twelve hours',async()=>{
 const t=setup();await t.r.unlockOnline('alice','synthetic existing password',t.snapshot,new Date(Date.now()+7*86400000).toISOString());t.advance(12*3600000+1000);t.r.lockDevice();await assert.rejects(t.r.unlockOffline('alice','synthetic existing password'),/expired/);
});

test('quota failure preserves previous draft and later writes recover',async()=>{
 const t=setup();await t.login();await t.r.putDraft('n','previous');const {IDBObjectStore}=require('fake-indexeddb');const put=IDBObjectStore.prototype.put;
 IDBObjectStore.prototype.put=function(value,...args){if(this.name==='drafts')throw new DOMException('Synthetic quota limit','QuotaExceededError');return put.call(this,value,...args)};
 try{await assert.rejects(t.r.putDraft('n','replacement'),/quota/)}finally{IDBObjectStore.prototype.put=put}
 assert.equal(await t.r.getDraft('n'),'previous');await t.r.putDraft('n','recovered');assert.equal(await t.r.getDraft('n'),'recovered');
});
test('snapshot retention removes old copies but never pending work',async()=>{
 const t=setup();const clinics=Array.from({length:7},(_,i)=>({id:'c'+i,member_id:'a'+i}));const snapshot={...t.snapshot,clinics,clinic:{id:'c0'},actor:{id:'a0'}};await t.login('alice','synthetic existing password',snapshot);await t.r.localPut('pending',{id:'n',text:'keep'});
 for(let i=1;i<7;i++){t.advance(100);await t.r.cacheSnapshot({...snapshot,clinic:{id:'c'+i},actor:{id:'a'+i}})}
 assert.equal((await t.r.localAll('snapshots')).length,5);assert.equal(await t.r.cachedSnapshot('c0','a0'),null);assert.equal((await t.r.localAll('pending')).length,1);
});

test('legacy warning counts only unencrypted clinical work without exposing contents',async()=>{
 const t=setup();await t.login();assert.equal(await t.r.legacyDeviceRows(),0);await t.r.putDraft('new','encrypted');t.localStorage.setItem('broby-note-other','unclaimed legacy');await t.raw('pending',null,{id:'old',clinic:'other',actor:'other',text:'legacy'});assert.equal(await t.r.legacyDeviceRows(),2);
});

test('observed permission change prevents old snapshot fallback after cache quota failure',async()=>{
 const t=setup();await t.login();
 const reduced={...t.snapshot,permissions:[],read_permissions:['read.patients']};
 const {IDBObjectStore}=require('fake-indexeddb'),put=IDBObjectStore.prototype.put;
 IDBObjectStore.prototype.put=function(value,...args){if(this.name==='snapshots')throw new DOMException('Synthetic quota','QuotaExceededError');return put.call(this,value,...args)};
 try{await assert.rejects(t.r.cacheSnapshot(reduced),/quota/)}finally{IDBObjectStore.prototype.put=put}
 assert.equal(await t.r.cachedSnapshot('clinic-a','actor-a'),null);
 t.r.lockDevice();await t.r.unlockOffline('alice','synthetic existing password');
 assert.equal(await t.r.cachedSnapshot('clinic-a','actor-a'),null);
 await t.r.cacheSnapshot(reduced);assert.deepEqual(Array.from((await t.r.cachedSnapshot('clinic-a','actor-a')).snapshot.read_permissions),['read.patients']);
});
