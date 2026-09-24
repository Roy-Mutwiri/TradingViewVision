import type {ISeriesPrimitive,IPrimitivePaneRenderer,SeriesAttachedParameter,Time,SeriesType,IChartApi,ISeriesApi,UTCTimestamp} from 'lightweight-charts';
import type {DrawObject} from '../net/protocol';
import {livingBudget} from '../living/budget';
import {defaultLiving,type LivingConfig} from '../living/types';
import {renderTrace} from '../living/trace';

/** Existing DrawObject zones painted above grid and below candles. */
export class FVGZones implements ISeriesPrimitive<Time> {
  constructor(private onFadeFrame:()=>void=()=>{}){}
  private chart?:IChartApi;
  private series?:ISeriesApi<SeriesType>;
  private request=()=>{};
  private objects:DrawObject[]=[];
  private discards=new Map<string,{object:DrawObject;at:number;decision:string}>();
  private expired=new Set<string>();
  private config=defaultLiving;
  private seen=new Set<string>();
  private opening=new Map<string,number>();
  private initialized=false;
  private raf=0;
  private focus:{x:number;y:number}|null=null;
  private focusFrom:{x:number;y:number}|null=null;
  private focusAt=0;
  private lastFocusMove=-Infinity;
  private referencePrice?:number;
  private sweepAt=-Infinity;
  private sessionAt=-Infinity;
  private poolSweeps=new Set<string>();
  private pauseAttention=false;
  private density:'clean'|'analyst'|'notebook'='notebook';
  setAttentionPaused(paused:boolean){this.pauseAttention=paused;} setDensity(density:'clean'|'analyst'|'notebook'){this.density=density;this.request();}
  get fadeCount(){return this.visibleObjects().filter(o=>o.text_args.lifecycle==='DISCARDED').length;}
  sessionScan(at:number){this.sessionAt=at;this.request();}
  cancelSessionScan(){this.sessionAt=-Infinity;}
  attached({chart,series,requestUpdate}:SeriesAttachedParameter<Time,SeriesType>){this.chart=chart;this.series=series;this.request=requestUpdate;}
  detached(){cancelAnimationFrame(this.raf);}
  setLiving(config:LivingConfig){this.config=config;if(!config.attention_enabled){cancelAnimationFrame(this.raf);this.raf=0;}this.request();}
  barClose(atMs:number){
    if(!this.config.reeval_sweep_enabled)return;
    const now=performance.now();
    if(livingBudget.admit([{id:`reeval:${atMs}`,kind:'sweep',duration:400,cancel:()=>{this.sweepAt=-Infinity;}}],now).length){this.sweepAt=now;this.request();}
  }
  update(objects:DrawObject[],referencePrice?:number){
    this.referencePrice=referencePrice;
    this.objects=objects.filter(o=>o.style.token==='zone.fvg'||o.style.token==='zone.ob'||o.style.token==='liquidity.pool'||o.style.token==='call.trade');
    for(const object of this.objects){
      if(object.text_args.lifecycle!=='DISCARDED')continue;
      const id=String(object.text_args.zone_id),decision=String(object.text_args.decision_id);
      if(!this.expired.has(decision)&&!this.discards.has(id)){
        this.discards.set(id,{object,at:performance.now(),decision});
        renderTrace('FADE',decision,{object_id:id,reason:object.text_args.discard_reason,duration:600,reason_chip:true,mandatory:true});
      }
    }
    const fresh=this.objects.filter(o=>!this.seen.has(String(o.text_args.zone_id??o.id)));
    for(const o of this.objects.filter(o=>o.style.token==='liquidity.pool'&&o.text_args.pool_state==='SWEPT')){
      const id=String(o.text_args.sweep_event_id);
      if(!this.poolSweeps.has(id)){
        this.poolSweeps.add(id);
        if(this.initialized&&livingBudget.admit([{id:`sweep:${id}`,kind:'promotion',duration:450,cancel:()=>this.opening.delete(String(o.text_args.zone_id))}],performance.now()).length)this.opening.set(String(o.text_args.zone_id),performance.now());
      }
    }
    if(this.initialized&&this.config.candidates_enabled){
      const at=performance.now();
      for(const event of livingBudget.admit(fresh.map(o=>({id:String(o.text_args.zone_id??o.id),kind:'promotion',duration:this.config.draw_on_ms,cancel:()=>this.opening.delete(String(o.text_args.zone_id??o.id))})),at))this.opening.set(event.id,at);
    }
    for(const o of this.objects)this.seen.add(String(o.text_args.zone_id??o.id));
    if(this.objects.length)this.initialized=true;this.request();
  }
  opacity(object:DrawObject){
    const discarded=this.discards.get(String(object.text_args.zone_id));
    const alpha=discarded?.45*Math.max(0,1-(performance.now()-discarded.at)/600):object.text_args.confirmed===false?.45:Number(object.text_args.opacity??1);
    return alpha*Number(object.text_args.overlay_opacity??1);
  }
  visibleObjects(){
    const now=performance.now();
    for(const [id,item] of this.discards)if(now-item.at>=600){this.expired.add(item.decision);this.discards.delete(id);}
    const current=this.objects.filter(o=>o.text_args.lifecycle!=='DISCARDED');
    current.push(...[...this.discards.values()].map(item=>item.object));
    const result:DrawObject[]=[];
    for(const tf of new Set(current.map(o=>`${String(o.text_args.tf)}:${o.style.token}`))){
      const group=current.filter(o=>`${String(o.text_args.tf)}:${o.style.token}`===tf);
      if(group[0]?.style.token==='liquidity.pool'){result.push(...group.filter(o=>o.text_args.lifecycle!=='DISCARDED').slice(0,6),...group.filter(o=>o.text_args.lifecycle==='DISCARDED'));continue;}
      const perTf=this.density==='notebook'?6:3;
      const candidates=group.filter(o=>o.text_args.confirmed===false).slice(-perTf);
      const confirmed=group.filter(o=>o.text_args.confirmed!==false);
      const capacity=Math.max(0,perTf-candidates.length);
      result.push(...(capacity?confirmed.slice(-capacity):[]),...candidates);
    }
    // Keep overlays within the latest density ceiling: two OBs in the whole
    // plot, one current FVG. Canonical objects and their history remain intact.
    // Mandatory removal fades are never evicted by presentation limits.
    const fades=result.filter(o=>o.text_args.lifecycle==='DISCARDED');
    const regular=result.filter(o=>o.text_args.lifecycle!=='DISCARDED');
    const newest=(a:DrawObject,b:DrawObject)=>Number(b.text_args.confirmed===false)-Number(a.text_args.confirmed===false)||(b.points[1]?.t_ms??0)-(a.points[1]?.t_ms??0);
    const obs=regular.filter(o=>o.style.token==='zone.ob').sort(newest);
    const local=obs.filter(o=>!o.text_args.htf_overlay),overlays=obs.filter(o=>o.text_args.htf_overlay);
    const maxZones=this.density==='notebook'?6:2;
    const selected=overlays.length?[...local.slice(0,Math.max(1,Math.floor(maxZones/2))),...overlays.slice(0,Math.max(1,maxZones-Math.min(Math.max(1,Math.floor(maxZones/2)),local.length)))]:local.slice(0,maxZones);
    return [...regular.filter(o=>o.style.token==='liquidity.pool'),...selected,...regular.filter(o=>o.style.token==='zone.fvg').sort(newest).slice(0,1),...regular.filter(o=>o.style.token==='call.trade'),...fades];
  }
  private animate(){if(this.raf)return;this.raf=requestAnimationFrame(()=>{this.raf=0;this.request();if(this.discards.size)this.onFadeFrame();});}
  private renderer:IPrimitivePaneRenderer={draw:()=>{},drawBackground:target=>{
    target.useMediaCoordinateSpace(({context:ctx,mediaSize:{width,height}})=>{
      const chart=this.chart,series=this.series;if(!chart||!series)return;
      const range=chart.timeScale().getVisibleRange();if(!range||typeof range.from!=='number'||typeof range.to!=='number')return;
      ctx.save();ctx.beginPath();ctx.rect(0,0,width,height);ctx.clip();
      const now=performance.now();let focusTarget:{x:number;y:number;price:number}|null=null;
      for(const obj of this.visibleObjects()){
        const a=obj.text_args;
        const start=obj.points[0].t_ms/1000,end=Number(a.end_ms)/1000;
        if(start>range.to||end<range.from)continue;
        const x1=chart.timeScale().timeToCoordinate(Math.max(start,range.from) as UTCTimestamp)??0;
        const x2=width;
        if(obj.style.token==='call.trade'){
          const entryLo=series.priceToCoordinate(Number(a.entry_lo)),entryHi=series.priceToCoordinate(Number(a.entry_hi));
          const sl=series.priceToCoordinate(Number(a.stop)),tp1=series.priceToCoordinate(Number(a.tp1)),tp2=a.tp2==null?null:series.priceToCoordinate(Number(a.tp2));
          if(entryLo===null||entryHi===null||sl===null||tp1===null)continue;
          const bullish=a.direction==='BULLISH',rgb=a.call_state==='WIN'?'83,212,182':a.call_state==='LOSS'?'241,139,145':bullish?'83,212,182':'241,139,145';
          ctx.save();ctx.fillStyle=`rgba(${rgb},.16)`;ctx.strokeStyle=`rgba(${rgb},.8)`;ctx.fillRect(x1,Math.min(entryLo,entryHi),x2-x1,Math.abs(entryHi-entryLo));ctx.strokeRect(x1,Math.min(entryLo,entryHi),x2-x1,Math.abs(entryHi-entryLo));
          ctx.strokeStyle='#f18b91';ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(x1,sl);ctx.lineTo(x2,sl);ctx.stroke();
          ctx.strokeStyle='#53d4b6';ctx.beginPath();ctx.moveTo(x1,tp1);ctx.lineTo(x2,tp1);ctx.stroke();
          if(tp2!==null){ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(x1,tp2);ctx.lineTo(x2,tp2);ctx.stroke();}
          ctx.restore();continue;
        }
        if(obj.style.token==='liquidity.pool'){
          const py=series.priceToCoordinate(Number(a.ce));if(py===null)continue;
          ctx.save();ctx.globalAlpha=this.opacity(obj);ctx.strokeStyle='#dec38c';ctx.lineWidth=a.confirmed===false?1.5:1;ctx.setLineDash(a.pool_state==='SWEPT'||a.confirmed===false?[4,4]:[]);
          ctx.beginPath();ctx.moveTo(x1,py);ctx.lineTo(x2,py);ctx.stroke();ctx.setLineDash([]);
          for(const t of Array.isArray(a.touch_times)?a.touch_times:[]){const px=chart.timeScale().timeToCoordinate((Number(t)-Number(t)%({M5:300000,M15:900000,H1:3600000,H4:14400000}[String(a.tf)]??900000))/1000 as UTCTimestamp);if(px!==null){ctx.beginPath();ctx.moveTo(px,py-3);ctx.lineTo(px,py+3);ctx.stroke();}}
          const born=this.opening.get(String(a.zone_id)),age=born===undefined?Infinity:now-born;
          if(age<450){ctx.globalAlpha=.2*(1-age/450);ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(x1,py);ctx.lineTo(x2,py);ctx.stroke();this.animate();}else if(born!==undefined)this.opening.delete(String(a.zone_id));
          ctx.restore();if(a.lifecycle==='DISCARDED')this.animate();continue;
        }
        const lo=series.priceToCoordinate(Number(a.unfilled_lo)),hi=series.priceToCoordinate(Number(a.unfilled_hi)),ce=series.priceToCoordinate(Number(a.ce));
        if(lo===null||hi===null||ce===null)continue;
        const top=Math.min(lo,hi),bottom=Math.max(lo,hi);
        const born=this.opening.get(String(a.zone_id??obj.id));
        const progress=born===undefined?1:Math.min(1,(now-born)/Math.max(1,Math.min(800,this.config.draw_on_ms)));
        const span=Math.max(1,(x2-x1)*(1-(1-progress)**3));
        if(progress<1)this.animate();else if(born!==undefined)this.opening.delete(String(a.zone_id??obj.id));
        const distance=this.referencePrice===undefined?Infinity:Math.abs(Number(a.ce)-this.referencePrice);
        if(!focusTarget||distance<focusTarget.price)focusTarget={x:x2,y:ce,price:distance};
        const color=a.direction==='BULLISH'?'83,212,182':'241,139,145';
        ctx.globalAlpha=this.opacity(obj);
        const ob=obj.style.token==='zone.ob';
        ctx.setLineDash(a.confirmed===false||a.ob_state==='TOUCHED'?[5,4]:[]);
        const alpha=ob?.11:a.weakened?.035:.085;
        const gradient=ctx.createLinearGradient(0,top,0,Math.max(top+1,bottom));
        gradient.addColorStop(0,`rgba(${color},${alpha})`);gradient.addColorStop(1,`rgba(${color},${alpha*.3})`);
        ctx.fillStyle=gradient;ctx.fillRect(x1,top,span,Math.max(1,bottom-top));
        ctx.strokeStyle=`rgba(${color},${a.weakened?.18:.35})`;ctx.lineWidth=ob&&a.validation_kind==='CHoCH'?2:1;
        ctx.strokeRect(x1+.5,top+.5,span,Math.max(1,bottom-top));
        if(ob&&a.ob_state==='BREAKER'){
          ctx.save();ctx.beginPath();ctx.rect(x1,top,span,Math.max(1,bottom-top));ctx.clip();ctx.setLineDash([]);
          for(let hx=x1-(bottom-top);hx<x2;hx+=9){ctx.beginPath();ctx.moveTo(hx,bottom);ctx.lineTo(hx+bottom-top,top);ctx.stroke();}ctx.restore();
        }
        if(!ob){ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x1,ce);ctx.lineTo(x2,ce);ctx.stroke();}ctx.setLineDash([]);
        ctx.globalAlpha=1;
        if(a.lifecycle==='DISCARDED')this.animate();
      }
      if(this.config.attention_enabled&&!this.pauseAttention&&focusTarget){
        const target={x:focusTarget.x,y:focusTarget.y};
        if(!this.focus){this.focus=target;this.focusFrom=target;}
        else if(Math.hypot(target.x-this.focus.x,target.y-this.focus.y)>8&&now-this.lastFocusMove>=2000){
          const accepted=livingBudget.admit([{id:`attention:${Math.floor(now)}`,kind:'attention',duration:this.config.attention_move_ms}],now);
          if(accepted.length){this.focusFrom=this.focus;this.focus=target;this.focusAt=now;this.lastFocusMove=now;}
        }
        const from=this.focusFrom??this.focus,p=Math.min(1,(now-this.focusAt)/Math.max(1,Math.min(800,this.config.attention_move_ms))),ease=1-(1-p)**3;
        const x=from.x+(this.focus.x-from.x)*ease,y=from.y+(this.focus.y-from.y)*ease;
        const glow=ctx.createRadialGradient(x,y,0,x,y,40);
        glow.addColorStop(0,`rgba(200,171,112,${.035+.015*(1+Math.sin(now/1800))/2})`);glow.addColorStop(1,'rgba(200,171,112,0)');
        ctx.fillStyle=glow;ctx.fillRect(x-40,y-40,80,80);this.animate();
      }
      const sweep=(now-this.sweepAt)/400;
      if(this.config.reeval_sweep_enabled&&sweep>=0&&sweep<1){
        const x=width*sweep,shimmer=ctx.createLinearGradient(x-22,0,x+22,0);
        shimmer.addColorStop(0,'rgba(200,171,112,0)');shimmer.addColorStop(.5,'rgba(200,171,112,.025)');shimmer.addColorStop(1,'rgba(200,171,112,0)');
        ctx.fillStyle=shimmer;ctx.fillRect(x-22,0,44,height);this.animate();
      }
      const session=(now-this.sessionAt)/1200;
      if(this.config.session_scan_enabled&&session>=0&&session<1){
        const x=(width+160)*session-80,band=ctx.createLinearGradient(x-80,0,x+80,0);
        band.addColorStop(0,'rgba(255,255,255,0)');band.addColorStop(.5,'rgba(255,255,255,.08)');band.addColorStop(1,'rgba(255,255,255,0)');
        ctx.fillStyle=band;ctx.fillRect(x-80,0,160,height);this.animate();
      }
      ctx.restore();
    });
  }};
  private views=[{zOrder:()=> 'normal' as const,renderer:()=>this.renderer}];
  paneViews(){return this.views;}
}

