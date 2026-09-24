import type {ChartFrame, DrawObject, WorkDecision} from './net/chart';
import type {ThesisView} from './thesisView';
import {fmt} from './fmt';

export type PlanOutcome='A_REACHED'|'B_HIT'|'REPLACED'|'EXPIRED'|'LIVE';
export type PlanVersion={
  id:string; index:number; day:string; created_ms:number; stage:string; key:string; zone_id:string|null; zone_lo:number|null; zone_hi:number|null; scenario_a:number|null; scenario_b:number|null; outcome:PlanOutcome; what_changed:string;
};

const tfMs=(tf:string)=>({M1:60000,M5:300000,M15:900000,M30:1800000,H1:3600000,H4:14400000,D1:86400000,W1:604800000}[tf]??900000);
const clean=(text:string)=>text.replace(/\s+/g,' ').replace(/\b([A-Z]+_[A-Z0-9_]+)\b/g,(_,raw)=>String(raw).toLowerCase().replaceAll('_',' ')).trim();
const nyTradingDay=(ms:number)=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(ms-17*60*60*1000));
const materialKey=(thesis:ThesisView|null)=>thesis?[
  thesis.stage,thesis.bias,thesis.bias_cause?.event_id??'',thesis.plan?.zone_id??'',
  thesis.alternative?.trigger_level??'',thesis.invalidation?.level??'',thesis.dry_run?.passes??'',thesis.dry_run?.first_fail??''
].join('|'):'';
const latestDecision=(frame:ChartFrame|null)=>[...(frame?.candidate_worklog??[]),...(frame?.worklog??[])].filter((entry):entry is WorkDecision=>typeof (entry as WorkDecision).label==='string'&&Number.isFinite(Number((entry as WorkDecision).at_ms))).sort((a,b)=>Number(a.at_ms)-Number(b.at_ms)).at(-1);

export class PlanTracker{
  private versions:PlanVersion[]=[];
  private lastKey='';
  private lastMinorMs=0;
  private day='';
  update(frame:ChartFrame|null,thesis:ThesisView|null,price:number|null):PlanVersion[]{
    const now=Number(frame?.now_ms??Date.now());
    const day=nyTradingDay(now);
    if(day!==this.day){
      this.day=day;this.lastKey='';this.lastMinorMs=0;this.versions=[];
    }
    const key=materialKey(thesis);
    if(!thesis||!key)return this.versions;
    const last=this.versions.at(-1);
    if(last?.outcome==='LIVE'){
      if(last.scenario_a!=null&&price!=null&&((thesis.bias==='BULLISH'&&price>=last.scenario_a)||(thesis.bias==='BEARISH'&&price<=last.scenario_a)))last.outcome='A_REACHED';
      else if(last.scenario_b!=null&&price!=null&&((thesis.bias==='BULLISH'&&price<=last.scenario_b)||(thesis.bias==='BEARISH'&&price>=last.scenario_b)))last.outcome='B_HIT';
    }
    if(key===this.lastKey)return this.versions;
    const previousCause=last?.key.split('|')[2]??'';
    const cause=thesis.bias_cause?.event_id??'';
    const hard=thesis.stage.startsWith('CALL_')||thesis.stage==='JUST_RESOLVED'||Boolean(cause&&cause!==previousCause);
    const frameTf=frame?.snapshot?.tf??frame?.update?.tf??'M15';
    if(!hard&&now-this.lastMinorMs<2*tfMs(frameTf))return this.versions;
    if(last?.outcome==='LIVE')last.outcome='REPLACED';
    const decision=latestDecision(frame);
    const index=this.versions.length+1;
    const zoneLo=Number(thesis.plan?.zone_lo??thesis.dry_run?.zone_lo);
    const zoneHi=Number(thesis.plan?.zone_hi??thesis.dry_run?.zone_hi);
    const version:PlanVersion={
      id:`${day}:v${index}:${key}`,
      index,day,created_ms:now,stage:thesis.stage,key,
      zone_id:thesis.plan?.zone_id??thesis.dry_run?.zone_id??null,
      zone_lo:Number.isFinite(zoneLo)?zoneLo:null,
      zone_hi:Number.isFinite(zoneHi)?zoneHi:null,
      scenario_a:Number.isFinite(Number(thesis.alternative?.trigger_level))?Number(thesis.alternative?.trigger_level):Number.isFinite(Number(thesis.targets?.[0]?.level))?Number(thesis.targets?.[0]?.level):null,
      scenario_b:Number.isFinite(Number(thesis.invalidation?.level??thesis.alternative?.invalidation_level))?Number(thesis.invalidation?.level??thesis.alternative?.invalidation_level):null,
      outcome:'LIVE',
      what_changed:clean(decision?.label??thesis.why??thesis.headline??'plan updated'),
    };
    this.versions.push(version);
    this.lastKey=key;this.lastMinorMs=now;
    return this.versions;
  }
  snapshot(){return this.versions.slice();}
}

const anim={in_:'fade',loop:null};
const point=(t_ms:number,price:number)=>({t_ms,price});
function obj(id:string,token:string,shape:DrawObject['shape'],points:DrawObject['points'],text_args:Record<string,unknown>,source:string,opacity:number):DrawObject{
  return {id,layer:'L3',shape,points,style:{token},text_key:id,text_args:{...text_args,opacity,source_object_id:source},state:'FRESH',ttl_ms:0,priority:2,z:2,anim,source_bars:[0],confidence:1,reason:'Plan version from thesis',digits:2} as DrawObject;
}
export function buildPlanObjects(plans:PlanVersion[],frame:ChartFrame|null,price:number|null):DrawObject[]{
  if(!frame||frame.chart_density!=='notebook')return [];
  const bars=frame.snapshot?.bars??(frame.update?[frame.update.bar]:[]),last=bars.at(-1);if(!last)return [];
  const now=last.t_open_ms, margin=tfMs(last.tf)*20, visible=plans.slice(-4), out:DrawObject[]=[];
  for(const plan of visible){
    const current=plan===visible.at(-1),opacity=current?1:.3,label=`v${plan.index}${current?'':`  ${fmt.time(plan.created_ms)}`}`;
    const end=now+margin*.55;
    if(plan.zone_lo!=null&&plan.zone_hi!=null){
      out.push(obj(`plan:${plan.id}:zone:lo`,'notebook.plan',[point(plan.created_ms,plan.zone_lo),point(now+margin,plan.zone_lo)].length?'PATH':'PATH',[point(plan.created_ms,plan.zone_lo),point(now+margin,plan.zone_lo)],{label,level:plan.zone_lo},plan.zone_id??plan.id,opacity));
      out.push(obj(`plan:${plan.id}:zone:hi`,'notebook.plan','PATH',[point(plan.created_ms,plan.zone_hi),point(now+margin,plan.zone_hi)],{label,level:plan.zone_hi},plan.zone_id??plan.id,opacity));
    }
    if(price!=null&&plan.scenario_a!=null)out.push(obj(`plan:${plan.id}:A`,'notebook.scenario','PATH',[point(now,price),point(end,plan.scenario_a)],{label:`${label} A`,direction:'A',label_at_end:true},plan.id,opacity));
    if(price!=null&&plan.scenario_b!=null)out.push(obj(`plan:${plan.id}:B`,'notebook.scenario','PATH',[point(now,price),point(end,plan.scenario_b)],{label:`${label} B`,direction:'B',label_at_end:true},plan.id,opacity));
  }
  return out;
}

export function planNotes(plans:PlanVersion[]):string[]{
  return plans.slice(-4).map(plan=>`v${plan.index} ${fmt.time(plan.created_ms)}  ${plan.what_changed}${plan.outcome!=='LIVE'?`  ${plan.outcome==='A_REACHED'?'A reached':plan.outcome==='B_HIT'?'B hit':plan.outcome.toLowerCase().replaceAll('_',' ')}`:''}`);
}
export function planHistorySlide(plans:PlanVersion[]):string{
  if(!plans.length)return '';
  return `Today: ${plans.slice(-6).map(plan=>`v${plan.index}${plan.outcome==='LIVE'?' live':''}`).join('  ')}`;
}
