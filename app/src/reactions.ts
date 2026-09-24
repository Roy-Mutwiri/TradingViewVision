import type {ChartFrame, DrawObject} from './net/chart';
import {fmt} from './fmt';

export type ReactionState='TESTING'|'HELD'|'REJECTED'|'BROKE'|'UNRESOLVED';
export type LevelReaction={id:string;source_id:string;created_ms:number;created_bar:number;level:number;label:string;state:ReactionState;resolved_ms?:number};
const tfMs=(tf:string)=>({M1:60000,M5:300000,M15:900000,M30:1800000,H1:3600000,H4:14400000,D1:86400000,W1:604800000}[tf]??900000);
const point=(t_ms:number,price:number)=>({t_ms,price});
const anim={in_:'fade',loop:null};
function sourceLabel(obj:DrawObject,level:number){const token=obj.style.token;const raw=String(obj.text_args.name??obj.text_args.label??obj.text_args.kind??'level');if(token.includes('fvg'))return `FVG ${fmt.price(level)}`;if(token.includes('ob'))return `OB ${fmt.price(level)}`;if(token.includes('pool'))return `${raw} ${fmt.price(level)}`;if(token.includes('fib'))return `${raw.split('  ')[0]} ${fmt.price(level)}`;if(token.includes('round'))return `${raw} ${fmt.price(level)}`;if(token.includes('protected'))return `PROTECTED ${fmt.price(level)}`;return `${raw.toUpperCase().slice(0,24)} ${fmt.price(level)}`;}
function levels(objects:DrawObject[]){const out:{id:string;level:number;label:string}[]=[];for(const obj of objects){const id=String(obj.id??obj.text_key);const token=obj.style.token;const candidates=[obj.text_args.level,obj.text_args.unfilled_lo,obj.text_args.unfilled_hi,obj.text_args.zone_lo,obj.text_args.zone_hi,obj.points[0]?.price];if(token==='notebook.plan'||token==='notebook.scenario'||token==='notebook.leg')continue;if(!(token==='notebook.fib'||token==='notebook.round'||token.includes('liquidity')||token.includes('zone')||token.includes('structure.protected')))continue;for(const value of candidates){const level=Number(value);if(Number.isFinite(level)){out.push({id,level,label:sourceLabel(obj,level)});break;}}}return out;}
export class ReactionTracker{
  private reactions:LevelReaction[]=[];
  update(frame:ChartFrame|null,objects:DrawObject[],price:number|null):LevelReaction[]{
    const bars=frame?.snapshot?.bars??(frame?.update?[frame.update.bar]:[]),last=bars.at(-1);if(!frame||!last||price==null)return this.reactions;
    const now=last.t_open_ms, threshold=Math.max(.5,Math.abs(last.h-last.l)*.08), barIndex=Math.floor(now/tfMs(last.tf));
    for(const lvl of levels(objects)){
      if(Math.abs(price-lvl.level)>threshold)continue;
      if(this.reactions.some(r=>r.source_id===lvl.id&&Math.abs(r.level-lvl.level)<.005&&now-r.created_ms<tfMs(last.tf)*12))continue;
      const verb=/SWEPT|NY|LONDON|ASIA|EQH|EQL|PDH|PDL/.test(lvl.label)?'testing':'tapped';
      this.reactions.push({id:`react:${lvl.id}:${Math.round(lvl.level*100)}:${now}`,source_id:lvl.id,created_ms:now,created_bar:barIndex,level:lvl.level,label:`${verb} ${lvl.label}`,state:'TESTING'});
    }
    for(const r of this.reactions){
      if(r.state!=='TESTING')continue;
      const age=barIndex-r.created_bar;
      if(age>=3){r.state='UNRESOLVED';r.resolved_ms=now;}
      else if(last.c>r.level&&last.o<r.level||last.c<r.level&&last.o>r.level){r.state='BROKE';r.resolved_ms=now;}
      else if(Math.abs(price-r.level)>Math.max(1,threshold*3)){r.state='HELD';r.resolved_ms=now;}
    }
    this.reactions=this.reactions.filter(r=>now-r.created_ms<tfMs(last.tf)*50).slice(-12);
    return this.reactions;
  }
  snapshot(){return this.reactions.slice();}
}
export function reactionNotes(reactions:LevelReaction[]):string[]{
  const seen=new Set<string>();
  return reactions.slice().sort((a,b)=>a.created_ms-b.created_ms).filter(r=>{
    const minute=Math.floor(r.created_ms/60000);
    const text=r.state==='TESTING'?r.label:`${r.label.replace(/^(testing|tapped)\s+/i,'')} ${r.state.toLowerCase()}`;
    const key=`${minute}:${text}`;
    if(seen.has(key))return false;
    seen.add(key);
    return true;
  }).slice(-3).map(r=>r.state==='TESTING'?`${fmt.time(r.created_ms)}  ${r.label}`:`${fmt.time(r.created_ms)}  ${r.label.replace(/^(testing|tapped)\s+/i,'')} ${r.state.toLowerCase()}`);
}
export function buildReactionObjects(reactions:LevelReaction[],frame:ChartFrame|null):DrawObject[]{
  const bars=frame?.snapshot?.bars??(frame?.update?[frame.update.bar]:[]),last=bars.at(-1);if(!frame||!last)return [];
  return reactions.slice(-6).map(r=>({id:r.id,layer:'L3',shape:'LABEL',points:[point(r.created_ms,r.level)],style:{token:'notebook.reaction'},text_key:r.id,text_args:{label:r.state==='TESTING'?r.label:`${r.label} ${r.state.toLowerCase()}`,source_object_id:r.source_id,opacity:r.state==='TESTING'?1:.45},state:'FRESH',ttl_ms:0,priority:2,z:2,anim,source_bars:[0],confidence:1,reason:'Level reaction from drawn object touch',digits:2} as DrawObject));
}
