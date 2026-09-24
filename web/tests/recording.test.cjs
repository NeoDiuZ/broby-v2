const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const source=fs.readFileSync(require('node:path').join(__dirname,'../lib/recording.ts'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function setup(){
 const data={recordings:new Map(),audio:new Map()},uploaded=new Map();
 let lastRecorder,failStorage=false,failMetadata=false,failNetwork=false,commands=[],stopped=false,tick,clock=Date.now(),beforeAction=null,failDelete=false,jobProgress=null;const localDeletes=[];
 const api={deviceInfo:()=>({username:'synthetic-recorder'}),identity:()=>({clinic:'test',actor:'test-vet'}),headers:()=>({}),localAll:async k=>[...data[k].values()],localDelete:async(k,id)=>{localDeletes.push({k,id});if(failDelete&&localDeletes.length===2)throw new Error('Cleanup failed');return data[k].delete(id)},
  localPut:async(k,v)=>{if(k==='audio'&&failStorage)throw new Error('Quota exceeded');if(k==='recordings'&&v.status==='queued'&&failMetadata)throw new Error('Metadata failure');data[k].set(v.id,{...v})},
  api:async(path,options={})=>{if(failNetwork)throw new Error('Offline');if(path.startsWith('/jobs/'))return jobProgress||{status:'waiting',result:{completed_windows:0}};if(path!=='/actions')return{received:[...uploaded.keys()]};const {action:a,payload:p,key}=JSON.parse(options.body);if(beforeAction)await beforeAction(a,p);commands.push({a,p,key,headers:options.headers});if(a==='recording.complete'){assert.equal(uploaded.size,p.expected_chunks)}return{id:'server-note'}}};
 class Recorder{static isTypeSupported(){return true}mimeType='audio/webm';constructor(){lastRecorder=this}start(){}pause(){}resume(){}stop(){this.ondataavailable({data:new Blob(['final'])});this.onstop()}emit(value){this.ondataavailable({data:new Blob([value])})}}
 const exports={};vm.runInNewContext(compiled,{exports,require:()=>api,MediaRecorder:Recorder,Blob,crypto:require('node:crypto').webcrypto,navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop:()=>{stopped=true}}]})}},setInterval:fn=>{tick=fn;return 1},clearInterval:()=>{},setTimeout,Date:class extends Date{static now(){return clock}},fetch:async(url,options)=>{if(failNetwork)return{ok:false};uploaded.set(Number(url.split('/').pop()),options.body);return{ok:true}}});
 return {r:exports,data,uploaded,commands,localDeletes,setDelete:v=>failDelete=v,setProgress:v=>jobProgress=v,advance:seconds=>{clock+=seconds*1000;tick?.()},before:fn=>beforeAction=fn,recorder:()=>lastRecorder,setStorage:v=>failStorage=v,setMetadata:v=>failMetadata=v,setNetwork:v=>failNetwork=v,isStopped:()=>stopped};
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


test('live transcription uploads a complete prefix without stopping or deleting audio',async()=>{
 const t=setup();await t.r.startRecording('patient','consult',{language:'en',diarize:false});
 t.recorder().emit('first');await t.r.syncAudio();assert.equal(t.commands.length,0);
 t.advance(1511);await t.r.syncAudio();assert.equal(t.r.recordingStore.getSnapshot().status,'recording');
 assert.equal(t.commands.filter(x=>x.a==='recording.refine').length,1);
 assert.equal(t.commands.find(x=>x.a==='recording.create').p.refinement.diarize,false);
 assert.equal(t.commands.some(x=>x.a==='recording.complete'),false);
 assert.equal(t.data.audio.size,1);assert.equal(t.localDeletes.length,0);assert.equal(t.isStopped(),false);
 t.recorder().emit('second');t.advance(60);await t.r.syncAudio();assert.equal(t.commands.filter(x=>x.a==='recording.refine').length,2);
 await t.r.stopRecording();assert.equal(t.commands.filter(x=>x.a==='recording.create').length,1);
 assert.equal(t.uploaded.size,3);assert.equal(t.data.audio.size,0);
});

test('Finish waits for a live upload in progress and keeps its final chunk',async()=>{
 const t=setup();await t.r.startRecording('patient','consult',{language:'en',diarize:true});
 t.recorder().emit('first');t.advance(1511);
 let release,entered;const waiting=new Promise(r=>entered=r);
 t.before(async a=>{if(a==='recording.create'){entered();await new Promise(r=>release=r)}});
 const uploading=t.r.syncAudio();await waiting;const finishing=t.r.stopRecording();
 await new Promise(r=>setImmediate(r));release();await Promise.all([uploading,finishing]);
 assert.equal(t.commands.filter(x=>x.a==='recording.create').length,1);
 assert.equal(t.commands.filter(x=>x.a==='recording.complete').length,1);
 assert.equal(t.commands.find(x=>x.a==='recording.complete').p.expected_chunks,2);
 assert.equal(t.uploaded.size,2);assert.equal(t.data.audio.size,0);assert.equal(t.data.recordings.size,0);
});

test('temporary live upload failure retains capture and succeeds on final retry',async()=>{
 const t=setup();await t.r.startRecording('patient','consult',{language:'en',diarize:true});
 t.recorder().emit('first');t.advance(1511);t.setNetwork(true);await assert.rejects(t.r.syncAudio());
 assert.equal(t.r.recordingStore.getSnapshot().status,'recording');assert.equal(t.data.audio.size,1);
 t.setNetwork(false);await t.r.stopRecording();assert.equal(t.data.audio.size,0);assert.equal(t.uploaded.size,2);
});

test('a missing local chunk blocks both prefix and final claims',async()=>{
 const t=setup();await t.r.startRecording('patient','consult',{language:'en',diarize:true});
 t.recorder().emit('first');t.recorder().emit('second');t.advance(1511);
 const first=[...t.data.audio.keys()][0];t.data.audio.delete(first);
 await assert.rejects(t.r.syncAudio(),/gap/);assert.equal(t.commands.length,0);
 await assert.rejects(t.r.stopRecording(),/gap/);assert.equal(t.data.audio.size,2);
});

test('paused time is excluded and delayed timer callbacks use elapsed time',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.advance(120);
 assert.equal(t.r.recordingStore.getSnapshot().elapsed,120);t.r.pauseRecording();t.advance(90);
 assert.equal(t.r.recordingStore.getSnapshot().elapsed,120);t.r.pauseRecording();t.advance(5);
 await t.r.stopRecording();assert.equal(t.commands.find(x=>x.a==='recording.complete').p.duration,125);
});


test('partial local cleanup after server acknowledgement can finish on retry',async()=>{
 const t=setup();await t.r.startRecording('patient','consult');t.recorder().emit('first');t.setDelete(true);
 await assert.rejects(t.r.stopRecording(),/Cleanup/);assert.equal(t.data.audio.size,1);assert.equal(t.data.recordings.size,1);
 t.setDelete(false);await t.r.syncAudio();assert.equal(t.data.audio.size,0);assert.equal(t.data.recordings.size,0);
 assert.equal(t.uploaded.size,2);assert.equal(t.commands.filter(x=>x.a==='recording.create').length,1);
});

test('completed sections avoid repeated decoding until the next 25-minute boundary',async()=>{
 const t=setup();await t.r.startRecording('patient','consult',{language:'en',diarize:true});
 t.recorder().emit('first');t.advance(1511);await t.r.syncAudio();
 t.setProgress({status:'waiting',result:{completed_windows:1}});t.recorder().emit('second');t.advance(60);await t.r.syncAudio();
 assert.equal(t.commands.filter(x=>x.a==='recording.refine').length,1);assert.equal(t.uploaded.size,1);
 t.advance(1440);await t.r.syncAudio();assert.equal(t.commands.filter(x=>x.a==='recording.refine').length,2);
 await t.r.stopRecording();
});

test('locking and sign-out cannot discard active or volatile audio',async()=>{
 const t=setup();t.r.assertDeviceCanLock();await t.r.startRecording('patient','consult');assert.throws(()=>t.r.assertDeviceCanLock(),/Finish/);
 t.setStorage(true);await assert.rejects(t.r.stopRecording());assert.throws(()=>t.r.assertDeviceCanLock(),/still held/);
 t.setStorage(false);t.setNetwork(true);await assert.rejects(t.r.syncAudio());t.r.assertDeviceCanLock();assert.equal(t.data.audio.size,1);
});
