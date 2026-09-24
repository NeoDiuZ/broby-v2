const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../scripts/service-worker.js'),'utf8');
function worker({offline=false,status=200}={}){
 const handlers={},requests=[],deleted=[],cached=new Map([['/offline-workspace.html',new Response('public login shell')]]);let installed=[],claimed=false;
 const cache={addAll:async list=>{installed=list},match:async key=>cached.get(key)};
 vm.runInNewContext(source,{RELEASE:'synthetic-build',ASSETS:['/offline-workspace.html','/_next/static/chunks/synthetic.js'],URL,Response,AbortController,setTimeout,clearTimeout,fetch:async req=>{requests.push(req);if(offline)throw new TypeError('Disconnected');return new Response('network body',{status})},caches:{open:async()=>cache,keys:async()=>['unrelated-cache','broby-shell-old','broby-shell-synthetic-build'],delete:async key=>deleted.push(key),match:async key=>cached.get(key)},self:{location:{origin:'https://broby.example'},clients:{claim:async()=>{claimed=true}},addEventListener:(name,fn)=>handlers[name]=fn}});
 const event=(name,request)=>{let promise=null;handlers[name]({request,respondWith:p=>{promise=p},waitUntil:p=>{promise=p}});return promise};
 return{event,requests,deleted,installed:()=>installed,claimed:()=>claimed,cached};
}
test('service worker never intercepts API, authentication, owner links or media',()=>{
 const w=worker();for(const path of ['/api/bootstrap','/api/session','/api/recordings/private/audio','/owner?token=secret','/privacy'])assert.equal(w.event('fetch',{url:'https://broby.example'+path,method:'GET',mode:'navigate'}),null);
 assert.equal(w.event('fetch',{url:'https://other.example/app',method:'GET',mode:'navigate'}),null);assert.equal(w.event('fetch',{url:'https://broby.example/app',method:'POST',mode:'navigate'}),null);
});
test('offline and unavailable server return the cached public shell, not an API snapshot',async()=>{
 for(const config of [{offline:true},{status:503}]){const w=worker(config);const r=await w.event('fetch',{url:'https://broby.example/app',method:'GET',mode:'navigate'});assert.equal(await r.text(),'public login shell')}
});
test('online navigation uses network; only release-listed static assets use cache',async()=>{
 const w=worker();const r=await w.event('fetch',{url:'https://broby.example/app',method:'GET',mode:'navigate'});assert.equal(await r.text(),'network body');w.cached.set('/_next/static/chunks/synthetic.js',new Response('cached code'));
 const asset=await w.event('fetch',{url:'https://broby.example/_next/static/chunks/synthetic.js',method:'GET',mode:'cors'});assert.equal(await asset.text(),'cached code');assert.equal(w.requests.length,1);assert.equal(w.event('fetch',{url:'https://broby.example/unknown.js',method:'GET',mode:'cors'}),null);
});
test('installation precaches all shell assets, activation cleans only this application cache',async()=>{
 const w=worker();await w.event('install');assert.equal(w.installed().length,2);await w.event('activate');assert.deepEqual(w.deleted,['broby-shell-old']);assert(w.claimed());assert(!source.includes('self.skipWaiting('));
});
