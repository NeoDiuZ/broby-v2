const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const source=fs.readFileSync(require('node:path').join(__dirname,'../lib/billing.ts'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const billing={};vm.runInNewContext(compiled,{exports:billing});
test('decimal input remains exact cents and cannot hide excess precision',()=>{
 for(const [input,result] of [['0',0],['1.01',101],['0.29',29],['12.30',1230],['4.9',490]])assert.equal(billing.cents(input),result);
 for(const input of ['1.001','1e3','-1','NaN','','0x12','99999999999999999'])assert.throws(()=>billing.cents(input));
});
test('credit and refund balances are distinct, including legacy and void invoices',()=>{
 const d={total_cents:1090,paid_cents:1090,credited_cents:327,status:'refund_due'};
 assert.equal(billing.netCharge(d),763);assert.equal(billing.outstanding(d),0);assert.equal(billing.refundDue(d),327);
 assert.equal(billing.refundDue({...d,paid_cents:763}),0);
 assert.equal(billing.outstanding({...d,paid_cents:0}),763);
 assert.equal(billing.netCharge({...d,status:'void'}),0);
 assert.equal(billing.outstanding({total_cents:100,paid_cents:25,status:'partial'}),75);
});
