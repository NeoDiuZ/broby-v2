const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');

function load(relative, overrides={}) {
 const exports={};
 const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,relative),'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,allowJs:true}
 }).outputText;
 vm.runInNewContext(code,{exports,process:{env:{NODE_ENV:'production'}},
  require:name=>overrides[name]||require(name)});
 return exports;
}

test('hosted legal chrome displays preview limitations before the reference text',()=>{
 const banner=load('../marketing/components/StagingBanner.jsx');
 const app=load('../pages/_app.jsx',{'next/head':{default:()=>null},'../marketing/components/StagingBanner.jsx':banner});
 const html=renderToStaticMarkup(React.createElement(app.default,{
  Component:()=>React.createElement('article',null,'Earlier product reference policy'),pageProps:{}
 }));
 assert.match(html,/aria-label="Broby V2 preview status"/);
 assert.match(html,/await approval for V2/);
 assert.match(html,/no verified automatic 90-day audio deletion/);
 assert.match(html,/Customer messaging and live payments are not enabled/);
 assert.ok(html.indexOf('synthetic preview')<html.indexOf('<article>'));
});
