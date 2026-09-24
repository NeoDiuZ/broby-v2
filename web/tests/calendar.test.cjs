const test=require('node:test'), assert=require('node:assert/strict');
const ts=require('typescript'), fs=require('node:fs'), vm=require('node:vm');
const compiled=ts.transpileModule(fs.readFileSync(require('node:path').join(__dirname,'../lib/calendar.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const exp={};vm.runInNewContext(compiled,{exports:exp,Date});
const {validCalendarDate,calendarDays,shiftCalendar}=exp;
test('partial or malformed date input cannot create duplicate Invalid Date cells',()=>{
 for(const d of ['','2','2099-','2026-02-30','2026-2-01','0000-01-01','10000-01-01']){
  assert.equal(validCalendarDate(d),false);assert.equal(calendarDays(d,'Week').length,0);assert.equal(shiftCalendar(d,'Week',1),d);
 }
 assert.equal(calendarDays('2099-01-05','Week').length,7);
 assert.equal(new Set(calendarDays('2099-01-05','Week')).size,7);
});
test('month navigation clamps to month end and handles leap years',()=>{
 assert.equal(shiftCalendar('2026-01-31','Month',1),'2026-02-28');
 assert.equal(shiftCalendar('2028-01-31','Month',1),'2028-02-29');
 assert.equal(shiftCalendar('2026-03-31','Month',-1),'2026-02-28');
 assert.equal(shiftCalendar('2026-12-31','Day',1),'2027-01-01');
});
test('calendar range never emits out of range dates and preserves zero padded years',()=>{
 assert.equal(validCalendarDate('0020-01-01'),true);
 for(const date of ['0001-01-01','9999-12-31','0020-01-01']) {
  const days=calendarDays(date,'Month');assert(days.length>0);assert(days.every(validCalendarDate));assert.equal(new Set(days).size,days.length);
 }
 assert.equal(shiftCalendar('9999-12-31','Day',1),'9999-12-31');
 assert.equal(shiftCalendar('0001-01-01','Day',-1),'0001-01-01');
});
