'use client';
import {deviceInfo} from './device';
import {api,identity,localAll,localDelete,localPut} from './api';
export type RecordingState={status:'idle'|'requesting'|'recording'|'paused'|'saving'|'saved'|'error';id:string;consultationId:string;patientId:string;elapsed:number;chunks:number;error:string};
export type RefinementOptions={language:string;diarize:boolean};
let state:RecordingState={status:'idle',id:'',consultationId:'',patientId:'',elapsed:0,chunks:0,error:''};
const listeners=new Set<()=>void>();
let recorder:MediaRecorder|null=null,stream:MediaStream|null=null,timer:ReturnType<typeof setInterval>|null=null;
let pendingWrites:Promise<void>[]=[],activeMeta:any=null,failedChunks:any[]=[],pendingFinalization=false;
let startedAt=0,previousElapsed=0,recoveryUser='';
const liveAttempts=new Map<string,number>();
const emit=(patch:Partial<RecordingState>)=>{state={...state,...patch};listeners.forEach(f=>f())};
const elapsed=()=>previousElapsed+(state.status==='recording'?Math.max(0,Date.now()-startedAt)/1000:0);
const scope=(meta:any)=>({'x-clinic-id':meta.clinic,'x-actor-id':meta.actor});
const action=(meta:any,action:string,payload:any,key:string)=>api('/actions',{method:'POST',headers:scope(meta),body:JSON.stringify({action,payload,key})});
export const recordingStore={subscribe:(fn:()=>void)=>{listeners.add(fn);return()=>{listeners.delete(fn)}},getSnapshot:()=>state,getServerSnapshot:()=>state};
export function assertDeviceCanLock(){if(['requesting','recording','paused','saving'].includes(state.status))throw new Error('Finish the voice note before locking or signing out.');if(failedChunks.length||pendingFinalization)throw new Error('Audio is still held in this page. Retry saving it before locking or signing out.')}
export async function startRecording(patientId:string,consultationId:string,refinement?:RefinementOptions){
 if(['requesting','recording','paused','saving'].includes(state.status))throw new Error('Finish the current voice note before starting another on this device.');
 if(failedChunks.length||pendingFinalization)throw new Error('Retry the previous note before starting another; audio is still held in this page.');
 recoveryUser=deviceInfo()?.username||'';
 const id=crypto.randomUUID();emit({status:'requesting',id,patientId,consultationId,error:'',elapsed:0,chunks:0});
 try{
  stream=await navigator.mediaDevices.getUserMedia({audio:true});const i=identity();
  activeMeta={id,...i,patientId,consultationId,refinement,status:'recording',elapsed:0,expected:0,serverId:null,lastSeen:Date.now()};
  await localPut('recordings',activeMeta);
  const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(v=>MediaRecorder.isTypeSupported(v));
  recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);activeMeta.mime=recorder.mimeType;
  await localPut('recordings',activeMeta);pendingWrites=[];failedChunks=[];
  recorder.ondataavailable=e=>{
   if(!e.data.size)return;const index=state.chunks;emit({chunks:index+1});
   const chunk={id:id+':'+index,recordingId:id,index,blob:e.data};
   pendingWrites.push(localPut('audio',chunk).catch(()=>{failedChunks.push(chunk);emit({error:'Device storage could not save part of this note. Keep this page open and retry.'})}));
  };
  recorder.start(5000);previousElapsed=0;startedAt=Date.now();emit({status:'recording'});
  timer=setInterval(()=>{
   emit({elapsed:Math.floor(elapsed())});activeMeta={...activeMeta,elapsed:state.elapsed,lastSeen:Date.now()};
   void localPut('recordings',activeMeta).catch(()=>emit({error:'Device storage could not save the recording. Finish and retry.'}));
  },1000);
 }catch(e){stream?.getTracks().forEach(t=>t.stop());emit({status:'error',error:(e as Error).message});throw e}
}
export function pauseRecording(){
 if(state.status==='recording'){previousElapsed=elapsed();recorder?.pause();emit({status:'paused',elapsed:Math.floor(previousElapsed)})}
 else if(state.status==='paused'){startedAt=Date.now();recorder?.resume();emit({status:'recording'})}
}
export async function stopRecording(){
 if(!recorder||!['recording','paused'].includes(state.status))return;
 const duration=Math.floor(elapsed());emit({status:'saving',elapsed:duration});if(timer)clearInterval(timer);
 await new Promise<void>(resolve=>{recorder!.onstop=()=>resolve();recorder!.stop()});
 stream?.getTracks().forEach(t=>t.stop());await Promise.all(pendingWrites);
 activeMeta={...activeMeta,status:'queued',elapsed:duration,expected:state.chunks};pendingFinalization=true;
 try{await persistFailedChunks();await localPut('recordings',activeMeta);pendingFinalization=false;emit({status:'saved',error:''});await syncAudio()}
 catch(e){emit({status:'error',error:failedChunks.length?'Audio is still held in this page. Keep it open and choose Retry upload.':'Voice note remains on this device. Choose Retry upload when connected.'});throw e}
}
async function persistFailedChunks(){
 if((failedChunks.length||pendingFinalization)&&recoveryUser!==(deviceInfo()?.username||''))throw new Error('Sign back into the account that recorded this note to recover its audio.');
 const retry=failedChunks;failedChunks=[];
 for(const chunk of retry){try{await localPut('audio',chunk)}catch{failedChunks.push(chunk)}}
 if(failedChunks.length)throw new Error('Device storage is full or unavailable. Keep this page open and free storage, then retry.');
}
// Patches read the current metadata: a live upload must never overwrite Finish
// with an older "recording" snapshot, or erase a newly received server ID.
async function patchMeta(meta:any,patch:any){
 const current=activeMeta?.id===meta.id?activeMeta:(await localAll('recordings')).find(x=>x.id===meta.id);
 if(!current)throw new Error('Local recording metadata is unavailable.');
 const next={...current,...patch};if(activeMeta?.id===meta.id)activeMeta=next;
 await localPut('recordings',next);return next;
}
let syncing:Promise<void>|null=null;
export async function syncAudio():Promise<void>{
 // Finish must run a second pass after an upload that began while recording.
 if(syncing){await syncing;return syncAudio()}
 const work=flushAudio();syncing=work;try{await work}finally{if(syncing===work)syncing=null}
}
async function flushAudio(){
 if(pendingFinalization){await persistFailedChunks();await localPut('recordings',activeMeta);pendingFinalization=false;emit({status:'saved',error:''})}
 const i=identity();
 for(let meta of await localAll('recordings')){
  if(meta.clinic!==i.clinic||meta.actor!==i.actor||meta.status==='importing')continue;
  const live=meta.status==='recording';
  if(live){
   if(!meta.refinement||meta.elapsed<1510||Date.now()-(liveAttempts.get(meta.id)||0)<60000)continue;
   // Never claim another tab's active microphone or process a storage gap.
   if(meta.id!==state.id||!['recording','paused'].includes(state.status)||failedChunks.length)continue;
   liveAttempts.set(meta.id,Date.now());await Promise.all(pendingWrites);
   if(meta.refinementJob){
    const progress=await api('/jobs/'+meta.refinementJob,{headers:scope(meta)});
    const due=Math.floor((meta.elapsed-10)/1500);
    if(progress.status==='failed'||(progress.result?.completed_windows||0)>=due)continue;
   }
  }
  const chunks=(await localAll('audio')).filter(x=>x.recordingId===meta.id).sort((a,b)=>a.index-b.index);
  const count=live?chunks.length:meta.expected;
  if(!count||chunks.some(x=>x.index<0||x.index>=count)||((live||!meta.serverId)&&(chunks.length!==count||chunks.some((x,n)=>x.index!==n))))throw new Error('Audio has a local storage gap. Keep this page open and retry.');
  let serverId=meta.serverId;
  if(!serverId){
   // Identical even after interrupted recovery or a lost create response.
   const r=await action(meta,'recording.create',{patient_id:meta.patientId,consultation_id:meta.consultationId,device:'web',mime:meta.mime||'audio/webm',refinement:meta.refinement||null},meta.id);
   serverId=r.id;meta=await patchMeta(meta,{serverId});
  }
  const manifest=await api('/recordings/'+serverId+'/manifest',{headers:scope(meta)});
  for(const chunk of chunks){
   if(manifest.received.includes(chunk.index))continue;
   const r=await fetch('/api/recordings/'+serverId+'/chunks/'+chunk.index,{method:'PUT',headers:scope(meta),body:chunk.blob});
   if(!r.ok)throw new Error('Audio upload failed; original chunks remain on this device.');
  }
  if(live){
   const job=await action(meta,'recording.refine',{id:serverId,expected_chunks:count},meta.id+'-prefix-'+count);
   await patchMeta(meta,{refinementJob:job.id});
   continue; // Retain every original byte until the complete manifest is acknowledged.
  }
  await action(meta,'recording.complete',{id:serverId,expected_chunks:meta.expected,duration:meta.elapsed,interrupted:!!meta.interrupted},meta.id+'-complete');
  for(const chunk of chunks)await localDelete('audio',chunk.id);
  await localDelete('recordings',meta.id);liveAttempts.delete(meta.id);
 }
}
export async function recoverInterrupted(){
 for(const meta of await localAll('recordings')){
  if(meta.status!=='recording'||Date.now()-(meta.lastSeen||0)<20000||meta.id===state.id&&['recording','paused','saving'].includes(state.status))continue;
  const chunks=(await localAll('audio')).filter(c=>c.recordingId===meta.id);
  if(chunks.length)await localPut('recordings',{...meta,status:'queued',interrupted:true,expected:Math.max(...chunks.map(c=>c.index))+1,elapsed:meta.elapsed||chunks.length*5});
  else await localDelete('recordings',meta.id);
 }
}
export async function importAudio(file:File,patientId:string,consultationId:string){
 if(file.size>100*1024*1024||!file.size)throw new Error('Choose an audio file smaller than 100 MB.');
 if(!file.type.startsWith('audio/'))throw new Error('Choose an audio file.');
 const id=crypto.randomUUID(),i=identity(),size=5*1024*1024,expected=Math.ceil(file.size/size);
 const meta={id,...i,patientId,consultationId,status:'importing',elapsed:0,expected,serverId:null,mime:file.type};
 await localPut('recordings',meta);
 try{for(let index=0;index<expected;index++)await localPut('audio',{id:id+':'+index,recordingId:id,index,blob:file.slice(index*size,(index+1)*size)});await localPut('recordings',{...meta,status:'queued'})}
 catch(e){for(const chunk of (await localAll('audio')).filter(x=>x.recordingId===id))await localDelete('audio',chunk.id);await localDelete('recordings',id);throw new Error('Audio import could not be stored. Free device storage and reselect the original file.')}
 await syncAudio();
}
