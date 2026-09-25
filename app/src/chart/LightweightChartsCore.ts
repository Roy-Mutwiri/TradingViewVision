import {createChart, CandlestickSeries, ColorType, type IChartApi, type ISeriesApi, type UTCTimestamp, type Time} from 'lightweight-charts';
import type {Bar, DrawObject} from '../net/protocol';
import type {SessionClosure} from '../net/chart';
import type {Decision} from '../net/chart';
import {MeasurementGesture} from '../living/Measurement';
import {CameraMotion} from '../living/Camera';
import {SessionBoundaries} from '../living/SessionScan';
import {livingBudget} from '../living/budget';
import {renderTrace} from '../living/trace';
import {defaultLiving} from '../living/types';
import type {ChartDensity, ChartEvents, ChartOpts, IChartCore, Timeframe} from './IChartCore';
import {axisPrice, CHART_FONT, labelLines, labelPriority, measurementColumn, overlaps, placeLabels, type LabelCandidate, type Rect} from './labels';
import {Watermark} from './Watermark';
import {FVGZones} from './FVGZones';
import {configureBudget} from '../living/budget';
import type {LivingConfig} from '../living/types';
import {defaultStream,type StreamConfig} from '../stream/types';
import {fmt} from '../fmt';

const CANDLE_UP='#00E0A4';
const CANDLE_DOWN='#FF4F64';

/** The ONLY contract milliseconds / vendor seconds conversion point. */
export const chartTime = {
  toVendor(ms: number): UTCTimestamp {
    if (!Number.isSafeInteger(ms) || ms < 0) throw new Error('Expected integer UTC epoch milliseconds');
    return ms / 1000 as UTCTimestamp;
  },
  fromVendor(time: Time): number {
    if (typeof time !== 'number') throw new Error('Chart requires numeric UTC time');
    return Math.round(time * 1000);
  },
};
export class LightweightChartsCore implements IChartCore {
  constructor(private factory: typeof createChart = createChart) {}
  private chart!: IChartApi;
  private series!: ISeriesApi<'Candlestick'>;
  private observer?: ResizeObserver;
  private bars = new Map<number, Bar>();
  private closures: SessionClosure[] = [];
  private listeners = new Map<string, Set<(v: any)=>void>>();
  private canvas!: HTMLCanvasElement;
  private el!: HTMLElement;
  private theme: 'dark'|'light' = 'dark';
  private visibleBars = 120;
  private raf = 0;
  private lastClose = new Set<number>();
  private objects: DrawObject[] = [];
  private allObjects: DrawObject[] = [];
  private language = 'en';
  private colors = new Map<number,string>();
  private reasonExpiry=new Map<string,number>();
  private reasonTimer=0;
  private watermark=new Watermark(defaultStream);
  private fvgZones=new FVGZones(()=>this.shade());
  private living=defaultLiving;
  private measurement=new MeasurementGesture();
  private sessions=new SessionBoundaries();
  private sessionMotion?:{name:string;id:string;at:number;chipAnimated?:boolean};
  private camera=new CameraMotion();
  private cameraRaf=0;
  private cameraCanvases:HTMLCanvasElement[]=[];
  private cameraState={x:0,scaleY:1,paused:false};
  private cameraPaused=false;
  private attentionPaused=false;
  private promoted=new Set<string>();
  private structureSeen=new Set<string>();
  private structureOpening=new Map<string,number>();
  private density:ChartDensity='notebook';
  private drawSignature='';
  async mount(el: HTMLElement, opts: ChartOpts) {
    this.el=el; this.theme=opts.theme; this.visibleBars=opts.visibleBars??120; this.density=opts.density??'notebook';
    this.chart=this.factory(el,{autoSize:true, layout:{attributionLogo:true},timeScale:{timeVisible:true,secondsVisible:false,rightOffset:this.density==='notebook'?20:8,barSpacing:8},rightPriceScale:{borderVisible:false},crosshair:{mode:0,vertLine:{visible:false,labelVisible:false},horzLine:{visible:false,labelVisible:false}}});
    this.series=this.chart.addSeries(CandlestickSeries,{upColor:CANDLE_UP,downColor:CANDLE_DOWN,wickUpColor:CANDLE_UP,wickDownColor:CANDLE_DOWN,borderUpColor:CANDLE_UP,borderDownColor:CANDLE_DOWN,borderVisible:true,priceFormat:{type:'custom',formatter:axisPrice,minMove:.001}});
    (this.series as any).applyOptions({autoscaleInfoProvider:(base:any)=>{
      const info=base();
      const range=this.visibleDrawPriceRange();
      if(!range)return info;
      const current=info?.priceRange;
      const min=Math.min(Number(current?.minValue??range.min),range.min);
      const max=Math.max(Number(current?.maxValue??range.max),range.max);
      const pad=Math.max((max-min)*.05,.5);
      return {priceRange:{minValue:min-pad,maxValue:max+pad}};
    }});
    this.series.attachPrimitive(this.watermark);
    this.series.attachPrimitive(this.fvgZones);
    this.canvas=document.createElement('canvas'); this.canvas.className='session-shading'; el.appendChild(this.canvas);
    this.setTheme(opts.theme);
    this.chart.timeScale().subscribeVisibleTimeRangeChange(()=> {this.emit('range',this.visibleRange()); this.shade();});
    this.chart.timeScale().subscribeVisibleLogicalRangeChange(()=>this.shade());
    this.chart.subscribeCrosshairMove(p=> {
      const t=p.time===undefined?null:chartTime.fromVendor(p.time);
      this.emit('crosshair',{t_ms:t,bar:t===null?null:this.bars.get(t)??null});
    });
    this.observer=new ResizeObserver(()=>{this.emit('resize',{width:el.clientWidth,height:el.clientHeight});this.shade();});
    this.observer.observe(el);
    this.cameraCanvases=Array.from(el.querySelectorAll('canvas'));
    if(typeof window!=='undefined')Object.assign(window,{oracleCameraState:()=>({...this.cameraState,visible_range:this.visibleRange()}),oracleChartAudit:()=>{const spacing=this.chart.timeScale().options().barSpacing,last=[...this.bars.values()].at(-1),lastX=last?this.timeToX(last.t_open_ms):null,plotWidth=this.chart.timeScale().width(),logicalRange=this.chart.timeScale().getVisibleLogicalRange?.();return {logicalRange,rightOffset:this.chart.timeScale().options().rightOffset,barSpacing:spacing,lastCandleX:lastX,plotWidth,rightGapPx:lastX==null?null:plotWidth-lastX,expectedRightGapPx:(this.density==='notebook'?20:8)*spacing,visible_range:this.visibleRange(),priceScale:this.visibleDrawPriceRange(),candleScale:this.candleScaleBand()};}});
  }
  destroy() {cancelAnimationFrame(this.cameraRaf);cancelAnimationFrame(this.raf);clearTimeout(this.reasonTimer);this.observer?.disconnect();this.chart?.remove();this.canvas?.remove();this.listeners.clear();}
  async setSymbol(symbol:string, _tf:Timeframe) {if(symbol!=='XAUUSD')throw new Error('Only canonical XAUUSD is supported');this.bars.clear();this.lastClose.clear();this.objects=[];this.allObjects=[];this.colors.clear();this.drawSignature='';this.series.setData([]);}
  private candle(b:Bar) {const token=this.colors.get(b.t_open_ms);const color=token==='utbot.buy'?CANDLE_UP:token==='utbot.sell'?CANDLE_DOWN:undefined;return {time:chartTime.toVendor(b.t_open_ms),open:b.o,high:b.h,low:b.l,close:b.c,...(color?{color,wickColor:color,borderColor:color}: {})};}
  applyBars(bars:Bar[]) {
    for(let i=1;i<bars.length;i++)if(bars[i].t_open_ms<=bars[i-1].t_open_ms)throw new Error('Bars must be ordered and unique');
    this.bars=new Map(bars.map(b=>[b.t_open_ms,b]));
    this.lastClose=new Set(bars.filter(b=>b.complete).map(b=>b.t_open_ms));
    this.resetData();
    this.series.applyOptions({priceFormat:{type:'custom',formatter:axisPrice,minMove:10**-(bars.at(-1)?.digits??2)}});
    this.chart.timeScale().applyOptions({rightOffset:this.density==='notebook'?20:8,barSpacing:8});
    this.chart.timeScale().setVisibleLogicalRange({from:Math.max(0,bars.length-this.visibleBars),to:bars.length+(this.density==='notebook'?20:8)});
    this.chart.timeScale().applyOptions({rightOffset:this.density==='notebook'?20:8,barSpacing:8});
    this.shade();
  }
  private resetData() {
    const data=new Map<number,ReturnType<LightweightChartsCore['candle']>|{time:UTCTimestamp}>();
    for(const b of this.bars.values())data.set(b.t_open_ms,this.candle(b));
    const times=[...this.bars.keys()];const lo=Math.min(...times),hi=Math.max(...times);
    for(const c of this.closures)for(const t of [c.start_ms,c.end_ms-60000])if(t>=lo&&t<=hi&&!data.has(t))data.set(t,{time:chartTime.toVendor(t)});
    this.series.setData([...data.entries()].sort((a,b)=>a[0]-b[0]).map(([,v])=>v));
  }
  updateBar(bar:Bar) {
    const old=this.bars.get(bar.t_open_ms);
    const latest=Math.max(...this.bars.keys());
    this.bars.set(bar.t_open_ms,bar);
    this.series.update(this.candle(bar),bar.t_open_ms<latest);
    if(bar.complete&&!this.lastClose.has(bar.t_open_ms)){this.lastClose.add(bar.t_open_ms);this.fvgZones.barClose(bar.t_open_ms);this.emit('barclose',bar);}
    if(!old&&this.bars.size>20000){const times=[...this.bars.keys()].sort((a,b)=>a-b);for(const t of times.slice(0,this.bars.size-20000)){this.bars.delete(t);this.lastClose.delete(t);}this.resetData();}
    this.shade();
  }
  priceToY(p:number){return this.series.priceToCoordinate(p);}
  timeToX(t:number){return this.chart.timeScale().timeToCoordinate(chartTime.toVendor(t));}
  private visibleScaleBars(){
    const ordered=[...this.bars.values()].sort((a,b)=>a.t_open_ms-b.t_open_ms);
    if(!ordered.length)return [] as Bar[];
    const logical=this.chart.timeScale().getVisibleLogicalRange?.();
    if(logical){
      const from=Math.max(0,Math.floor(Number(logical.from)));
      const to=Math.min(ordered.length-1,Math.ceil(Number(logical.to)));
      if(to>=from)return ordered.slice(from,to+1);
    }
    const r=this.visibleRange();
    return r?ordered.filter(bar=>bar.t_open_ms>=r.from&&bar.t_open_ms<=r.to):ordered.slice(-this.visibleBars);
  }
  private candleScaleBand(){
    const visible=this.visibleScaleBars();
    if(!visible.length)return null;
    const lows=visible.map(bar=>bar.l),highs=visible.map(bar=>bar.h);
    const trueRanges=visible.slice(-14).map((bar,index,arr)=>{
      const previous=index>0?arr[index-1].c:bar.o;
      return Math.max(bar.h-bar.l,Math.abs(bar.h-previous),Math.abs(bar.l-previous));
    });
    const min=Math.min(...lows),max=Math.max(...highs),span=Math.max(max-min,.01);
    const atr=trueRanges.length?trueRanges.reduce((a,b)=>a+b,0)/trueRanges.length:span*.05;
    const pad=Math.max(2*atr,span*.05);
    return {min,max,pad,lo:min-pad,hi:max+pad,visibleBars:visible.length,left:visible[0]?.t_open_ms,right:visible.at(-1)?.t_open_ms};
  }
  private visibleDrawPriceRange(){
    const band=this.candleScaleBand();
    return band?{min:band.lo,max:band.hi}:null;
  }
  private clipDrawPrice(price:number){const band=this.candleScaleBand();return band?Math.max(band.lo,Math.min(band.hi,price)):price;}
  visibleRange(){const r=this.chart.timeScale().getVisibleRange();return r?{from:chartTime.fromVendor(r.from),to:chartTime.fromVendor(r.to)}:null;}
  setVisibleRange(from:number,to:number){this.chart.timeScale().setVisibleRange({from:chartTime.toVendor(from),to:chartTime.toVendor(to)});}
  setDensity(density:ChartDensity){
    if(density===this.density)return;
    this.density=density;
    this.fvgZones.setDensity(density);
    this.chart?.timeScale().applyOptions({rightOffset:density==='notebook'?20:8});
    this.shade();
  }
  setTheme(theme:'dark'|'light') {this.theme=theme;this.chart.applyOptions({layout:{background:{type:ColorType.Solid,color:theme==='dark'?'#07172a':'#f5f6fa'},fontSize:14,fontFamily:CHART_FONT,textColor:theme==='dark'?'#dbe7f8':'#566173'},grid:{vertLines:{color:theme==='dark'?'#16304a':'#e5e8ef'},horzLines:{color:theme==='dark'?'#16304a':'#e5e8ef'}}});this.shade();}
  setSessions(closures:SessionClosure[]) {this.closures=closures;if(this.bars.size)this.resetData();this.shade();}
  setStream(config:StreamConfig){this.watermark.update(config);}
  setLiving(config:LivingConfig){
    this.living=config;configureBudget(config.visual_events_per_minute,config.concurrent_animations);this.fvgZones.setLiving(config);
    if(!config.measurement_gesture.enabled)this.measurement.clear();
    this.camera.configure({...config.camera,enabled:config.camera.enabled&&config.camera_drift_enabled});
    cancelAnimationFrame(this.cameraRaf);this.cameraRaf=0;
    if(config.camera.enabled&&config.camera_drift_enabled)this.cameraLoop();
    else {for(const canvas of this.cameraCanvases)canvas.style.transform='';this.cameraState={x:0,scaleY:1,paused:false};}
    renderTrace('LIVING_CONFIG','config',{attention_enabled:config.attention_enabled,camera_enabled:config.camera.enabled&&config.camera_drift_enabled,budget_events_per_min:config.visual_events_per_minute,budget_concurrent:config.concurrent_animations});
    this.reserveMotion(performance.now());
  }
  setDecisions(decisions:Decision[]){
    const now=performance.now();this.reserveMotion(now);
    this.measurement.consider(decisions,now,this.living.measurement_gesture.enabled,this.living.measurement_min_interval_s*1000);
    for(const d of decisions){
      const id=`${d.tf}:${d.seq}:${d.object_id}:${d.action}`;
      if(d.action==='PROMOTE'&&!this.promoted.has(id)){
        this.promoted.add(id);
        if(livingBudget.admit([{id:`camera:${id}`,kind:'drift',duration:700,cancel:()=>this.camera.cancelSnap()}],now).length)this.camera.recentre(now);
      }
    }
    this.shade();
  }
  private reserveMotion(now:number){
    const fades=this.fvgZones.fadeCount+(this.measurement.isFading(now)?1:0);
    const cameraPaused=fades>0,attentionPaused=fades>=2;
    if(cameraPaused!==this.cameraPaused){this.cameraPaused=cameraPaused;renderTrace(cameraPaused?'CAMERA_PAUSED':'CAMERA_RESUMED','camera');}
    if(attentionPaused!==this.attentionPaused){this.attentionPaused=attentionPaused;renderTrace(attentionPaused?'ATTENTION_PAUSED':'ATTENTION_RESUMED','attention');}
    this.fvgZones.setAttentionPaused(attentionPaused);
    const camera=this.living.camera.enabled&&this.living.camera_drift_enabled&&!cameraPaused?1:0;
    const attention=this.living.attention_enabled&&!attentionPaused?1:0;
    livingBudget.reserve(fades+camera+attention,now);
    return cameraPaused;
  }
  private cameraLoop(){
    this.cameraRaf=requestAnimationFrame(()=>{
      this.cameraRaf=0;const now=performance.now(),paused=this.reserveMotion(now),range=this.visibleRange();
      const width=this.chart.timeScale().width(),height=this.el.clientHeight-this.chart.timeScale().height(),spacing=this.chart.timeScale().options().barSpacing;
      let right=0;
      if(range)for(const bar of this.bars.values())if(bar.t_open_ms>=range.from&&bar.t_open_ms<=range.to){const x=this.timeToX(bar.t_open_ms);if(x!==null)right=Math.max(right,x+spacing*.45);}
      // Protect both the last visible candle and the permanent corner brand.
      this.cameraState=this.camera.step(now,Math.max(0,Math.min(14,width-right-2)),paused);
      const sizes=this.cameraCanvases.map(canvas=>({canvas,wide:canvas===this.canvas||canvas.clientWidth>this.el.clientWidth/2,pane:canvas===this.canvas||canvas.clientHeight>40}));
      for(const {canvas,wide,pane} of sizes){canvas.style.transformOrigin=`0px ${height/2}px`;canvas.style.transform=`translateX(${wide?this.cameraState.x:0}px) scaleY(${pane?this.cameraState.scaleY:1})`;}
      this.cameraLoop();
    });
  }
  sessionAt(now:number,connected:boolean){
    const boundary=this.sessions.observe(now,connected);
    if(!boundary||!this.living.session_scan_enabled)return;
    const at=performance.now();
    if(!livingBudget.admit([{id:boundary.id,kind:'session',duration:1200,cancel:()=>this.fvgZones.cancelSessionScan()}],at).length)return;
    this.sessionMotion={...boundary,at};this.fvgZones.sessionScan(at);
    renderTrace('SESSION_SCAN',boundary.id,{duration:1200,name:boundary.name,boundary_ms:boundary.at,chip_hold_ms:4000});this.shade();
  }
  applyDrawObjects(objects:DrawObject[],language='en'){
    const signature=JSON.stringify(objects.map(object=>[
      object.id??object.text_key,
      object.style.token,
      object.state,
      object.points,
      object.text_args,
    ]));
    if(signature===this.drawSignature&&language===this.language)return;
    this.drawSignature=signature;
    this.allObjects=objects;
    const at=performance.now(),lastOpen=[...this.bars.values()].at(-1)?.t_open_ms??Infinity;
    for(const object of objects.filter(o=>o.style.token==='structure.event')){
      const id=String(object.text_args.event_id);
      if(this.living.candidates_enabled&&!this.structureSeen.has(id)&&Number(object.text_args.confirmed_at_ms)>=lastOpen){
        if(livingBudget.admit([{id:`structure:${id}`,kind:'structure',duration:this.living.draw_on_ms,cancel:()=>this.structureOpening.delete(id)}],at).length)this.structureOpening.set(id,at);
      }
      this.structureSeen.add(id);
    }
    this.fvgZones.update(objects,[...this.bars.values()].at(-1)?.c);
    const keepStructure=new Set(objects.filter(o=>o.style.token==='structure.event').sort((a,b)=>Number(b.points?.at(-1)?.t_ms??0)-Number(a.points?.at(-1)?.t_ms??0)).slice(0,3).map(o=>o.id??o.text_key));
    this.objects=objects.filter(o=>o.style.token!=='structure.event'||keepStructure.has(o.id??o.text_key));this.language=language;clearTimeout(this.reasonTimer);
    const strips=objects.filter(o=>o.style.token==='analysis.reason');
    for(const id of this.reasonExpiry.keys())if(!strips.some(o=>(o.id??o.text_key)===id))this.reasonExpiry.delete(id);
    for(const obj of strips){const id=obj.id??obj.text_key,deadline=performance.now()+Math.min(obj.ttl_ms??20000,20000);this.reasonExpiry.set(id,Math.min(this.reasonExpiry.get(id)??deadline,deadline));}
    this.scheduleReasonTimer();
    this.shade();
  }
  private scheduleReasonTimer(){
    clearTimeout(this.reasonTimer);
    const remaining=[...this.reasonExpiry.values()].map(t=>t-performance.now()).filter(t=>t>0);
    if(remaining.length)this.reasonTimer=window.setTimeout(()=>this.shade(),Math.min(...remaining)+1);
  }
  setBarColors(colors:{t_ms:number;token:string}[]){const next=new Map(colors.map(c=>[c.t_ms,c.token]));if(next.size===this.colors.size&&[...next].every(([t,c])=>this.colors.get(t)===c))return;this.colors=next;if(this.bars.size)this.resetData();}
  private shade() {
    if(this.raf)return;
    this.raf=requestAnimationFrame(()=> {
      this.raf=0; const dpr=devicePixelRatio;const w=this.el.clientWidth,h=this.el.clientHeight;
      this.reserveMotion(performance.now());
      const pixelWidth=Math.max(1,Math.floor(w*dpr)),pixelHeight=Math.max(1,Math.floor(h*dpr));
      if(this.canvas.width!==pixelWidth||this.canvas.height!==pixelHeight){
        this.canvas.width=pixelWidth;this.canvas.height=pixelHeight;this.canvas.style.width=`${w}px`;this.canvas.style.height=`${h}px`;
      }
      const ctx=this.canvas.getContext('2d')!;
      ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.clearRect(0,0,w,h);
      ctx.fillStyle=this.theme==='dark'?'rgba(175,151,90,.12)':'rgba(147,116,53,.12)';
      const r=this.visibleRange();if(!r)return;
      for(const c of this.closures){if(c.end_ms<r.from||c.start_ms>r.to)continue;const x1=this.timeToX(c.start_ms)??0;const x2=this.timeToX(c.end_ms-60000)??w;ctx.fillRect(x1,0,Math.max(2,x2-x1),h-28);}
      const inRange=[...this.bars.values()].filter(b=>b.t_open_ms>=r.from&&b.t_open_ms<=r.to);
      if(inRange.length&&w/inRange.length>=2){
        ctx.save();ctx.lineWidth=1.3;
        for(const bar of inRange){const x=this.timeToX(bar.t_open_ms),hi=this.priceToY(bar.h),lo=this.priceToY(bar.l);if(x===null||hi===null||lo===null)continue;ctx.strokeStyle=bar.c>=bar.o?'#53d4b6':'#f18b91';ctx.beginPath();ctx.moveTo(x,hi);ctx.lineTo(x,lo);ctx.stroke();}
        ctx.restore();
      }
      const plotWidth=this.chart.timeScale().width(),plotHeight=h-this.chart.timeScale().height();
      const spacing=this.chart.timeScale().options().barSpacing;
      const bodies:Rect[]=[];
      for(const bar of inRange){
        const x=this.timeToX(bar.t_open_ms),open=this.priceToY(bar.o),close=this.priceToY(bar.c);
        if(x===null||open===null||close===null)continue;
        const width=Math.max(1,spacing*.9);
        bodies.push({x:x-width/2,y:Math.min(open,close),width,height:Math.max(1,Math.abs(open-close))});
      }
      let candidates:LabelCandidate[]=[];
      const levelLabelSeen=new Set<string>();
      const gesture=this.measurement.object(performance.now(),[...this.bars.values()].at(-1)?.t_open_ms??0);
      const session=this.sessionMotion,sessionAge=session?performance.now()-session.at:Infinity;
      if(session&&sessionAge>=1200&&sessionAge<5200&&session.chipAnimated===undefined)session.chipAnimated=!!livingBudget.admit([{id:`${session.id}:chip`,kind:'draw',duration:450,cancel:()=>{session.chipAnimated=false;}}],performance.now()).length;
      const sessionChip:DrawObject|null=session&&this.living.session_scan_enabled&&sessionAge>=1200&&sessionAge<5200?{id:session.id,layer:'L3',shape:'LABEL',points:[{t_ms:r.to,price:0}],style:{token:'living.session'},text_key:session.id,text_args:{name:session.name,corner:true,opacity:session.chipAnimated?Math.min(1,(sessionAge-1200)/450):1},reason:'Session calendar boundary',confidence:1,priority:3,z:1,state:'FRESH',ttl_ms:4000,anim:{in_:'none',loop:null},source_bars:[Math.max(0,this.bars.size-1)]}:null;
      const renderedObjects=[...this.objects.filter(o=>o.style.token!=='zone.fvg'&&o.style.token!=='zone.ob'&&o.style.token!=='liquidity.pool'),...this.fvgZones.visibleObjects(),...(gesture?[gesture]:[]),...(sessionChip?[sessionChip]:[])];
      for(const obj of renderedObjects){
        if(obj.layer!=='L2'&&obj.layer!=='L3')continue;
        const zone=obj.style.token==='zone.fvg'||obj.style.token==='zone.ob';
        const protectedLevel=obj.style.token==='structure.protected';
        const liquidityLevel=obj.style.token==='liquidity.pool';
        const callLevel=obj.style.token==='call.level';
        const path=protectedLevel||liquidityLevel||callLevel?[obj.points[0],{t_ms:Math.min(Number(obj.text_args.end_ms),r.to),price:obj.points[0].price}]:obj.points;
        const original=obj.text_args.label_at_end===true?path.at(-1):path[0];
        if(zone&&original&&(original.t_ms>r.to||Number(obj.text_args.end_ms)<r.from))continue;
        const first=zone&&original?{t_ms:Math.min(Number(obj.text_args.end_ms),r.to),price:Number(obj.text_args.unfilled_hi)}:original;
        if(!first||first.t_ms<r.from||first.t_ms>r.to)continue;
        const corner=obj.text_args.corner===true;
        const baseX=corner?65:this.timeToX(first.t_ms),y=corner?46:this.priceToY(first.price);if(baseX===null||y===null)continue;
        const measure=obj.style.token==='living.measurement';
        const measureYs=measure?obj.points.flatMap(p=>{const value=this.priceToY(p.price);return value===null?[]:[Number(value)];}):[];
        ctx.font=`700 13px ${CHART_FONT}`;
        const measureWidth=measure?Math.max(...labelLines(obj).map(line=>ctx.measureText(line).width))+16:0;
        const x=measure?measurementColumn(baseX+40,measureYs,bodies,plotWidth,measureWidth):baseX;
        if(obj.shape==='PATH'){
          ctx.save();ctx.globalAlpha=Number(obj.text_args.opacity??1);ctx.strokeStyle='#bfa66e';ctx.lineWidth=Number(obj.text_args.weight??1);ctx.setLineDash(obj.text_args.dashed?[4,4]:[]);ctx.beginPath();let started=false;
          const originY=measure?this.priceToY(obj.points[0].price):null,progress=1-(1-Number(obj.text_args.progress??1))**3;
          const opening=this.structureOpening.get(String(obj.text_args.event_id)),age=opening===undefined?Infinity:performance.now()-opening;
          const wipe=opening===undefined?1:1-(1-Math.min(1,age/this.living.draw_on_ms))**3;
          const fromX=this.timeToX(path[0].t_ms)??0;
          const lastBar=[...this.bars.values()].at(-1);
          const lastX=lastBar?this.timeToX(lastBar.t_open_ms):null;
          for(const point of path){let rawX=this.timeToX(point.t_ms)??(point.t_ms<r.from?0:point.t_ms>r.to?plotWidth:null);if(obj.style.token==='notebook.scenario'&&lastX!==null&&point.t_ms>(lastBar?.t_open_ms??0))rawX=lastX+(plotWidth-lastX)*.55;const rawY=this.priceToY(obj.shape==='PATH'?this.clipDrawPrice(point.price):point.price);if(rawX===null||rawY===null){started=false;continue;}const px=measure?x:fromX+(rawX-fromX)*wipe,py=measure&&originY!==null?originY+(rawY-originY)*progress:rawY;if(started)ctx.lineTo(px,py);else ctx.moveTo(px,py);started=true;}
          ctx.stroke();ctx.restore();
          if(opening!==undefined){
            if(age<this.living.draw_on_ms){
              if(obj.text_args.attention&&this.living.attention_enabled){ctx.save();const glow=ctx.createRadialGradient(baseX,y,0,baseX,y,40);glow.addColorStop(0,'rgba(222,195,140,.08)');glow.addColorStop(1,'rgba(222,195,140,0)');ctx.fillStyle=glow;ctx.fillRect(baseX-40,y-40,80,80);ctx.restore();}
              this.shade();
            }else this.structureOpening.delete(String(obj.text_args.event_id));
          }
          if(obj.style.token==='living.measurement'){
            ctx.save();ctx.globalAlpha=Number(obj.text_args.opacity??1);ctx.strokeStyle='#dec38c';
            for(const point of obj.points){const rawY=this.priceToY(obj.shape==='PATH'?this.clipDrawPrice(point.price):point.price);if(rawY!==null){const py=originY===null?rawY:originY+(rawY-originY)*progress;ctx.beginPath();ctx.moveTo(x-5,py);ctx.lineTo(x+5,py);ctx.stroke();}}
            ctx.restore();
          }
        }
        const strip=obj.style.token==='analysis.reason';
        if(strip&&performance.now()>=(this.reasonExpiry.get(obj.id??obj.text_key)??0))continue;
        if(!strip&&obj.shape!=='LABEL'&&obj.shape!=='ZONE'&&obj.shape!=='LINE'&&obj.shape!=='RAY'&&obj.shape!=='PATH')continue;
        const lines=labelLines(obj);if(!lines.length)continue;
        const isLevelLabel=protectedLevel||liquidityLevel||callLevel;
        const levelKey=isLevelLabel?String(obj.id??obj.text_key??`${obj.style.token}:${first.price}`):'';
        if(isLevelLabel&&levelLabelSeen.has(levelKey))continue;
        if(isLevelLabel)levelLabelSeen.add(levelKey);
        const below=obj.style.token==='utbot.buy'||obj.text_args.direction==='BULLISH'||obj.text_args.direction==='LONG'||obj.text_args.direction==='DOWN';
        const bar=this.bars.get(first.t_ms),wick=bar?this.priceToY(below?bar.l:bar.h):null;
        const anchor=isLevelLabel?y:measure?Math.min(...measureYs):corner?46:wick===null?y:below?Math.max(y,wick):Math.min(y,wick);
        ctx.font=`700 ${strip?15:14}px ${CHART_FONT}`;
        const signalCard=obj.style.token==='call.trade';
        const width=Math.max(...lines.map(line=>ctx.measureText(line).width))+(signalCard?34:20);
        const chipX=isLevelLabel||zone?plotWidth-12:x;
        const color=obj.style.token.startsWith('utbot.')&&obj.style.token!=='utbot.provisional'?(below?'#26A69A':'#EF5350'):obj.style.token==='structure.event'?'#1A1E25':obj.style.token==='liquidity.pool'?'#0B0D10':obj.style.token==='call.trade'?'#1A1E25':obj.style.token==='call.level'?'#0B0D10':'#1A1E25';
        candidates.push({id:obj.id??obj.text_key,t:first.t_ms,priority:signalCard?100:obj.text_args.lifecycle==='DISCARDED'?4.75:zone&&obj.text_args.confirmed===false?4.5:labelPriority(obj),x:measure?x-measureWidth/2-14:chipX,anchor,below,lines,width,height:signalCard?lines.length*23+20:lines.length>1?lines.length*20+14:30,color,opacity:protectedLevel?1:zone||liquidityLevel?this.fvgZones.opacity(obj):Number(obj.text_args.opacity??1),strikethrough:obj.text_args.lifecycle==='DISCARDED',pinnedLevel:isLevelLabel,levelPrice:isLevelLabel?first.price:undefined,token:obj.style.token});
      }

      const deduped=new Map<string,LabelCandidate>();
      for(const candidate of candidates){
        const key=String(candidate.token??'')+':'+candidate.id+':'+candidate.lines.join('|');
        const current=deduped.get(key);
        if(!current||candidate.priority>current.priority||candidate.t>current.t)deduped.set(key,candidate);
      }
      candidates=[...deduped.values()];
      const callPinned=candidates.filter(c=>c.pinnedLevel&&c.token==='call.level');
      const otherPinned=candidates.filter(c=>c.pinnedLevel&&c.token!=='call.level').sort((a,b)=>a.anchor-b.anchor||b.priority-a.priority);
      const notPinned=candidates.filter(c=>!c.pinnedLevel);
      const mergedPinned:LabelCandidate[]=[];
      for(const candidate of otherPinned){
        const last=mergedPinned.at(-1);
        const lastMergeMax=last?Number((last as any).mergeMax??last.anchor):Number.NaN;
        const lastMergeMin=last?Number((last as any).mergeMin??last.anchor):Number.NaN;
        if(last&&candidate.anchor-lastMergeMax<=10){
          const lines=[...last.lines];
          for(const line of candidate.lines)for(const part of line.split(/\s{2,}|\s+\/\s+/)){const text=part.trim();if(text&&!lines.includes(text))lines.push(text);}
          last.lines=lines.slice(0,3);
          last.width=Math.max(last.width, ...last.lines.map(line=>ctx.measureText(line).width+16));
          last.priority=Math.max(last.priority,candidate.priority);
          (last as any).mergeMin=Math.min(lastMergeMin,candidate.anchor);
          (last as any).mergeMax=Math.max(lastMergeMax,candidate.anchor);
          last.anchor=(Number((last as any).mergeMin)+Number((last as any).mergeMax))/2;
        }else mergedPinned.push({...candidate,mergeMin:candidate.anchor,mergeMax:candidate.anchor} as LabelCandidate);
      }
      candidates=[...callPinned,...mergedPinned,...notPinned];
      ctx.save();ctx.beginPath();ctx.rect(0,0,plotWidth,plotHeight);ctx.clip();
      const brandBox={x:Math.max(0,plotWidth-126),y:Math.max(0,plotHeight-32),width:122,height:28};
      const labelCap=this.density==='notebook'?40:this.density==='analyst'?20:10;
      const placements=placeLabels(candidates,bodies,plotWidth,plotHeight,labelCap,[brandBox]);
      const labelAudit:any[]=[];
      for(const {candidate,box} of placements){
        ctx.fillStyle=candidate.color;ctx.globalAlpha=candidate.opacity??1;
        if(!box){
          labelAudit.push({id:candidate.id,token:candidate.token,pinnedLevel:candidate.pinnedLevel??false,levelPrice:candidate.levelPrice,anchor:candidate.anchor,labelY:null,delta:null,dropped:true,dropReason:'placement collision or label cap',lines:candidate.lines,box:null});
          const x=candidate.x,y=Math.max(4,Math.min(plotHeight-4,candidate.anchor+(candidate.below?8:-8))),sign=candidate.below?-1:1;
          ctx.beginPath();ctx.moveTo(x,y+sign*3);ctx.lineTo(x-3,y-sign*3);ctx.lineTo(x+3,y-sign*3);ctx.closePath();ctx.fill();continue;
        }
        const source=this.objects.find(o=>(o.id??o.text_key)===candidate.id);
        const signalCard=source?.style.token==='call.trade';
        const strip=candidate.lines.length>1||source?.style.token==='analysis.reason';
        const displaced=Math.hypot((box.x+box.width/2)-candidate.x,(box.y+box.height/2)-candidate.anchor)>16;
        if(displaced){ctx.save();ctx.globalAlpha=.85;ctx.strokeStyle=this.theme==='dark'?'#5f7793':'#242A33';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(candidate.x,candidate.anchor);ctx.lineTo(Math.max(box.x,Math.min(candidate.x,box.x+box.width)),Math.max(box.y,Math.min(candidate.anchor,box.y+box.height)));ctx.stroke();ctx.restore();}
        const token=source?.style.token??'';
        const filled=signalCard||token.startsWith('utbot.');
        if(signalCard){
          const gradient=ctx.createLinearGradient(box.x,box.y,box.x+box.width,box.y+box.height);
          gradient.addColorStop(0,'#f2d990');gradient.addColorStop(.5,'#d7b86b');gradient.addColorStop(1,'#f7e4a5');
          ctx.fillStyle=gradient;ctx.beginPath();ctx.roundRect(box.x,box.y,box.width,box.height,3);ctx.fill();
          ctx.strokeStyle='#fff3bf';ctx.lineWidth=2;ctx.beginPath();ctx.roundRect(box.x+.5,box.y+.5,box.width-1,box.height-1,3);ctx.stroke();
        }else if(token.startsWith('utbot.')){ctx.beginPath();ctx.roundRect(box.x,box.y,box.width,box.height,3);ctx.fill();}
        ctx.font=`900 ${signalCard?15:strip?15:14}px ${CHART_FONT}`;ctx.textAlign='left';
        const textColor=token.startsWith('utbot.')?'#07172a':token==='call.level'?'#f7fbff':token==='liquidity.pool'?'#dbe7f8':token==='structure.event'?(String(source?.text_args.kind??'').toUpperCase()==='BOS'?(String(source?.id??'')===String(this.objects.filter(o=>o.style.token==='structure.event').sort((a,b)=>Number(b.points?.at(-1)?.t_ms??0)-Number(a.points?.at(-1)?.t_ms??0))[0]?.id)?'#f7fbff':'#cfdbec'):'#ffd774'):'#f7fbff';
        candidate.lines.forEach((line,i)=>{const tx=box.x+(signalCard?14:filled?9:0),ty=box.y+(signalCard?24+i*23:strip?21+i*20:21);if(!filled){ctx.save();ctx.lineJoin='round';ctx.strokeStyle=this.theme==='dark'?'#031020':'#FFFFFF';ctx.lineWidth=4;ctx.strokeText(line,tx,ty);ctx.restore();}ctx.fillStyle=textColor;ctx.fillText(line,tx,ty);});
        if(candidate.pinnedLevel&&Number.isFinite(Number(candidate.levelPrice))){const tag=fmt.price(Number(candidate.levelPrice));ctx.font=`800 12px ${CHART_FONT}`;const tw=ctx.measureText(tag).width+10;let tx=Math.max(2,plotWidth-tw-2);const ty=Math.max(2,Math.min(plotHeight-17,candidate.anchor-9));const tagBox={x:tx,y:ty,width:tw,height:18};if(overlaps(tagBox,brandBox,4)){tx=Math.max(2,brandBox.x-tw-6);tagBox.x=tx;}ctx.fillStyle=this.theme==='dark'?'#10243a':'#EFF1F5';ctx.beginPath();ctx.roundRect(tx,ty,tw,18,3);ctx.fill();ctx.fillStyle=textColor;ctx.fillText(tag,tx+5,ty+14);}
        if(candidate.strikethrough){ctx.strokeStyle=source?.style.token.startsWith('utbot.')?'#0B0D10':'#E8EBF0';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(box.x+6,box.y+13);ctx.lineTo(box.x+box.width-6,box.y+13);ctx.stroke();}
        labelAudit.push({id:candidate.id,token:candidate.token,pinnedLevel:candidate.pinnedLevel??false,levelPrice:candidate.levelPrice,anchor:candidate.anchor,labelY:box.y+box.height+4,delta:Math.abs((box.y+box.height+4)-candidate.anchor),dropped:false,lines:candidate.lines,box:{x:box.x,y:box.y,width:box.width,height:box.height}});
      }
      if(typeof window!=='undefined')Object.assign(window,{oracleLabelAudit:()=>labelAudit});
      ctx.restore();
      this.scheduleReasonTimer();
      if(gesture||sessionAge<5200)this.shade();
    });
  }
  on<K extends keyof ChartEvents>(event:K,cb:(value:ChartEvents[K])=>void){const set=this.listeners.get(event)??new Set();set.add(cb);this.listeners.set(event,set);return()=>{set.delete(cb);};}
  private emit<K extends keyof ChartEvents>(event:K,value:ChartEvents[K]){for(const cb of this.listeners.get(event)??[])cb(value);}
}






