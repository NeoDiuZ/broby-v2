const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
function compile(file){return ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText}
const refresh={};vm.runInNewContext(compile('workspace-refresh.ts'),{exports:refresh,require,Promise,encodeURIComponent});
const base=(version='one',clinic='east',actor='vet')=>({snapshot_revision:version,records:[{id:'patient',version}],actor:{id:actor},clinic:{id:clinic},clinics:[],permissions:[],jobs:[],integrations:{},mode:'password'});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{resolve,reject,promise}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('unchanged needs the exact in-memory clinic, actor and revision',async()=>{
 const old=base(),paths=[];
 const result=await refresh.readWorkspace(async p=>{paths.push(p);return{unchanged:true,snapshot_revision:'one'}},old,{clinic:'east',actor:'vet'});
 assert.equal(result.snapshot,old);assert.equal(result.changed,false);assert.deepEqual(paths,['/bootstrap?since=one']);
 for(const scope of [{clinic:'river',actor:'vet'},{clinic:'east',actor:'nurse'}]){
  let seen;await refresh.readWorkspace(async p=>{seen=p;return base('new',scope.clinic,scope.actor)},old,scope);assert.equal(seen,'/bootstrap');
 }
});

test('unexpected unchanged reply falls back to a full read and cannot clear records',async()=>{
 let calls=0;
 const result=await refresh.readWorkspace(async()=>++calls===1?{unchanged:true,snapshot_revision:'wrong'}:base(),null,{clinic:'east',actor:'vet'});
 assert.equal(calls,2);assert.equal(result.snapshot.records.length,1);
 await assert.rejects(refresh.readWorkspace(async()=>({unchanged:true,snapshot_revision:'wrong'}),null,{clinic:'east',actor:'vet'}),/clinic view changed/);
});

function workspace(){
 const slots=[],events=[],saved=new Map([['broby-clinic','east'],['broby-actor','vet']]);let index=0;
 const state={paths:[],syncs:0,caches:[],revoked:0,cache:null,pending:[{id:'synthetic-note',clinic:'east',actor:'vet',status:'pending'}],read:async()=>base()};
 const hook=value=>{const i=index++;if(!(i in slots))slots[i]=value;return[i,slots[i]]};
 const react={createContext:()=>({Provider:'provider'}),useRef:v=>hook({current:v})[1],useMemo:f=>hook(f())[1],useCallback:f=>{index++;return f},useEffect:()=>{index++},useContext:()=>null,useState:v=>{const[i,value]=hook(v);return[value,v=>{slots[i]=typeof v==='function'?v(slots[i]):v}]}};
 react.default=react;
 class ApiError extends Error{constructor(status,message){super(message);this.status=status}}
 const exports={};
 const modules={'react':react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'fragment'},'./workspace-refresh':refresh,'./types':{},'./recording':{recordingStore:{getSnapshot:()=>({status:'idle'})}},
 './api':{ApiError,identity:()=>({clinic:saved.get('broby-clinic'),actor:saved.get('broby-actor')}),api:async p=>{state.paths.push(p);return state.read(p)},command:async()=>({id:'synthetic-action'}),syncPending:async()=>{state.syncs++},localAll:async()=>state.pending},
 './device':{cacheSnapshot:async data=>{state.caches.push(data);if(state.cacheError)throw state.cacheError;state.cache={snapshot:data,savedAt:123}},cachedSnapshot:async()=>state.cache,deviceScopeAllowed:()=>true,revokeOfflineAccess:async()=>{state.revoked++}}};
 vm.runInNewContext(compile('workspace.tsx'),{exports,require:id=>modules[id],window:{dispatchEvent:e=>events.push(e.type)},Event,location:{hash:''},localStorage:{setItem:(k,v)=>saved.set(k,v)},setTimeout:()=>1,clearTimeout:()=>{}});
 const render=()=>{index=0;return exports.Workspace({children:null}).props.value};
 return{state,render,ApiError,events};
}

test('unchanged polling still syncs pending notes and avoids re-encrypting the clinic',async()=>{
 const t=workspace();await t.render().refresh();t.state.read=async()=>({unchanged:true,snapshot_revision:'one'});await t.render().refresh();
 assert.equal(t.state.syncs,2);assert.equal(t.state.caches.length,1);assert.equal(t.render().records.length,1);assert.equal(t.render().pending[0].id,'synthetic-note');
});

test('failed device save is retried even when the next server response is unchanged',async()=>{
 const t=workspace();t.state.cacheError=new Error('Synthetic quota');await t.render().refresh();assert.match(t.render().error,/Synthetic quota/);
 t.state.cacheError=null;t.state.read=async()=>({unchanged:true,snapshot_revision:'one'});await t.render().refresh();
 assert.equal(t.state.caches.length,2);assert.equal(t.state.cache.snapshot.snapshot_revision,'one');assert.equal(t.render().error,'');
});

test('offline failure retains cached snapshot and queues; reconnect forces full verification',async()=>{
 const t=workspace();await t.render().refresh();t.state.read=async()=>{throw new Error('Synthetic network interruption')};await t.render().refresh();
 assert.equal(t.render().offline,true);assert.equal(t.render().records[0].id,'patient');assert.equal(t.render().pending[0].id,'synthetic-note');
 t.state.read=async()=>base('two');await t.render().refresh();assert.equal(t.state.paths.at(-1),'/bootstrap');assert.equal(t.render().offline,false);
});

test('live authorization failure clears the view and revokes offline access',async()=>{
 for(const status of [401,403]){const t=workspace();await t.render().refresh();t.state.read=async()=>{throw new t.ApiError(status,'SYNTHETIC access revoked')};await t.render().refresh();assert.equal(t.render().snapshot,null);assert.equal(t.state.revoked,1);assert(t.events.includes('broby-auth-required'));assert.equal(t.state.pending.length,1)}
});

test('mutation during an older poll waits for a fresh follow-up instead of dropping refresh',async()=>{
 const t=workspace(),old=deferred(),fresh=deferred();let call=0;
 t.state.read=()=>++call===1?old.promise:fresh.promise;
 const initial=t.render().refresh();await tick();let done=false;const acting=t.render().act('patient.update',{}).then(()=>done=true);await tick();
 old.resolve(base('one'));await tick();assert.equal(call,2);assert.equal(done,false);
 fresh.resolve(base('two'));await Promise.all([initial,acting]);assert.equal(done,true);assert.equal(t.render().snapshot.snapshot_revision,'two');
});

test('scope switch ignores an in-flight old-clinic reply and refreshes new scope',async()=>{
 const t=workspace(),old=deferred();let call=0;t.state.read=()=>++call===1?old.promise:Promise.resolve(base('river-new','river','nurse'));
 const initial=t.render().refresh();await tick();t.render().switchIdentity('river','nurse');const switched=t.render().refresh();old.resolve(base());await Promise.all([initial,switched]);
 assert.equal(t.render().snapshot.clinic.id,'river');assert.equal(t.state.caches.length,1);assert.equal(t.state.caches[0].clinic.id,'river');assert.equal(t.state.paths.at(-1),'/bootstrap');
});

test('refresh coordinator recovers after synchronous and asynchronous failure',async()=>{
 let calls=0;const run=refresh.coalesceRefresh(()=>{if(++calls===1)throw Error('first');return Promise.resolve()});await assert.rejects(run(),/first/);await run();assert.equal(calls,2);
});

test('sustained overlapping polls cannot starve callers waiting for earlier reads',async()=>{
 const gates=[];const run=refresh.coalesceRefresh(()=>{const gate=deferred();gates.push(gate);return gate.promise});
 let current=run();await tick();
 for(let i=0;i<8;i++){
  let nextDone=false;const next=run().then(()=>nextDone=true);
  // Several later callers coalesce the same next read, without extending this one.
  const alsoNext=run();gates[i].resolve();await current;await tick();
  assert.equal(gates.length,i+2);assert.equal(nextDone,false);
  current=Promise.all([next,alsoNext]);
 }
 gates.at(-1).resolve();await current;
});
