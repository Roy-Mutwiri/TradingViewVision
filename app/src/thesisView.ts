export type ThesisView={
  headline:string;
  stage:string;
  bias:string;
  key:string;
  lines:string[];
  why:string;
  if_then:string;
  plan?:{side?:string;zone_id?:string|null;zone_lo?:number|null;zone_hi?:number|null;zone_ok?:boolean;zone_problem?:string|null};
  price_position?:{label?:string;distance_to_eq?:number|null};
  blocking_gate?:{code?:string;passed?:boolean;threshold?:number|null;distance?:number|null};
  dealing_range?:{lo?:number|null;hi?:number|null;eq?:number|null};
  invalidation?:{level?:number|null;rule?:string|null};
  targets?:{id?:string;name?:string;level?:number;distance?:number}[];
  alternative?:{trigger_level?:number|null;consequence?:string|null;invalidation_level?:number|null;invalidation_consequence?:string|null};
  dry_run?:{tf?:string;direction?:string;grade?:string;grade_notes?:string[];zone_id?:string|null;zone_lo?:number|null;zone_hi?:number|null;entry_ref?:number|null;stop?:number|null;tp1?:number|null;tp1_name?:string|null;reward_r?:number|null;min_r?:number;first_fail?:string|null;passes?:boolean;distance_to_zone?:number|null;target_close_note?:string|null};
  htf_alignment?:string;
  bias_since?:number|null;
  bias_cause?:{event_id?:string|null;level?:number|null;t_ms?:number|null;kind?:string|null};
};

const objectOrUndefined=<T extends object>(value:unknown):T|undefined=>typeof value==='object'&&value?value as T:undefined;

export function thesisView(value:unknown):ThesisView|null{
  if(!value||typeof value!=='object')return null;
  const item=value as Record<string,unknown>;
  return {
    headline:String(item.headline??''),
    stage:String(item.stage??''),
    bias:String(item.bias??''),
    key:String(item.key??''),
    lines:Array.isArray(item.lines)?item.lines.map(String).slice(0,5):[],
    why:String(item.why??''),
    if_then:String(item.if_then??''),
    plan:objectOrUndefined<NonNullable<ThesisView['plan']>>(item.plan),
    price_position:objectOrUndefined<NonNullable<ThesisView['price_position']>>(item.price_position),
    blocking_gate:objectOrUndefined<NonNullable<ThesisView['blocking_gate']>>(item.blocking_gate),
    dealing_range:objectOrUndefined<NonNullable<ThesisView['dealing_range']>>(item.dealing_range),
    invalidation:objectOrUndefined<NonNullable<ThesisView['invalidation']>>(item.invalidation),
    targets:Array.isArray(item.targets)?item.targets as ThesisView['targets']:[],
    alternative:objectOrUndefined<NonNullable<ThesisView['alternative']>>(item.alternative),
    dry_run:objectOrUndefined<NonNullable<ThesisView['dry_run']>>(item.dry_run),
    htf_alignment:typeof item.htf_alignment==='string'?item.htf_alignment:undefined,
    bias_since:Number.isFinite(Number(item.bias_since))?Number(item.bias_since):null,
    bias_cause:objectOrUndefined<NonNullable<ThesisView['bias_cause']>>(item.bias_cause),
  };
}

