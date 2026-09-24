import type {Snapshot} from './types';
export const READ_LABELS:Record<string,string>={
 'read.patients':'Patients and owner contacts','read.clinical':'Clinical notes, measurements, files and audio',
 'read.billing':'Invoices, payments and credits','read.inventory':'Inventory and purchasing',
 'read.schedule':'Appointments and staff rota','read.messages':'Messages, recalls and owner submissions',
 'read.staff':'Other staff memberships','read.reports':'Combined reports and saved views',
};
export const fullReadAccess=(snapshot:Snapshot)=>Object.keys(READ_LABELS).every(p=>snapshot.read_permissions?.includes(p));
export function pageAllowed(snapshot:Snapshot,page:string){
 const requirements:Record<string,string[]>={Settings:[],Patients:['read.patients'],Clients:['read.patients'],Billing:['read.patients','read.billing'],Inventory:['read.inventory'],Appointments:['read.patients','read.schedule','read.staff'],Messages:['read.patients','read.messages'],Templates:['read.patients','read.clinical']};
 return (requirements[page]||Object.keys(READ_LABELS)).every(p=>snapshot.read_permissions?.includes(p));
}
