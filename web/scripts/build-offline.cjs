// The shell contains only AuthGate markup. Never cache personalized API output.
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),next=path.join(root,'.next'),pub=path.join(root,'public');
const version=fs.readFileSync(path.join(next,'BUILD_ID'),'utf8').trim();
const list=[];let size=0;
function walk(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){const file=path.join(dir,entry.name);if(entry.isDirectory())walk(file);else if(/\.(js|css|woff2?|ttf)$/.test(file)){list.push('/_next/'+path.relative(next,file).split(path.sep).join('/'));size+=fs.statSync(file).size}}}
walk(path.join(next,'static'));
if(size>20*1024*1024)throw new Error('Offline static bundle exceeds 20 MB; review the asset list.');
const assets=['/offline-workspace.html','/favicon.png','/fonts/PlusJakartaSans-Variable.ttf','/fonts/JetBrainsMono-Medium.ttf',...list];
fs.copyFileSync(path.join(next,'server/app/app.html'),path.join(pub,'offline-workspace.html'));
const template=fs.readFileSync(path.join(__dirname,'service-worker.js'),'utf8');
fs.writeFileSync(path.join(pub,'broby-sw.js'),'const RELEASE='+JSON.stringify(version)+';\nconst ASSETS='+JSON.stringify(assets)+';\n'+template);
console.log(`Offline shell packaged: ${assets.length} assets, ${(size/1024/1024).toFixed(2)} MB of static code.`);
