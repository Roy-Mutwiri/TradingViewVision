import type {ChartFrame, DrawObject, WorkDecision} from './net/chart';
import type {ThesisView} from './thesisView';
import {fmt} from './fmt';

const tfMs=(tf:string)=>({M1:60000,M5:300000,M15:900000,M30:1800000,H1:3600000,H4:14400000,D1:86400000,W1:604800000}[tf]??900000);
const anim={in_:'fade',loop:null};
const point=(t_ms:number,price:number)=>({t_ms,price});

function formatNotebookText(value:string):string{
  let text=value.replace(/[\u00e2\u00c3]/g,'').replace(/\s+/g,' ').trim();
  text=text.replace(/(\d{4}(?:\.\d{1,3})?)\s*-\s*(\d{4}(?:\.\d{1,3})?)/g,(_,a,b)=>fmt.range(Number(a),Number(b)));
  text=text.replace(/(?<![\d,])\d{4}(?:\.\d{1,3})?(?![\d,])/g,match=>fmt.price(Number(match)));
  text=text.replace(/\b([A-Z]+_[A-Z0-9_]+)\b/g,(_,raw)=>raw.toLowerCase().replaceAll('_',' '));
  return text;
}

function obj(id:string,token:string,shape:DrawObject['shape'],points:DrawObject['points'],text_args:Record<string,unknown>,reason:string,source:string):DrawObject{
  return {id,layer:'L3',shape,points,style:{token},text_key:id,text_args:{...text_args,source_object_id:source},state:'FRESH',ttl_ms:0,priority:2,z:2,anim,source_bars:[0],confidence:1,reason,digits:2} as DrawObject;
}
export function buildNotebookObjects(frame:ChartFrame|null,thesis:ThesisView|null,price:number|null):DrawObject[]{
  if(!frame||frame.chart_density!=='notebook')return [];
  const bars=frame.snapshot?.bars??(frame.update?[frame.update.bar]:[]);
  const last=bars.at(-1); if(!last)return [];
  const now=last.t_open_ms, margin=tfMs(last.tf)*20, out:DrawObject[]=[];
  const visible=bars.slice(-80);
  if(visible.length>=8){
    const hi=Math.max(...visible.map(bar=>bar.h));
    const lo=Math.min(...visible.map(bar=>bar.l));
    const mid=(hi+lo)/2;
    const start=visible[0].t_open_ms;
    const range=hi-lo;
    out.push(obj(`notebook:observed-range:${last.tf}:hi:${visible[0].t_open_ms}`,'notebook.range','PATH',[point(start,hi),point(now+margin,hi)],{label:formatNotebookText(`RANGE H  ${fmt.price(hi)}`),level:hi,weight:1.25},'Observed visible range high',`range:${last.tf}:hi`));
    out.push(obj(`notebook:observed-range:${last.tf}:lo:${visible[0].t_open_ms}`,'notebook.range','PATH',[point(start,lo),point(now+margin,lo)],{label:formatNotebookText(`RANGE L  ${fmt.price(lo)}`),level:lo,weight:1.25},'Observed visible range low',`range:${last.tf}:lo`));
    out.push(obj(`notebook:observed-range:${last.tf}:mid:${visible[0].t_open_ms}`,'notebook.range','PATH',[point(start,mid),point(now+margin*.72,mid)],{label:formatNotebookText(`MID  ${fmt.price(mid)}`),level:mid,dashed:true,opacity:.7},'Observed visible range midpoint',`range:${last.tf}:mid`));
    const atrBars=visible.slice(-14);
    const atr=atrBars.length?atrBars.reduce((sum,bar,index,arr)=>{const prev=index>0?arr[index-1].c:bar.o;return sum+Math.max(bar.h-bar.l,Math.abs(bar.h-prev),Math.abs(bar.l-prev));},0)/atrBars.length:NaN;
    const from=visible[Math.max(0,visible.length-48)];
    const move=last.c-from.c;
    out.push(obj(`notebook:observed-move:${last.tf}:${from.t_open_ms}:${last.t_open_ms}`,'notebook.leg','PATH',[point(from.t_open_ms,from.c),point(now,last.c)],{label:formatNotebookText(`${fmt.delta(move)}  ${Number.isFinite(atr)&&atr>0?fmt.one(Math.abs(move)/atr):'--'} ATR`),direction:move>=0?'BULLISH':'BEARISH',opacity:.9},'Recent observed move',`move:${last.tf}`));
    if(range>0){
      const oteLo=hi-range*.79, oteHi=hi-range*.618;
      out.push(obj(`notebook:observed-ote:${last.tf}:${visible[0].t_open_ms}`,'notebook.fib','PATH',[point(start,oteLo),point(now+margin*.72,oteLo)],{label:formatNotebookText(`OTE 0.79  ${fmt.price(oteLo)}`),level:oteLo,dashed:true,opacity:.65},'Observed range OTE lower band',`range:${last.tf}:ote`));
      out.push(obj(`notebook:observed-ote2:${last.tf}:${visible[0].t_open_ms}`,'notebook.fib','PATH',[point(start,oteHi),point(now+margin*.72,oteHi)],{label:formatNotebookText(`OTE 0.618  ${fmt.price(oteHi)}`),level:oteHi,dashed:true,opacity:.65},'Observed range OTE upper band',`range:${last.tf}:ote`));
    }
  }
  const st=frame.structure_state;
  if(st&&st.trend!=='UNDEFINED'){
    const bullish=st.trend==='BULLISH';
    const rawLo=bullish?st.protected_low:st.major_low, rawHi=bullish?st.major_high:st.protected_high;
    const lo=Number(rawLo), hi=Number(rawHi);
    const source=st.last_event?.id??'structure';
    if(Number.isFinite(lo)&&Number.isFinite(hi)&&hi>lo){
      const range=hi-lo;
      const atrBars=bars.slice(-14);
      const atr=atrBars.length?atrBars.reduce((sum,bar,index,arr)=>{const prev=index>0?arr[index-1].c:bar.o;return sum+Math.max(bar.h-bar.l,Math.abs(bar.h-prev),Math.abs(bar.l-prev));},0)/atrBars.length:NaN;
      for(const [name,ratio] of [['0.5 EQ',.5],['0.618',.618],['0.705',.705],['0.79',.79]] as const){
        const level=bullish?hi-range*ratio:lo+range*ratio;
        out.push(obj(`notebook:fib:${source}:${name}`, 'notebook.fib', 'PATH', [point(now,level),point(now+margin,level)], {label:formatNotebookText(`${name}  ${fmt.price(level)}`), level}, 'Fib from confirmed structure impulse', source));
      }
      out.push(obj(`notebook:leg:${source}`,'notebook.leg','PATH',[point(now-tfMs(last.tf)*18,bullish?lo:hi),point(now,bullish?hi:lo)],{label:formatNotebookText(`${fmt.delta(bullish?range:-range)}  ${Number.isFinite(atr)&&atr>0?fmt.one(range/atr):'--'} ATR`),direction:st.trend},'Current confirmed impulse leg',source));
    }
  }
  const alt=thesis?.alternative;
  if(price!=null&&alt?.trigger_level!=null){
    out.push(obj(`notebook:scenario:A:${thesis?.key??'na'}`,'notebook.scenario','PATH',[point(now,price),point(now+margin*.55,Number(alt.trigger_level))],{label:'A',direction:thesis?.bias==='BULLISH'?'BULLISH':'BEARISH'},'Thesis branch A',thesis?.key??'thesis'));
  }
  const inv=thesis?.invalidation?.level??alt?.invalidation_level;
  if(price!=null&&inv!=null){
    out.push(obj(`notebook:scenario:B:${thesis?.key??'na'}`,'notebook.scenario','PATH',[point(now,price),point(now+margin*.55,Number(inv))],{label:'B',direction:thesis?.bias==='BULLISH'?'BEARISH':'BULLISH'},'Thesis invalidation branch',thesis?.key??'thesis'));
  }
  if(price!=null){
    const base=Math.floor(price/50)*50;
    for(const rn of [base-50,base,base+50,base+100])out.push(obj(`notebook:rn:${rn}`,'notebook.round','PATH',[point(now-tfMs(last.tf)*60,rn),point(now+margin,rn)],{label:formatNotebookText(`RN ${fmt.axis(rn)}`),level:rn},'Gold round number',`rn:${rn}`));
  }
  return out;
}
export function bookNotes(book:Record<string,unknown>|undefined|null):string[]{
  if(!book||typeof book!=='object')return [];
  const card=Array.isArray(book.story_card)?book.story_card.map(String).filter(Boolean):[];
  return card.slice(0,4).map((line,index)=>formatNotebookText(`${index===0?'CONTEXT':index===1?'STORY':index===2?'WHY':'NEXT'}  ${line}`));
}

export function notebookNotes(thesis:ThesisView|null,worklog:WorkDecision[]=[]):string[]{
  const notes=worklog.slice(-7).map((entry,index)=>formatNotebookText(`${index+1}  ${fmt.time(entry.at_ms)} ${entry.label}`));
  if(thesis?.if_then)notes.push(formatNotebookText(`A/B  ${thesis.if_then}`));
  return notes.slice(-8);
}



