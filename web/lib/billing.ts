export const netCharge=(d:Record<string,any>)=>d.status==='void'?0:d.total_cents-(d.credited_cents||0);
export const outstanding=(d:Record<string,any>)=>d.status==='void'?0:Math.max(0,netCharge(d)-d.paid_cents);
export const refundDue=(d:Record<string,any>)=>d.status==='void'?0:Math.max(0,d.paid_cents-netCharge(d));
export function cents(value:string){
 if(!/^\d+(\.\d{1,2})?$/.test(value))throw new Error('Enter an amount with at most two decimal places.');
 const [whole,fraction='']=value.split('.');const result=Number(whole)*100+Number(fraction.padEnd(2,'0'));
 if(!Number.isSafeInteger(result))throw new Error('Amount is too large.');
 return result;
}
