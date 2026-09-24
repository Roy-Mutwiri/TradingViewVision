import {fmt} from './fmt';
import type {ChartFrame, Pool, DrawObject, UTBotDrawObject} from './net/chart';
import type {RetentionFrame, Call, CallStats2} from './net/retention';
import type {ThesisView} from './thesisView';

export type AnalysisSlideType='THESIS'|'CONTEXT'|'STORY'|'WHY'|'WHERE'|'NEXT'|'STATS'|'PLAN'|'PLAN HISTORY'|'LIQUIDITY'|'TIMEFRAMES'|'MOMENTUM'|'INVALIDATION'|'SCENARIOS'|'SCORE'|'CALL'|'NEWS';
export type AnalysisSlide={type:AnalysisSlideType;content:string;key:string;changed_ms:number;anchor?:boolean;interruptKey?:string};
export type AnalysisSlideInput={
  thesis:ThesisView|null;
  frame:ChartFrame|null;
  retention:RetentionFrame|null;
  tf:string;
  price:number|null;
  liveSignal?:Call|null;
  liveSignalR?:number;
  now:number;
  planHistory?:string;
  book?:Record<string,unknown>|null;
};

const fixedOrder:AnalysisSlideType[]=['CONTEXT','STORY','WHY','WHERE','NEXT','STATS','PLAN','PLAN HISTORY','LIQUIDITY','TIMEFRAMES','MOMENTUM','INVALIDATION','SCENARIOS','SCORE','NEWS'];
const clean=(s:string)=>s.replace(/\s*\/\s*/g,'  ').replace(/\s+/g,' ').replace(/ {3,}/g,'  ').trim();
const rawEnum=/\b[A-Z]+_[A-Z0-9_]+\b/;
const friendly=(value:string)=>value.toLowerCase().replaceAll('_',' ');
const usable=(s:string)=>Boolean(s)&&!/(^--$|pending|undefined|null|0\.00 away)/i.test(s)&&!rawEnum.test(s);
const ms=(value:unknown)=>Number.isFinite(Number(value))?Number(value):0;
const priceAt=(pool:Pool)=>pool.geometry.level;
const poolName=(pool:Pool)=>pool.geometry.name||pool.scope_key||pool.id||'POOL';
const stateTarget=(pool:Pool)=>!pool.state||pool.state==='FRESH'||pool.state==='TOUCHED';
const directionWord=(direction:string|undefined)=>direction==='LONG'?'BUY':direction==='SHORT'?'SELL':direction??'';
const displayGate=(value:string|undefined|null)=>String(value??'').replaceAll('_',' ').toLowerCase();
const callEntry=(call:Call)=>Number.isFinite(Number(call.entry_ref))?Number(call.entry_ref):call.direction==='LONG'?call.entry_hi:call.entry_lo;

function nearestPools(pools:Pool[],price:number|null){
  if(!Number.isFinite(Number(price)))return {below:null as Pool|null,above:null as Pool|null};
  const p=Number(price);
  const eligible=pools.filter(stateTarget);
  const below=eligible.filter(pool=>priceAt(pool)<p).sort((a,b)=>p-priceAt(a)-(p-priceAt(b)))[0]??null;
  const above=eligible.filter(pool=>priceAt(pool)>p).sort((a,b)=>priceAt(a)-p-(priceAt(b)-p))[0]??null;
  return {below,above};
}

function latestUt(objects:(DrawObject|UTBotDrawObject)[]){
  return objects.filter(obj=>'indicator' in obj&&obj.indicator==='utbot').sort((a,b)=>ms(b.points?.[0]?.t_ms)-ms(a.points?.[0]?.t_ms))[0] as UTBotDrawObject|undefined;
}

function callSlide(call:Call|undefined|null,r:number|undefined,tf:string,now:number):AnalysisSlide|null{
  if(!call||!["PENDING","ACTIVE"].includes(call.state??"PENDING"))return null;
  const side=directionWord(call.direction);
  const barsLeft=call.expires_ms>now?Math.max(0,Math.ceil((call.expires_ms-now)/60000)):0;
  const grade=call.grade??"A";
  const notes=(call.grade_notes??[]).join("  ");
  const content=clean(`${call.timeframe??tf} ${side}  Grade ${grade}${notes?`  ${notes}`:""}  ENTRY ${fmt.price(callEntry(call))}  SL ${fmt.price(call.invalidation)}  TP1 ${fmt.price(call.target)}  ${fmt.r(r)}  ${call.state??"PENDING"}${(call.state??"PENDING")==="PENDING"?` ${barsLeft}m`:""}  PAPER`);
  return {type:"CALL",content,key:`CALL:${call.id??call.created_ms}:${call.state}`,changed_ms:call.created_ms,anchor:true,interruptKey:`CALL:${call.state}:${call.id??call.created_ms}`};
}


export function buildAnalysisSlides(input:AnalysisSlideInput):AnalysisSlide[]{
  const slides:AnalysisSlide[]=[];
  const {thesis,frame,retention,tf,price,liveSignal,liveSignalR,now,planHistory,book}=input;
  const openCall=callSlide(liveSignal,liveSignalR,tf,now);
  if(openCall)slides.push(openCall);
  if(thesis&&usable(thesis.headline)&&!openCall){
    slides.push({type:'THESIS',content:clean(thesis.headline),key:`THESIS:${thesis.key||thesis.headline}`,changed_ms:frame?.now_ms??now,anchor:true});
  }

  const bookSlides=Array.isArray(book?.slides)?book.slides as Array<Record<string,unknown>>:[];
  for(const [i,slide] of bookSlides.entries()){
    const type=String(slide.type??'').toUpperCase() as AnalysisSlideType;
    const text=clean(String(slide.text??''));
    if(['CONTEXT','STORY','WHY','WHERE','NEXT','STATS'].includes(type)&&usable(text))slides.push({type,content:text,key:`BOOK:${type}:${book?.id??''}:${i}:${text}`,changed_ms:Number(book?.generated_ms??frame?.now_ms??now)});
  }

  if(!bookSlides.some(slide=>String(slide.type).toUpperCase()==='WHY')&&thesis?.why&&usable(thesis.why)){
    const cause=thesis.bias_cause;
    const suffix=cause?.level?`  ${fmt.price(cause.level)}${cause?.t_ms?` ${fmt.time(cause.t_ms)}`:''}`:'';
    slides.push({type:'WHY',content:clean(`${thesis.why}${suffix}`),key:`WHY:${thesis.bias}:${cause?.event_id??thesis.why}`,changed_ms:cause?.t_ms??frame?.structure_state?.trend_since_ms??0});
  }
  if(thesis){
    let plan='';
    const side=String(thesis.plan?.side??'').toUpperCase();
    if(thesis.stage==='NO_VALID_ZONE'&&thesis.plan?.zone_problem&&thesis.dealing_range){
      const lo=side==='SHORT'?thesis.dealing_range.eq:thesis.dealing_range.lo;
      const hi=side==='SHORT'?thesis.dealing_range.hi:thesis.dealing_range.eq;
      plan=clean(`Needs ${side==='SHORT'?'supply':'demand'} ${fmt.range(lo,hi)}  none valid yet`);
    }else if(thesis.dry_run&&Number.isFinite(Number(thesis.dry_run.reward_r))){
      const dry=thesis.dry_run;
      const r=Number(dry.reward_r);
      const tp=dry.tp1!=null?`${dry.tp1_name??'TP1'} ${fmt.price(dry.tp1)}`:'TP1 pending';
      plan=dry.passes?clean(`Setup now passes R ${fmt.r(r)}  TP1 ${tp}${dry.target_close_note?`  ${dry.target_close_note}`:''}`):clean(dry.first_fail==='R_MIN'&&dry.tp1!=null?`R ${fmt.one(r)} < ${fmt.one(Number(dry.min_r??1.5))}  target ${tp} too close${dry.target_close_note?`  ${dry.target_close_note}`:''}`:`Setup now fails R ${fmt.r(r)}  ${displayGate(dry.first_fail)}${dry.tp1!=null?`  ${tp}`:''}${dry.target_close_note?`  ${dry.target_close_note}`:''}`);
    }else if(thesis.blocking_gate?.code&&Number.isFinite(Number(thesis.blocking_gate.threshold))){
      const d=thesis.blocking_gate.distance;
      plan=Number.isFinite(Number(d))&&Math.abs(Number(d))>0.005?clean(`${friendly(thesis.blocking_gate.code)} ${fmt.price(thesis.blocking_gate.threshold)}  ${fmt.usd(d)} away`):'';
    }else if(thesis.plan?.zone_lo&&thesis.plan?.zone_hi){
      plan=clean(`${side||'PLAN'} zone ${fmt.range(thesis.plan.zone_lo,thesis.plan.zone_hi)}`);
    }
    if(!usable(plan)&&(!thesis.dry_run)&&String(thesis.bias??'UNDEFINED')==='UNDEFINED')plan='WATCH after M15 bias confirms';
    if(usable(plan))slides.push({type:'PLAN',content:plan,key:`PLAN:${thesis.stage}:${thesis.plan?.zone_id??thesis.blocking_gate?.code??plan}:${thesis.dry_run?.passes}:${thesis.dry_run?.first_fail}:${Math.round(Number(thesis.dry_run?.reward_r??0)*10)}`,changed_ms:frame?.now_ms??now,interruptKey:thesis.dry_run?`DRY:${thesis.dry_run.zone_id}:${thesis.dry_run.passes}:${thesis.dry_run.first_fail}:${Math.round(Number(thesis.dry_run.reward_r??0)*10)}:${Math.round(Number(thesis.dry_run.tp1??0)*100)}`:undefined});
  }
  if(planHistory&&usable(planHistory))slides.push({type:'PLAN HISTORY',content:planHistory,key:`PLANH:${planHistory}`,changed_ms:frame?.now_ms??now,interruptKey:`PLANH:${planHistory}`});
  const pools=nearestPools(frame?.liquidity_pools??[],price);
  if(pools.below||pools.above){
    const below=pools.below?`${poolName(pools.below)} below ${fmt.price(priceAt(pools.below))} ${fmt.usd(Number(price)-priceAt(pools.below))}`:'';
    const above=pools.above?`${poolName(pools.above)} above ${fmt.price(priceAt(pools.above))} ${fmt.usd(priceAt(pools.above)-Number(price))}`:'';
    const content=clean([below,above].filter(Boolean).join('  '));
    slides.push({type:'LIQUIDITY',content,key:`LIQ:${pools.below?.id??''}:${pools.above?.id??''}`,changed_ms:Math.max(ms(pools.below?.swept_ms),ms(pools.above?.swept_ms),frame?.now_ms??0)});
  }
  const trend=frame?.structure_state?.trend;
  const alignment=String(thesis?.htf_alignment??'undefined').toLowerCase();
  if(trend&&trend!=='UNDEFINED'&&alignment!=='undefined'&&alignment!=='current view'){
    const side=alignment.includes('disagree')?'H1 disagrees':'aligned';
    slides.push({type:'TIMEFRAMES',content:clean(`H4 ${trend}  H1 ${side==='H1 disagrees'?'disagrees':trend}  ${tf} ${trend}  ${side}`),key:`TF:${tf}:${trend}:${alignment}`,changed_ms:frame?.structure_state?.trend_since_ms??0});
  }
  const ut=latestUt(frame?.objects??[]);
  if(ut){
    const utState=ut.direction==='BULLISH'?'BUY':ut.direction==='BEARISH'?'SELL':ut.direction;
    const agrees=(ut.direction==='BULLISH'&&thesis?.bias==='BULLISH')||(ut.direction==='BEARISH'&&thesis?.bias==='BEARISH');
    slides.push({type:'MOMENTUM',content:clean(`UT ${utState} since ${fmt.time(ut.points[0]?.t_ms)}  ${agrees?'agrees with bias':'against bias'}`),key:`MOM:${ut.id??ut.object_hash}:${utState}:${thesis?.bias??''}`,changed_ms:ut.points[0]?.t_ms??0});
  }
  if(thesis?.invalidation?.level&&thesis.invalidation.rule){
    slides.push({type:'INVALIDATION',content:clean(`${friendly(thesis.invalidation.rule)}  ${fmt.price(thesis.invalidation.level)}`),key:`INV:${thesis.invalidation.level}:${thesis.invalidation.rule}`,changed_ms:frame?.now_ms??now});
  }
  if(thesis?.if_then&&usable(thesis.if_then)){
    slides.push({type:'SCENARIOS',content:clean(thesis.if_then),key:`SCEN:${thesis.key}:${thesis.if_then}`,changed_ms:frame?.now_ms??now});
  }
  const today=retention?.scoreboard?.today as CallStats2|undefined;
  if(today){
    const resolved=Number(today.resolved??0),wins=Number(today.wins??0),losses=Number(today.losses??0);
    const ft=`Forward ${resolved}/60${resolved<20?'  n<20':today.expectancy!=null?`  ${fmt.r(today.expectancy)}`:''}`;
    const content=`Today ${wins}W ${losses}L  Resolved ${resolved}  ${ft}`;
    slides.push({type:'SCORE',content,key:`SCORE:${wins}:${losses}:${resolved}:${today.expectancy??'n'}`,changed_ms:frame?.now_ms??now} as AnalysisSlide);
  }
  const seen=new Set<string>();
  return slides.filter(slide=>usable(slide.content)&&!seen.has(slide.type)&&(seen.add(slide.type),true));
}

export function rotateAnalysisSlides(slides:AnalysisSlide[]):AnalysisSlide[]{
  if(slides.length<=2)return slides;
  const anchor=slides.find(slide=>slide.anchor)||slides.find(slide=>slide.type==='THESIS')||slides[0];
  const rest=slides.filter(slide=>slide!==anchor).sort((a,b)=>{
    const recent=(b.changed_ms??0)-(a.changed_ms??0);
    if(recent)return recent;
    return fixedOrder.indexOf(a.type)-fixedOrder.indexOf(b.type);
  });
  const ordered:AnalysisSlide[]=[];
  let countSinceAnchor=3;
  for(const slide of rest){
    if(countSinceAnchor>=2){ordered.push(anchor);countSinceAnchor=0;}
    ordered.push(slide);countSinceAnchor+=1;
  }
  if(!ordered.includes(anchor))ordered.unshift(anchor);
  return ordered;
}

export function validateSlideLengths(slides:AnalysisSlide[],maxContent=116):string[]{
  return slides.filter(slide=>slide.content.length>maxContent).map(slide=>`${slide.type}:${slide.content.length}`);
}





