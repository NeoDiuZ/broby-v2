const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const jsx=require('react/jsx-runtime');

// Exercise actual component event handlers without installing a second UI stack.
function component(file,mocks){
 const slots=[],effects=[];let cursor=0;
 const hooks={useState(initial){const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value}]},useRef(value){const i=cursor++;return slots[i]??=( {current:value})},useEffect(fn,deps){const i=cursor++;if(!slots[i]||deps?.some((d,n)=>d!==slots[i][n])){slots[i]=deps;effects.push(fn)}}};
 const exp={};const compiled=ts.transpileModule(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
 vm.runInNewContext(compiled,{exports:exp,require:id=>id==='react'?hooks:id==='react/jsx-runtime'?jsx:mocks[id]||new Proxy({},{get:(_,name)=>String(name)}),crypto:require('node:crypto').webcrypto,Date});
 return {render(name,props){cursor=0;const tree=exp[name](props);effects.splice(0).forEach(fn=>fn());return tree}};
}
function nodes(tree){if(!tree||typeof tree!=='object')return [];if(Array.isArray(tree))return tree.flatMap(nodes);return [tree,...nodes(tree.props?.children)]}
function text(tree){if(tree==null||typeof tree==='boolean')return '';if(typeof tree!=='object')return String(tree);if(Array.isArray(tree))return tree.map(text).join('');return text(tree.props?.children)}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function savedAssistant(turn){
 const calls=[],navigation=[];let closed=0;
 const w={records:turn.choices||[],refresh:async()=>{},notify:()=>{}};
 const api=async(url,options)=>{calls.push({url,options});if(url==='/assistant/conversations')return [{id:'saved-conversation',title:'Saved original request'}];if(url==='/assistant/conversations/saved-conversation')return {turns:[turn]};if(url==='/assistant')return {conversation_id:'saved-conversation',turn_id:'next-turn',status:'completed',text:'Recorded facts',sources:[]};throw Error('Unexpected request '+url)};
 const c=component('components/Assistant.tsx',{'@/lib/api':{api},'@/lib/workspace':{useWorkspace:()=>w},'./App':{navigate:(...args)=>navigation.push(args)}});
 const props={onClose:()=>closed++};let tree=c.render('default',props);await settle();tree=c.render('default',props);
 nodes(tree).find(n=>n.type==='select'&&n.props['aria-label']==='Saved conversations').props.onChange({target:{value:'saved-conversation'}});
 await settle();return {tree:c.render('default',props),calls,navigation,closed:()=>closed};
}

test('choosing a duplicate patient resubmits the exact saved question in the same conversation',async()=>{
 const original='Show Bella invoices whose status equals issued on 2098-07-10';
 const h=await savedAssistant({turn_id:'first',request_key:'old-key',message:original,status:'completed',text:'Choose exact patient',choices:[{id:'bella-cat',data:{name:'Bella',species:'Cat'}},{id:'bella-dog',data:{name:'Bella',species:'Dog'}}]});
 nodes(h.tree).find(n=>n.type==='button'&&text(n)==='Bella · Cat').props.onClick();await settle();
 const requests=h.calls.filter(c=>c.options?.method==='POST');assert.equal(requests.length,1);assert.equal(requests[0].url,'/assistant');
 const body=JSON.parse(requests[0].options.body);assert.equal(body.message,original);assert.equal(body.patient_id,'bella-cat');assert.equal(body.conversation_id,'saved-conversation');assert.notEqual(body.key,'old-key');
 assert(!h.calls.some(c=>c.url.includes('/confirm')));
});

test('saved dictionary guide opens the real catalog section without posting an action',async()=>{
 const h=await savedAssistant({turn_id:'guide',request_key:'guide-key',message:'Review dictionary',status:'completed',text:'Use the catalog',navigate:'Settings',navigate_section:'Observation catalog'});
 nodes(h.tree).find(n=>n.type==='button'&&text(n)==='Open Observation catalog').props.onClick();
 assert.equal(JSON.stringify(h.navigation),JSON.stringify([['Settings','Observation catalog']]));assert.equal(h.closed(),1);
 assert(!h.calls.some(c=>c.options?.method==='POST'));
 const c=component('components/operations/Administration.tsx',{'@/lib/workspace':{useWorkspace:()=>({records:[{id:'settings',kind:'settings',data:{}}],snapshot:{clinic:{id:'fixture'},actor:{data:{role:'admin'}}}})},'@/lib/api':{api:async()=>[]}});
 const tree=c.render('Settings',{section:h.navigation[0][1]});
 assert(nodes(tree).some(n=>n.type==='h2'&&text(n)==='Typed observation catalog'));
 assert(nodes(tree).some(n=>n.type==='OntologyProposals'));
 assert(!nodes(tree).some(n=>n.type==='h2'&&text(n)==='Clinic preferences'));
});

test('unknown settings section cannot select an arbitrary panel',()=>{
 const c=component('components/operations/Administration.tsx',{'@/lib/workspace':{useWorkspace:()=>({records:[{id:'settings',kind:'settings',data:{}}],snapshot:{clinic:{id:'fixture'},actor:{data:{role:'admin'}}}})},'@/lib/api':{api:async()=>[]}});
 assert(nodes(c.render('Settings',{section:'Untrusted section'})).some(n=>n.type==='h2'&&text(n)==='Clinic preferences'));
});
