import type {ChartFrame, DrawObject, Pool} from './net/chart';
import {fmt} from './fmt';

export type AnalysisState='CANDIDATE'|'ACTIVE'|'TESTED'|'RESOLVED_OK'|'RESOLVED_FAIL'|'EXPIRED'|'FADED'|'DELETED';
export type AnalysisObject={id:string;detector:string;tf:string;created_ms:number;state:AnalysisState;geometry:{lo:number;hi:number;level:number};score?:number;reason:string;source_ids:string[];tags:string[]};
type Source={id:string;price:number;tag:string};
const tfMs=(tf:string)=>({M1:60000,M5:300000,M15:900000,M30:1800000,H1:3600000,H4:14400000,D1:86400000,W1:604800000}[tf]??900000);
const point=(t_ms:number,price:number)=>({t_ms,price});
const anim={in_:'fade',loop:null};
const sourcePrice=(object:DrawObject)=>Number(object.text_args.level??object.text_args.unfilled_hi??object.text_args.unfilled_lo??object.points[0]?.price);
const sourceTag=(object:DrawObject)=>{
  const tf=String(object.text_args.tf??'');
  if(object.style.token==='zone.ob')return `${tf} OB`.trim();
  if(object.style.token==='zone.fvg')return `${tf} FVG`.trim();
  if(object.style.token==='notebook.fib')return String(object.text_args.label??'FIB').split('  ')[0];
  if(object.style.token==='notebook.round')return String(object.text_args.label??'RN');
  if(object.style.token==='liquidity.pool')return String(object.text_args.name??'POOL');
  if(object.style.token==='structure.protected')return 'PROTECTED';
  return String(object.text_args.label??object.style.token).toUpperCase();
};
function poolSources(pools:Pool[]):Source[]{return pools.filter(pool=>!['SWEPT','BROKEN'].includes(String(pool.state))).map(pool=>({id:pool.id,price:pool.geometry.level,tag:pool.geometry.name||pool.scope_key||'POOL'}));}
function objectSources(objects:DrawObject[]):Source[]{return objects.filter(object=>['zone.ob','zone.fvg','notebook.fib','notebook.round','liquidity.pool','structure.protected'].includes(object.style.token)).map(object=>({id:String(object.id??object.text_key),price:sourcePrice(object),tag:sourceTag(object)})).filter(item=>Number.isFinite(item.price));}
export function confluenceGroups(sources:Source[],width:number):Source[][]{
  const sorted=sources.filter(item=>Number.isFinite(item.price)).sort((a,b)=>a.price-b.price||a.id.localeCompare(b.id));
  const groups:Source[][]=[];
  for(let left=0;left<sorted.length;left++){
    const window:Source[]=[];
    for(let right=left;right<sorted.length;right++){
      if(sorted[right].price-sorted[left].price>width)break;
      window.push(sorted[right]);
    }
    const distinct=[...new Map(window.map(item=>[item.tag,item])).values()];
    if(distinct.length>=3)groups.push(distinct);
  }
  const seen=new Set<string>();
  return groups
    .map(group=>group.slice().sort((a,b)=>a.price-b.price||a.id.localeCompare(b.id)))
    .filter(group=>{const key=group.map(item=>item.id).sort().join('|');if(seen.has(key))return false;seen.add(key);return true;});
}
export function detectConfluenceStacks(frame:ChartFrame|null,objects:DrawObject[],pools:Pool[],price:number|null):AnalysisObject[]{
  if(!frame||price==null)return [];
  const bars=frame.snapshot?.bars??(frame.update?[frame.update.bar]:[]),last=bars.at(-1);if(!last)return [];
  const atrBars=bars.slice(-14);const atr=atrBars.length?atrBars.reduce((sum,bar,index,arr)=>{const prev=index>0?arr[index-1].c:bar.o;return sum+Math.max(bar.h-bar.l,Math.abs(bar.h-prev),Math.abs(bar.l-prev));},0)/atrBars.length:Math.max(1,last.h-last.l);
  const width=Math.max(.25*atr,.25);
  const sources=[...objectSources(objects),...poolSources(pools)];
  const stacks:AnalysisObject[]=[];
  for(const vals of confluenceGroups(sources,width)){
    const level=vals.reduce((sum,item)=>sum+item.price,0)/vals.length;
    const lo=Math.min(...vals.map(item=>item.price)),hi=Math.max(...vals.map(item=>item.price));
    const key=vals.map(item=>item.id).sort().join('|');
    stacks.push({id:`confluence:${key}`,detector:'CONFLUENCE',tf:last.tf,created_ms:last.t_open_ms,state:vals.length>=3?'ACTIVE':'CANDIDATE',geometry:{lo,hi,level},score:vals.length,reason:`${vals.length} sources overlap inside ${fmt.range(lo,hi)}`,source_ids:vals.map(item=>item.id),tags:vals.map(item=>item.tag).slice(0,4)});
  }
  return stacks.sort((a,b)=>Math.abs(a.geometry.level-price)-Math.abs(b.geometry.level-price)).slice(0,3);
}
export function analysisObjectNotes(items:AnalysisObject[]):string[]{return items.slice(0,3).map(item=>`${fmt.time(item.created_ms)}  confluence ${item.score??''}  ${fmt.range(item.geometry.lo,item.geometry.hi)}  ${item.tags.join('  ')}`);}
export function buildAnalysisObjects(items:AnalysisObject[],frame:ChartFrame|null):DrawObject[]{
  const bars=frame?.snapshot?.bars??(frame?.update?[frame.update.bar]:[]),last=bars.at(-1);if(!last)return [];
  const end=last.t_open_ms+tfMs(last.tf)*20;
  return items.map(item=>({id:item.id,layer:'L3',shape:'PATH',points:[point(last.t_open_ms,item.geometry.level),point(end,item.geometry.level)],style:{token:'detector.confluence'},text_key:item.id,text_args:{label:`CONFLUENCE ${item.score??0}  ${fmt.range(item.geometry.lo,item.geometry.hi)}  ${item.tags.join('  ')}`,level:item.geometry.level,state:item.state,source_object_id:item.source_ids[0],dashed:item.state==='CANDIDATE'},state:item.state==='CANDIDATE'?'CANDIDATE':'FRESH',ttl_ms:0,priority:3,z:2,anim,source_bars:[0],confidence:1,reason:item.reason,digits:2} as DrawObject));
}
