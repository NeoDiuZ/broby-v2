import type {Snapshot} from './types';

type Scope={clinic:string;actor:string};
type Read=(path:string)=>Promise<any>;

/** An unchanged response is usable only with this exact in-memory scope. */
export async function readWorkspace(read:Read, previous:Snapshot|null, scope:Scope){
 const matching=previous?.clinic.id===scope.clinic&&previous?.actor.id===scope.actor;
 const token=matching?previous?.snapshot_revision:undefined;
 let result=await read('/bootstrap'+(token?'?since='+encodeURIComponent(token):''));
 if(result.unchanged){
  if(token&&result.snapshot_revision===token)return{snapshot:previous!,changed:false};
  // A removed copy or unexpected token must never become an empty clinic view.
  result=await read('/bootstrap');
 }
 if(result.unchanged||!Array.isArray(result.records)||result.clinic?.id!==scope.clinic||result.actor?.id!==scope.actor)throw new Error('The clinic view changed. Reload the current clinic.');
 return{snapshot:result as Snapshot,changed:true};
}

/** Await a follow-up when a mutation asks to refresh during an older poll. */
export function coalesceRefresh(run:()=>Promise<void>){
 const batch=()=>{let resolve!:()=>void,reject!:(reason:unknown)=>void;const promise=new Promise<void>((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}};
 type Batch=ReturnType<typeof batch>;
 let active=false,queued:Batch|null=null;
 const start=(current:Batch)=>{
  active=true;
  const finish=(failed:boolean,error?:unknown)=>{
   const next=queued;queued=null;active=false;
   if(next)start(next);
   if(failed)current.reject(error);else current.resolve();
  };
  void Promise.resolve().then(run).then(()=>finish(false),error=>finish(true,error));
 };
 return function refresh():Promise<void>{
  if(active){queued=queued||batch();return queued.promise}
  const current=batch();start(current);return current.promise;
 };
}
