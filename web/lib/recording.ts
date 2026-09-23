'use client';
import {api,command,headers,identity,localAll,localDelete,localPut} from './api';
export type RecordingState={status:'idle'|'requesting'|'recording'|'paused'|'saving'|'saved'|'error';id:string;consultationId:string;patientId:string;elapsed:number;chunks:number;error:string};
let state:RecordingState={status:'idle',id:'',consultationId:'',patientId:'',elapsed:0,chunks:0,error:''};
const listeners=new Set<()=>void>();let recorder:MediaRecorder|null=null;let stream:MediaStream|null=null;let timer:ReturnType<typeof setInterval>|null=null;let pendingWrites:Promise<void>[]=[];let activeMeta:any=null;let failedChunks:any[]=[];let pendingFinalization=false;
const emit=(patch:Partial<RecordingState>)=>{state={...state,...patch};listeners.forEach(f=>f())};
export const recordingStore={subscribe:(fn:()=>void)=>{listeners.add(fn);return()=>{listeners.delete(fn)}},getSnapshot:()=>state,getServerSnapshot:()=>state};
export async function startRecording(patientId:string,consultationId:string){
 if(['requesting','recording','paused','saving'].includes(state.status))throw new Error('Finish the current voice note before starting another on this device.');
 if(failedChunks.length||pendingFinalization)throw new Error('Retry the previous note before starting another; audio is still held in this page.');
 const id=crypto.randomUUID();emit({status:'requesting',id,patientId,consultationId,error:'',elapsed:0,chunks:0});
 try{stream=await navigator.mediaDevices.getUserMedia({audio:true});const i=identity();activeMeta={id,...i,patientId,consultationId,status:'recording',elapsed:0,expected:0,serverId:null,lastSeen:Date.now()};await localPut('recordings',activeMeta);
 const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(v=>MediaRecorder.isTypeSupported(v));
 recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);activeMeta.mime=recorder.mimeType;await localPut('recordings',activeMeta);pendingWrites=[];failedChunks=[];
 recorder.ondataavailable=e=>{if(!e.data.size)return;const index=state.chunks;emit({chunks:index+1});const chunk={id:id+':'+index,recordingId:id,index,blob:e.data};pendingWrites.push(localPut('audio',chunk).catch(()=>{failedChunks.push(chunk);emit({error:'Device storage could not save part of this note. Keep this page open and retry.'})}));};
 recorder.start(5000);emit({status:'recording'});timer=setInterval(()=>{if(state.status==='recording')emit({elapsed:state.elapsed+1});activeMeta={...activeMeta,elapsed:state.elapsed,lastSeen:Date.now()};void localPut('recordings',activeMeta).catch(()=>emit({error:'Device storage could not save the recording. Finish and retry.'}))},1000);
 }catch(e){stream?.getTracks().forEach(t=>t.stop());emit({status:'error',error:(e as Error).message});throw e}
}
export function pauseRecording(){if(state.status==='recording'){recorder?.pause();emit({status:'paused'})}else if(state.status==='paused'){recorder?.resume();emit({status:'recording'})}}
export async function stopRecording(){
 if(!recorder||!['recording','paused'].includes(state.status))return;
 emit({status:'saving'});if(timer)clearInterval(timer);
 await new Promise<void>(resolve=>{recorder!.onstop=()=>resolve();recorder!.stop()});
 stream?.getTracks().forEach(t=>t.stop());await Promise.all(pendingWrites);
 activeMeta={...activeMeta,status:'queued',elapsed:state.elapsed,expected:state.chunks};pendingFinalization=true;
 try{await persistFailedChunks();await localPut('recordings',activeMeta);pendingFinalization=false;emit({status:'saved',error:''});await syncAudio()}
 catch(e){emit({status:'error',error:failedChunks.length?'Audio is still held in this page. Keep it open and choose Retry upload.':'Voice note remains on this device. Choose Retry upload when connected.'});throw e}
}
async function persistFailedChunks(){
 const retry=failedChunks;failedChunks=[];
 for(const chunk of retry){try{await localPut('audio',chunk)}catch{failedChunks.push(chunk)}}
 if(failedChunks.length)throw new Error('Device storage is full or unavailable. Keep this page open and free storage, then retry.');
}
let syncing=false;
export async function syncAudio(){if(syncing)return;syncing=true;try{if(pendingFinalization){await persistFailedChunks();await localPut('recordings',activeMeta);pendingFinalization=false;emit({status:'saved',error:''})}const i=identity();for(const meta of await localAll('recordings')){if(meta.clinic!==i.clinic||meta.actor!==i.actor||['recording','importing'].includes(meta.status))continue;let serverId=meta.serverId;
 if(!serverId){const r=await command('recording.create',{patient_id:meta.patientId,consultation_id:meta.consultationId,device:'web',mime:meta.mime||'audio/webm',interrupted:!!meta.interrupted},meta.id);serverId=r.id;await localPut('recordings',{...meta,serverId})}
 const manifest=await api('/recordings/'+serverId+'/manifest');const chunks=(await localAll('audio')).filter(x=>x.recordingId===meta.id).sort((a,b)=>a.index-b.index);
 for(const chunk of chunks){if(manifest.received.includes(chunk.index))continue;const r=await fetch('/api/recordings/'+serverId+'/chunks/'+chunk.index,{method:'PUT',headers:headers(),body:chunk.blob});if(!r.ok)throw new Error('Audio upload failed')}
 await command('recording.complete',{id:serverId,expected_chunks:meta.expected,duration:meta.elapsed},meta.id+'-complete');for(const chunk of chunks)await localDelete('audio',chunk.id);await localDelete('recordings',meta.id);
 }}finally{syncing=false}}
export async function recoverInterrupted(){for(const meta of await localAll('recordings')){if(meta.status!=='recording'||Date.now()-(meta.lastSeen||0)<20000||meta.id===state.id&&['recording','paused','saving'].includes(state.status))continue;const chunks=(await localAll('audio')).filter(c=>c.recordingId===meta.id);if(chunks.length)await localPut('recordings',{...meta,status:'queued',interrupted:true,expected:Math.max(...chunks.map(c=>c.index))+1,elapsed:meta.elapsed||chunks.length*5});else await localDelete('recordings',meta.id)}}

export async function importAudio(file:File,patientId:string,consultationId:string){
 if(file.size>100*1024*1024||!file.size)throw new Error('Choose an audio file smaller than 100 MB.');
 if(!file.type.startsWith('audio/'))throw new Error('Choose an audio file.');
 const id=crypto.randomUUID(),i=identity(),size=5*1024*1024,expected=Math.ceil(file.size/size);
 const meta={id,...i,patientId,consultationId,status:'importing',elapsed:0,expected,serverId:null,mime:file.type};
 await localPut('recordings',meta);
 try{for(let index=0;index<expected;index++)await localPut('audio',{id:id+':'+index,recordingId:id,index,blob:file.slice(index*size,(index+1)*size)});await localPut('recordings',{...meta,status:'queued'})}catch(e){for(const chunk of (await localAll('audio')).filter(x=>x.recordingId===id))await localDelete('audio',chunk.id);await localDelete('recordings',id);throw new Error('Audio import could not be stored. Free device storage and reselect the original file.')}
 await syncAudio();
}
