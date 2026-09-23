export type Receipt={kind:'document'|'audio'|'event'|'human';id:string;receipt_id:string;page?:number;start_ms?:number;end_ms?:number};
export type Measurement={id:string;concept:string;name:string;value:number;unit:string;ref_low:number|null;ref_high:number|null;flag:'high'|'low'|null;source:Receipt|null};
export type PatientEvent={id:string;event_type:string;occurred_at:string;summary:string;actor:{kind:string;name:string};source:Receipt|null;body:Record<string,unknown>;flags:{type:string;observation_id?:string}[];observations:Measurement[]};
export type PatientV2={id:string;name:string;species:string;breed:string;sex:string;date_of_birth:string|null;owner:{id:string;name:string}|null;last_seen:string|null};
export type Series={concept:{id:string;name:string;unit:string};series:{observed_at:string;value:number;ref_low:number|null;ref_high:number|null;flag:string|null;event_id:string;source:Receipt|null}[]};
