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
 const w={records:turn.choices||[],refresh:async()=>{},notify:()=>{},act:async(action,payload)=>{calls.push({action,payload});return {id:'saved-view'}}};
 const api=async(url,options)=>{calls.push({url,options});if(url==='/assistant/conversations')return [{id:'saved-conversation',title:'Saved original request'}];if(url==='/assistant/conversations/saved-conversation')return {turns:[turn]};if(url==='/assistant')return {conversation_id:'saved-conversation',turn_id:'next-turn',status:'completed',text:'Recorded facts',sources:[]};throw Error('Unexpected request '+url)};
 const c=component('components/Assistant.tsx',{'@/lib/api':{api},'@/lib/workspace':{useWorkspace:()=>w},'./App':{navigate:(...args)=>navigation.push(args)}});
 const props={onClose:()=>closed++};let tree=c.render('default',props);await settle();tree=c.render('default',props);
 nodes(tree).find(n=>n.type==='select'&&n.props['aria-label']==='Saved conversations').props.onChange({target:{value:'saved-conversation'}});
 await settle();return {tree:c.render('default',props),render:()=>c.render('default',props),calls,navigation,closed:()=>closed};
}

test('choosing a duplicate patient resubmits the exact saved question in the same conversation',async()=>{
 const original='Show Bella invoices whose status equals issued on 2098-07-10';
 const h=await savedAssistant({turn_id:'first',request_key:'old-key',message:original,status:'completed',text:'Choose exact patient',choices:[{id:'bella-cat',data:{name:'Bella',species:'Cat'}},{id:'bella-dog',data:{name:'Bella',species:'Dog'}}]});
 nodes(h.tree).find(n=>n.type==='button'&&text(n)==='Bella · Cat').props.onClick();await settle();
 const requests=h.calls.filter(c=>c.options?.method==='POST');assert.equal(requests.length,1);assert.equal(requests[0].url,'/assistant');
 const body=JSON.parse(requests[0].options.body);assert.equal(body.message,original);assert.equal(body.patient_id,'bella-cat');assert.equal(body.conversation_id,'saved-conversation');assert.notEqual(body.key,'old-key');
 assert(!h.calls.some(c=>c.url.includes('/confirm')));
});

for(const [section,expectedPanels] of [
 ['Observation catalog',['OntologyProposals']],
 ['Integrations',['TestConnections']],
 ['Data & migration',['IncomingTransfers','MigrationRehearsal']],
 ['Sync & jobs',['OperationsHealth','DeviceControls']],
 ['Clinic',['SchedulePreferences','OrganizationControls']],
])test('saved guide opens the actual '+section+' review controls without posting an action',async()=>{
 const h=await savedAssistant({turn_id:'guide',request_key:'guide-key',message:'Open the dedicated review',status:'completed',text:'Use the review screen',navigate:'Settings',navigate_section:section});
 nodes(h.tree).find(n=>n.type==='button'&&text(n)==='Open '+section).props.onClick();
 assert.equal(JSON.stringify(h.navigation),JSON.stringify([['Settings',section]]));assert.equal(h.closed(),1);
 assert(!h.calls.some(c=>c.options?.method==='POST'));
 const calls=[];
 const mocks={'@/lib/workspace':{useWorkspace:()=>({records:[{id:'settings',kind:'settings',data:{}}],pending:[],snapshot:{mode:'password',clinic:{id:'fixture'},actor:{data:{role:'admin'}},integrations:{},jobs:[]}})},'@/lib/api':{api:async(url,options)=>{calls.push({url,options});return []}}};
 const c=component('components/operations/Administration.tsx',mocks);
 const tree=c.render('Settings',{section:h.navigation[0][1]});
 for(const panel of expectedPanels)assert(nodes(tree).some(n=>n.type===panel),'Missing actual review panel '+panel);
 assert.equal(nodes(tree).some(n=>n.type==='h2'&&text(n)==='Clinic preferences'),section==='Clinic');
 if(section==='Integrations'){
  const controls=component('components/AdvancedOperations.tsx',{...mocks,'./ui':new Proxy({patientOptions:()=>[]},{get:(target,name)=>target[name]||String(name)})}).render('TestConnections',{});
  assert(nodes(controls).some(n=>n.type==='TwilioTrial'),'Sender and provider-receipt review must be reachable here');
 }
 assert(!calls.some(c=>c.options?.method==='POST'));
});

test('unknown settings section cannot select an arbitrary panel',()=>{
 const c=component('components/operations/Administration.tsx',{'@/lib/workspace':{useWorkspace:()=>({records:[{id:'settings',kind:'settings',data:{}}],snapshot:{clinic:{id:'fixture'},actor:{data:{role:'admin'}}}})},'@/lib/api':{api:async()=>[]}});
 assert(nodes(c.render('Settings',{section:'Untrusted section'})).some(n=>n.type==='h2'&&text(n)==='Clinic preferences'));
});

const plot={concept:{code:'synthetic_marker',name:'SYNTHETIC marker',unit:'mmol/L'},timezone:'Asia/Singapore',series:[
 {record_id:'point-a',version:2,observed_at:'2098-07-09T16:00:00Z',time_basis:'observed',value:0,ref_low:1,ref_high:3,flag:'low',event_id:'event-a'},
 {record_id:'point-b',version:1,observed_at:'2098-07-11T01:00:00Z',time_basis:'recorded',value:2,ref_low:null,ref_high:null,flag:null,event_id:'event-b'},
]};
const plotRows=plot.series.map(p=>({id:p.record_id,kind:'observation',version:p.version,data:{name:'SYNTHETIC marker',value:p.value,unit:'mmol/L'}}));
const plotQuery={kind:'observation',presentation:'trend',patient_id:'synthetic-patient',code:'synthetic_marker',unit:'mmol/L',start:'2098-07-10',end:'2098-07-12'};

test('shared chart preserves supplied bands and exact accessible source identities',()=>{
 const clicked=[];const c=component('components/ReferenceChart.tsx',{});
 const tree=c.render('ReferenceChart',{data:plot,sourceLabel:'record',onPoint:id=>clicked.push(id)});
 const all=nodes(tree);assert.equal(all.filter(n=>n.type==='rect').length,1,'Missing range must not invent a band');
 assert.match(text(tree),/code: synthetic_marker · mmol\/L · Asia\/Singapore/);
 assert.match(text(tree),/Record timestamp/);assert.match(text(tree),/gaps do not imply zero/);
 assert(!text(tree).toLowerCase().includes('laboratory'));
 const points=all.filter(n=>n.type==='g'&&n.props.role==='button');assert.equal(points.length,2);
 assert.match(points[0].props['aria-label'],/Open source record/);points[0].props.onClick();
 let prevented=false;points[1].props.onKeyDown({key:'Enter',preventDefault:()=>prevented=true});
 assert(prevented);assert.deepEqual(clicked,['point-a','point-b']);
 all.find(n=>n.type==='button'&&text(n)==='Open record v2 ↗').props.onClick();assert.equal(clicked.at(-1),'point-a');
 const native=c.render('ReferenceChart',{data:{concept:plot.concept,series:[{...plot.series[0],record_id:undefined}]},onPoint:id=>clicked.push(id)});
 nodes(native).find(n=>n.type==='button').props.onClick();assert.equal(clicked.at(-1),'event-a');
 assert(!nodes(c.render('ReferenceChart',{data:{...plot,series:[]},onPoint:()=>{}})).some(n=>n.type==='svg'));
});

test('saved assistant trend opens the exact point version and saves the exact plot query',async()=>{
 const h=await savedAssistant({turn_id:'trend',request_key:'trend-key',message:'Plot exact recorded values',status:'completed',text:'Two matching observations',sources:plotRows,dashboard:{title:'SYNTHETIC numeric trend',query:plotQuery,trend:plot,count:2,groups:[]}});
 const chart=nodes(h.tree).find(n=>n.type==='ReferenceChart');assert(chart);assert.equal(chart.props.data,plot);
 chart.props.onPoint('point-a');const modal=nodes(h.render()).find(n=>n.type==='SourceModal');assert.equal(modal.props.source.id,'point-a');assert.equal(modal.props.source.version,2);
 await nodes(h.tree).find(n=>n.type==='BusyButton'&&text(n)==='Save this view').props.onClick();
 const saved=h.calls.find(c=>c.action==='dashboard.save');assert.equal(JSON.stringify(saved.payload.query),JSON.stringify(plotQuery));
 assert.deepEqual(h.navigation,[['Reports']]);assert(!h.calls.some(c=>c.url?.includes('/confirm')));
});

test('saved trend refresh replaces versions and reconciliation epoch clears cached chart and source',async()=>{
 const view={id:'saved-plot',version:1,kind:'dashboard',data:{name:'SYNTHETIC saved plot'}};
 const w={records:[view],snapshot:{clinic:{id:'synthetic-clinic'},clinical_verification:{epoch:'before'}}};
 let response={...view,result:{count:2,query:plotQuery,trend:plot,records:plotRows,groups:[],filter_summary:'Exact synthetic query',timezone:'Asia/Singapore',refreshed_at:'2098-07-12T00:00:00Z'}};
 const calls=[];
 const c=component('components/AdvancedOperations.tsx',{'@/lib/workspace':{useWorkspace:()=>w},'@/lib/api':{api:async url=>{calls.push(url);return response}},'./ui':new Proxy({patientOptions:()=>[]},{get:(target,name)=>target[name]||String(name)})});
 let tree=c.render('SavedViews',{});
 nodes(tree).find(n=>n.type==='select').props.onChange({target:{value:view.id}});await settle();tree=c.render('SavedViews',{});
 nodes(tree).find(n=>n.type==='ReferenceChart').props.onPoint('point-b');
 assert.equal(nodes(c.render('SavedViews',{})).find(n=>n.type==='SourceModal').props.source.id,'point-b');
 const revisedRows=plotRows.map(r=>({...r,version:3}));response={...response,result:{...response.result,records:revisedRows,trend:{...plot,series:plot.series.map(p=>({...p,version:3}))}}};
 await nodes(tree).find(n=>n.type==='BusyButton'&&text(n)==='Refresh results').props.onClick();tree=c.render('SavedViews',{});
 assert.equal(nodes(tree).find(n=>n.type==='ReferenceChart').props.data.series[0].version,3);
 assert(!nodes(tree).some(n=>n.type==='SourceModal'));
 w.snapshot.clinical_verification.epoch='after-hold';c.render('SavedViews',{});tree=c.render('SavedViews',{});
 assert(!nodes(tree).some(n=>n.type==='ReferenceChart'||n.type==='SourceModal'));assert.equal(calls.length,2);
});

test('a saved point cannot silently open a different current record version',()=>{
 const source={...plotRows[0],data:{...plotRows[0].data,value:99}};
 const w={records:[{...source,version:3}],offline:false};
 const c=component('components/ui.tsx',{'@/lib/workspace':{useWorkspace:()=>w}});
 const tree=c.render('SourceModal',{source,expectedVersion:2,onClose:()=>{}});
 assert.match(text(tree),/saved result used record version 2/);assert.match(text(tree),/current record is version 3/);
 assert(!text(tree).includes('99'));
 w.records=[];const held=c.render('SourceModal',{source,expectedVersion:2,onClose:()=>{}});
 assert.match(text(held),/no longer available as a current clinical fact/);assert(!text(held).includes('99'));
});
