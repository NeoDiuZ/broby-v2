export type Row={id:string;kind:string;clinic_id:string;version:number;created_at:string;updated_at:string;data:Record<string,any>};
export type Snapshot={records:Row[];actor:Row;clinic:Row;clinics:(Row&{member_id?:string})[];jobs:any[];permissions:string[];integrations:Record<string,boolean>;mode:string};
export type Command={action:string;payload:Record<string,any>;key:string};
export const money=(c:number)=>new Intl.NumberFormat('en-SG',{style:'currency',currency:'SGD'}).format(c/100);
export const today=()=>new Date().toLocaleDateString('en-CA');
export const dayLabel=(d:string)=>new Date(d+'T12:00:00').toLocaleDateString('en-SG',{weekday:'long',day:'numeric',month:'long'});
export const speciesClass=(s:string)=>({Dog:'dog',Cat:'cat',Rabbit:'rabbit',Bird:'bird',Reptile:'reptile'}[s]||'other');
export const initials=(s:string)=>s.split(' ').map(v=>v[0]).slice(0,2).join('');

export function patientAge(data:Record<string,any>){
 if(!data.date_of_birth)return data.age||'Age not recorded';
 const born=new Date(data.date_of_birth+'T00:00:00Z');
 const current=new Date(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())+'T00:00:00Z');
 let months=(current.getUTCFullYear()-born.getUTCFullYear())*12+current.getUTCMonth()-born.getUTCMonth();
 if(current.getUTCDate()<born.getUTCDate())months--;
 if(months<1)return 'Under 1 month';
 return months<12?months+' month'+(months===1?'':'s'):Math.floor(months/12)+' year'+(months<24?'':'s');
}
