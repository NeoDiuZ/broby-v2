const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const source=fs.readFileSync(require('node:path').join(__dirname,'../lib/recording.ts'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function setup(){
 const data={recordings:new Map(),audio:new Map()},uploaded=new Map();
 let lastRecorder,failStorage=false,failMetadata=false,failNetwork=false,commands=[],stopped=false;
 const api={identity:()=>({clinic:'test',actor:'test-vet'}),headers:()=>({}),localAll:async k=>[...data[k].values()],localDelete:async(k,id)=>data[k].delete(id),
  localPut:async(k,v)=>{if(k==='audio'&&failStorage)throw new Error('Quota exceeded');if(k==='recordings'&&v.status==='queued'&&failMetadata)throw new Error('Metadata failure');data[k].set(v.id,{...v})},
  api:async()=>({received:[...uploaded.keys()]}),command:async(a,p,key)=>{if(failNetwork)throw new Error('Offline');commands.push({a,p,key});if(a==='recording.complete'){assert.equal(uploaded.size,p.expected_chunks)}return{id:'server-note'}}};
 class Recorder{static isTypeSupported(){return true}mimeType='audio/webm';constructor(){lastRecorder=this}start(){}pause(){}resume(){}stop(){this.ondataavailable({data:new Blob(['final'])});this.onstop()}emit(value){this.ondataavailable({data:new Blob([value])})}}
 const exports={};vm.runInNewContext(compiled,{exports,require:()=>api,MediaRecorder:Recorder,Blob,crypto:require('node:crypto').webcrypto,navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop:()=>{stopped=true}}]})}},setInterval:()=>1,clearInterval:()=>{},setTimeout,Date,fetch:async(url,options)=>{if(failNetwork)return{ok:false};uploaded.set(Number(url.split('/').pop()),options.body);return{ok:true}}});
 return {r:exports,data,uploaded,commands,recorder:()=>lastRecorder,setStorage:v=>failStorage=v,setMetadata:v=>failMetadata=v,setNetwork:v=>failNetwork=v,isStopped:()=>stopped};
}

test('finished recording uploads all chunks once and clears only confirmed local audio',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.recorder().emit('first');await t.r.stopRecording();
 assert.equal(t.uploaded.size,2);assert.equal(t.data.audio.size,0);assert.equal(t.data.recordings.size,0);assert(t.isStopped());
 assert.equal(t.commands.filter(c=>c.a==='recording.complete').length,1);
});

test('offline upload keeps durable chunks and retries without recreating the note',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.setNetwork(true);await assert.rejects(t.r.stopRecording());
 assert.equal(t.data.audio.size,1);assert.equal(t.data.recordings.size,1);
 t.setNetwork(false);await t.r.syncAudio();assert.equal(t.uploaded.size,1);assert.equal(t.data.audio.size,0);
});

test('storage quota failure retains in-memory audio and blocks replacement until recovered',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.setStorage(true);t.recorder().emit('first');await assert.rejects(t.r.stopRecording());
 assert.equal(t.r.recordingStore.getSnapshot().status,'error');assert.equal(t.commands.length,0);assert(t.isStopped());
 await assert.rejects(t.r.startRecording('patient','another'),/Retry the previous note/);
 t.setStorage(false);await t.r.syncAudio();assert.equal(t.uploaded.size,2);assert.equal(t.data.audio.size,0);
});

test('failed final metadata write is recoverable without truncating the manifest',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.setMetadata(true);await assert.rejects(t.r.stopRecording());
 assert.equal(t.data.audio.size,1);await assert.rejects(t.r.startRecording('patient','another'));
 t.setMetadata(false);await t.r.syncAudio();assert.equal(t.uploaded.size,1);assert.equal(t.commands.find(c=>c.a==='recording.complete').p.expected_chunks,1);
});

test('pause and resume preserve one note, and a second capture cannot stop it',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.r.pauseRecording();assert.equal(t.r.recordingStore.getSnapshot().status,'paused');
 await assert.rejects(t.r.startRecording('other','consult2'));t.r.pauseRecording();assert.equal(t.r.recordingStore.getSnapshot().status,'recording');await t.r.stopRecording();
});

test('background sync cannot finalize an active recording after a storage failure',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.setStorage(true);t.recorder().emit('first');await Promise.resolve();
 t.setStorage(false);await t.r.syncAudio();assert.equal(t.r.recordingStore.getSnapshot().status,'recording');assert.equal(t.commands.length,0);
 t.recorder().emit('second');await t.r.stopRecording();assert.equal(t.uploaded.size,3);assert.equal(t.data.audio.size,0);
});

test('failed imported-file finalization cleans up incomplete metadata for reselection',async()=>{
 const t=setup();t.setMetadata(true);const file=new Blob(['synthetic'],{type:'audio/wav'});
 await assert.rejects(t.r.importAudio(file,'patient','consult'),/reselect the original file/);
 assert.equal(t.data.audio.size,0);assert.equal(t.data.recordings.size,0);assert.equal(t.commands.length,0);
});
