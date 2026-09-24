import {useEffect, useRef, useState} from 'react';
import type {Bar} from '../net/protocol';
import type {ChartDebug, ChartFrame, TickQuote} from '../net/chart';
import type {IChartCore, Timeframe} from './IChartCore';
import {LightweightChartsCore} from './LightweightChartsCore';
import {ModeBadge,type UIMode} from '../auth/Studio';
import type {SessionStatus} from '../net/auth';
import type {RetentionFrame} from '../net/retention';
import {RetentionRail} from '../retention/Retention';
import {Watching} from '../retention/Watching';
import {ClockCluster} from '../stream/ClockCluster';
import {decisionWorklog} from '../living/Worklog';
import {ReplayCoverage} from '../living/ReplayCoverage';
import type {TikTokComment,TikTokWelcome} from '../stream/types';
import {fmt,liveParts} from '../fmt';
import {copy} from '../copy';
import {buildSignalProcedure} from '../signalProcedure';
import {thesisView} from '../thesisView';
import {buildAnalysisSlides} from '../analysisSlides';
import {AnalysisSlides} from './AnalysisSlides';
import {buildNotebookObjects, notebookNotes, bookNotes} from '../notebook';
import {PlanTracker, buildPlanObjects, planNotes, planHistorySlide, type PlanVersion} from '../planHistory';
import {ReactionTracker, buildReactionObjects, reactionNotes, type LevelReaction} from '../reactions';
import {detectConfluenceStacks, buildAnalysisObjects, analysisObjectNotes, type AnalysisObject} from '../analysisObjects';

const timeframes: Timeframe[]=['M1','M5','M15','M30','H1','H4','D1','W1'];
const savedTimeframe=():Timeframe=>{
 const saved=localStorage.getItem('oracle:last-timeframe');
 return timeframes.includes(saved as Timeframe)?saved as Timeframe:'M5';
};
export function remaining(closeMs:number|null|undefined, nowMs:number):string {
  if(!closeMs)return '-';
  const seconds=Math.max(0,Math.ceil((closeMs-nowMs)/1000));
  return `${Math.floor(seconds/3600)?`${Math.floor(seconds/3600)}:`:''}${String(Math.floor(seconds/60)%60).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}
const utc=(ms:number)=>new Date(ms).toISOString().replace('T',' ').replace('.000Z',' UTC');
const offset=(s:number)=>`${s<0?'-':'+'}${String(Math.floor(Math.abs(s)/3600)).padStart(2,'0')}:${String(Math.floor(Math.abs(s)%3600/60)).padStart(2,'0')}`;

export function LiveChart({theme,active,mode,session,toggleTheme,comments=[],joins=[]}:{theme:'dark'|'light';active:boolean;mode:UIMode;session:SessionStatus;toggleTheme:()=>void;comments?:(TikTokComment&{id:number})[];joins?:(TikTokWelcome&{id:number;returning:boolean;join_count:number})[]}) {
  const el=useRef<HTMLDivElement>(null);
  const activeRef=useRef(active);activeRef.current=active;
  const core=useRef<IChartCore|null>(null);
  const frameRef=useRef<ChartFrame|null>(null);
  const currentTf=useRef<Timeframe>(savedTimeframe());
  const generation=useRef(0);
  const anchor=useRef({server:Date.now(),local:performance.now()});
  const [tf,setTf]=useState<Timeframe>(savedTimeframe);
  const [frame,setFrame]=useState<ChartFrame|null>(null);
  const [live,setLive]=useState<Bar|null>(null);
  const [crosshair,setCrosshair]=useState<Bar|null>(null);
  const [debug,setDebug]=useState<ChartDebug|null>(null);
  const [drawer,setDrawer]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [fault,setFault]=useState<{code:string;message:string;detail:Record<string,unknown>;recoverable:boolean}|null>(null);
  const [resolved,setResolved]=useState('');
  const [now,setNow]=useState(Date.now());
  const [corrections,setCorrections]=useState<string[]>([]);
  const [tick,setTick]=useState<TickQuote|null>(null);
  const [switchMs,setSwitchMs]=useState<number|null>(null);
  const [retention,setRetention]=useState<RetentionFrame|null>(null);
  const [analysisWorklog,setAnalysisWorklog]=useState<{id:string;at_ms:number;tf:Timeframe;object_id:string;action:'MARKED';label:string;source_bars:number[];source_object_ids:string[]}[]>([]);
  const replayRef=useRef(false);
  const replayTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(()=>{
    const onWorklog=(event:Event)=>{
      const detail=(event as CustomEvent<{key:string;label:string;at_ms:number}>).detail;
      if(!detail?.key||!detail.label)return;
      setAnalysisWorklog(previous=>{
        if(previous.some(item=>item.id===`analysis:${detail.key}`))return previous;
        return [...previous,{id:`analysis:${detail.key}`,at_ms:detail.at_ms,tf:currentTf.current,object_id:detail.key,action:'MARKED' as const,label:detail.label,source_bars:[],source_object_ids:[]}].slice(-8);
      });
    };
    window.addEventListener('oracle:analysis-worklog',onWorklog);
    return()=>window.removeEventListener('oracle:analysis-worklog',onWorklog);
  },[]);
  const [replayEpoch,setReplayEpoch]=useState(0);
  const [recordedSource,setRecordedSource]=useState('');
  const themeRef=useRef(theme);themeRef.current=theme;
  const retentionRef=useRef<RetentionFrame|null>(null);
  const zoomRange=useRef<{from:number;to:number}|null>(null);
  const planTracker=useRef(new PlanTracker());
  const reactionTracker=useRef(new ReactionTracker());
  const [plans,setPlans]=useState<PlanVersion[]>([]);
  const [reactions,setReactions]=useState<LevelReaction[]>([]);
  const [analysisObjects,setAnalysisObjects]=useState<AnalysisObject[]>([]);
  const priceRef=useRef<HTMLElement|null>(null);
  const chartDensity=useRef<'clean'|'analyst'|'notebook'>('notebook');
  const chartBars=useRef<Bar[]>([]);

  const packetWithBars=(packet:ChartFrame):ChartFrame=>{
    if(packet.snapshot?.bars?.length){
      chartBars.current=packet.snapshot.bars.slice(-2200);
      return packet;
    }
    if(packet.update?.bar){
      const next=chartBars.current.filter(bar=>bar.t_open_ms!==packet.update!.bar.t_open_ms);
      next.push(packet.update.bar);
      next.sort((a,b)=>a.t_open_ms-b.t_open_ms);
      chartBars.current=next.slice(-2200);
    }
    if(!chartBars.current.length)return packet;
    return {...packet,snapshot:{symbol:'XAUUSD',tf:currentTf.current,bars:chartBars.current,clockVersion:0}};
  };

  const accept=(packet:ChartFrame)=> {
    if(packet.snapshot?.tf!==currentTf.current&&packet.update?.tf!==currentTf.current&&packet.kind!=='status')return;
    if(packet.resolved_symbol)setResolved(packet.resolved_symbol);
    frameRef.current=packet;setFrame(packet);
    const nextDensity=packet.chart_density??'clean';
    if(nextDensity!==chartDensity.current){
      chartDensity.current=nextDensity;
      core.current?.setDensity(nextDensity);
    }
    anchor.current={server:packet.now_ms,local:performance.now()};
    if(packet.snapshot){core.current?.setSessions(packet.closures??[]);core.current?.applyBars(packet.snapshot.bars);setLive(packet.snapshot.bars.at(-1)??null);}
    else if(packet.kind==='status'&&packet.closures?.length)core.current?.setSessions(packet.closures);
    if(packet.update){core.current?.updateBar(packet.update.bar);setLive(previous=>!previous||packet.update!.bar.t_open_ms>=previous.t_open_ms?packet.update!.bar:previous);}
    core.current?.setDecisions(packet.candidate_decisions??[]);
    { const renderPacket=packetWithBars(packet); const tv=thesisView(packet.thesis); const px=packet.quote?.bid??packet.update?.bar?.c??renderPacket.snapshot?.bars?.at(-1)?.c??null; const updatedPlans=planTracker.current.update(renderPacket,tv,px); setPlans(updatedPlans.slice()); const nb=buildNotebookObjects(renderPacket,tv,px); const po=buildPlanObjects(updatedPlans,renderPacket,px); const baseObjects=[...(packet.objects??[]),...nb,...po]; const detectors=detectConfluenceStacks(renderPacket,baseObjects,packet.liquidity_pools??[],px); setAnalysisObjects(detectors); const detectorObjects=buildAnalysisObjects(detectors,renderPacket); const updatedReactions=reactionTracker.current.update(renderPacket,[...baseObjects,...detectorObjects],px); setReactions(updatedReactions.slice()); const ro=buildReactionObjects(updatedReactions,renderPacket); core.current?.applyDrawObjects([...baseObjects,...detectorObjects,...ro,...(retentionRef.current?.marks??[])],packet.language??'en'); }
    core.current?.setBarColors(packet.bar_colors??[]);
    if(packet.kind==='correction'&&packet.update)setCorrections(previous=>[`${utc(packet.update!.bar.t_open_ms)} ${packet.update!.tf} broker correction`,...previous].slice(0,200));
    if(packet.kind==='clock_refined')setCorrections(previous=>[`ClockRefined v${packet.snapshot?.clockVersion}: history refetched`,...previous].slice(0,200));
  };
  useEffect(()=> {
    let disposed=false;
    const adapter:IChartCore=new LightweightChartsCore();core.current=adapter;
    void adapter.mount(el.current!,{theme:themeRef.current,visibleBars:120,density:'notebook'}).then(()=>{
      if(disposed)return;
      adapter.on('crosshair',e=>setCrosshair(e.bar));
      window.oracle?.streamConfig?.().then(config=>adapter.setStream(config)).catch(()=>{});
      window.oracle?.livingConfig?.().then(config=>adapter.setLiving(config)).catch(()=>{});
    });
    const remove=window.oracle?.onChart?.(packet=>{if(!disposed&&!replayRef.current)accept(packet);});
    const recorded=(event:Event)=>{
      const detail=(event as CustomEvent<{packet:ChartFrame;source:string;range?:{from:number;to:number}}>).detail;
      replayRef.current=true;setRecordedSource(detail.source);setTick(null);setLoading(false);setError('');
      if(typeof window!=='undefined')Object.assign(window,{__oracleRecordedPacket:detail.packet});
      accept(detail.packet);
      if(detail.range)adapter.setVisibleRange(detail.range.from,detail.range.to);
      if(replayTimer.current)clearTimeout(replayTimer.current);
      replayTimer.current=setTimeout(()=>window.dispatchEvent(new Event('oracle:recorded-end')),30000);
    };
    const recordedEnd=()=>{if(replayTimer.current)clearTimeout(replayTimer.current);replayTimer.current=null;replayRef.current=false;setRecordedSource('');setReplayEpoch(value=>value+1);};
    window.addEventListener('oracle:recorded-frame',recorded);
    window.addEventListener('oracle:recorded-end',recordedEnd);
    const removeStream=window.oracle?.onStreamConfig?.(config=>adapter.setStream(config));
    const removeQuote=window.oracle?.onQuote?.(quote=>{if(!disposed&&!replayRef.current){setTick(quote);anchor.current={server:quote.now_ms,local:performance.now()};}});
    const removeError=window.oracle?.onChartError?.(issue=>{if(!disposed){setError(issue.message);setFault(issue);setLoading(false);}});
    const key=(e:KeyboardEvent)=>{if(e.key==='`'&&!(e.target instanceof HTMLInputElement)){e.preventDefault();setDrawer(v=>!v);}};
    window.addEventListener('keydown',key);
    const timer=setInterval(()=>{
      const time=anchor.current.server+performance.now()-anchor.current.local;
      setNow(time);core.current?.sessionAt(time,activeRef.current&&frameRef.current?.quality.state!=='STALE'&&frameRef.current?.quality.state!=='GAPPED');
    },200);
    return()=>{disposed=true;if(replayTimer.current)clearTimeout(replayTimer.current);remove?.();removeStream?.();removeQuote?.();removeError?.();clearInterval(timer);window.removeEventListener('oracle:recorded-frame',recorded);window.removeEventListener('oracle:recorded-end',recordedEnd);window.removeEventListener('keydown',key);adapter.destroy();core.current=null;};
  },[]);
  useEffect(()=>{core.current?.setTheme(theme);},[theme]);
  useEffect(()=>{
    let alive=true;
    const remove=window.oracle?.onRetention?.(value=>{if(alive)setRetention(value);});
    const recorded=(event:Event)=>{if(alive)setRetention((event as CustomEvent<RetentionFrame>).detail);};
    window.addEventListener('oracle:recorded-retention',recorded);
    window.oracle?.retentionState?.().then(value=>{if(alive)setRetention(value);}).catch(()=>{});
    return()=>{alive=false;remove?.();window.removeEventListener('oracle:recorded-retention',recorded);};
  },[]);
  useEffect(()=>{
    retentionRef.current=retention;
    if(!replayRef.current){ const packet=frameRef.current; const renderPacket=packet?packetWithBars(packet):null; const tv=thesisView(packet?.thesis); const px=packet?.quote?.bid??packet?.update?.bar?.c??renderPacket?.snapshot?.bars?.at(-1)?.c??null; const nb=buildNotebookObjects(renderPacket,tv,px); const po=buildPlanObjects(plans,renderPacket,px); const detectorObjects=buildAnalysisObjects(analysisObjects,renderPacket); const ro=buildReactionObjects(reactions,renderPacket); core.current?.applyDrawObjects([...(packet?.objects??[]),...nb,...po,...detectorObjects,...ro,...(retention?.marks??[])],retention?.language??'en'); }
    if(mode==='operator'&&retention?.zoom){
      if(!zoomRange.current)zoomRange.current=core.current?.visibleRange()??null;
      core.current?.setVisibleRange(retention.zoom.from_ms,retention.zoom.to_ms);
    }else if(zoomRange.current){core.current?.setVisibleRange(zoomRange.current.from,zoomRange.current.to);zoomRange.current=null;}
  },[retention]);
  useEffect(()=> {
    localStorage.setItem('oracle:last-timeframe',tf);
    currentTf.current=tf;const seq=++generation.current;
    setLoading(true);setError('');setFault(null);setCrosshair(null);if(replayEpoch===0){setLive(null);setFrame(null);}
    if(!active){setLoading(false);return;}
    const bridge=window.oracle;
    if(!bridge?.chartSubscribe){setError('Live chart requires the desktop data connection.');setLoading(false);return;}
    void core.current?.setSymbol('XAUUSD',tf);
    bridge.chartDebug().then(metadata=>{if(seq===generation.current){setDebug(metadata);setResolved(metadata.resolved_symbol);}}).catch(()=>{});
    const requestStarted=performance.now();
    let retry:ReturnType<typeof setTimeout>|null=null;
    const subscribe=()=>bridge.chartSubscribe(tf).then(async packet=> {
      if(seq!==generation.current)return;
      accept(packet);setLoading(false);setSwitchMs(performance.now()-requestStarted);
      const metadata=await bridge.chartDebug();if(seq===generation.current)setDebug(metadata);
    }).catch((issue:unknown)=>{if(seq===generation.current){const typed=issue as {code?:string;message?:string;detail?:Record<string,unknown>;recoverable?:boolean};setError(typed.message??'Chart response was invalid; reconnect the desktop.');setFault({code:typed.code??'IPC_RESPONSE_INVALID',message:typed.message??'Chart response was invalid; reconnect the desktop.',detail:typed.detail??{},recoverable:typed.recoverable??true});setLoading(false);retry=setTimeout(()=>{if(seq===generation.current){setLoading(true);void subscribe();}},3000);}});
    void subscribe();
    return()=>{generation.current++;if(retry)clearTimeout(retry);};
  },[tf,active,replayEpoch]);
  useEffect(()=> {
    if(!drawer||!active||!window.oracle?.chartDebug)return;
    let disposed=false,busy=false;
    const refresh=async()=>{if(busy)return;busy=true;try{const info=await window.oracle!.chartDebug();if(!disposed)setDebug(info);}catch{/* Reconnection status is supplied by chrome. */}finally{busy=false;}};
    void refresh();const timer=setInterval(()=>void refresh(),1000);
    return()=>{disposed=true;clearInterval(timer);};
  },[drawer,active]);
  const indicatorSettings=async(options:{enabled?:boolean;key?:number;atr_period?:number;show_stop_line?:boolean;color_bars?:boolean})=>{
    try{const packet=await window.oracle!.chartIndicator(options);accept(packet);setDebug(await window.oracle!.chartDebug());}
    catch(issue){setError((issue as {message?:string}).message??'Indicator settings were invalid; check key and ATR period.');}
  };
  const quote=tick?.quote??frame?.quote;
  const digits=tick?.digits??live?.digits??2;
  const tickAge=quote?Math.max(0,(now-quote.t_ms)/1000):null;
  const debugBar=(bar:Bar|null)=> {
    if(!bar)return <p>No candle selected</p>;
    const raw=debug?.bars.find(b=>b.t_open_ms===bar.t_open_ms);
    return <dl className="debug-values">
      <dt>t_open_ms</dt><dd>{bar.t_open_ms} - {utc(bar.t_open_ms)}</dd>
      <dt>t_broker_ms</dt><dd>{raw?`${raw.t_broker_ms} - ${utc(raw.t_broker_ms).replace(' UTC',' broker')} - offset ${offset(raw.offset_s)} - clock v${raw.clock_version}`:'Provenance unavailable'}</dd>
      <dt>source</dt><dd>{bar.source} - clock {bar.clock_confidence??'ASSUMED'} - corrections this session: {debug?.corrections??0} / {debug?.checked??0} checked</dd>
      <dt>o h l c</dt><dd>{[bar.o,bar.h,bar.l,bar.c].map(p=>fmt.live(p)).join(' / ')}</dd>
      <dt>tick_volume</dt><dd>{bar.tick_volume} - spread {fmt.spread(debug?.spread_points)??'--'}</dd>
      <dt>bar age</dt><dd>{Math.max(0,Math.floor((now-bar.t_open_ms)/1000))}s / {frame?.bar_duration_ms ? frame.bar_duration_ms/1000 : '-'}s - next live close in {remaining(frame?.next_close_ms,now)}</dd>
      <dt>data quality</dt><dd>{frame?.quality.state??'-'} - last tick {debug?fmt.usd(Math.max(0,(now-debug.last_tick_ms)/1000)):'-'}s ago</dd>
    </dl>;
  };
  if(typeof window!=='undefined')Object.assign(window,{__oracleLastFrame:frame,__oracleLastRetention:retention});
  const marketClosed=retention?.session==='Market closed';
  const feedStale=(tickAge??0)>10&&active&&!marketClosed;
  const health=frame?.quality.state==='STALE'||frame?.quality.state==='GAPPED'||!active||!!error||feedStale?'fault':!session.clockProven||frame?.quality.state==='CALENDAR_PENDING'||frame?.quality.state==='WIDE_SPREAD'?'pending':'healthy';
  const openCalls=(retention?.scoreboard?.rows??[]).map(row=>row.call).filter(call=>call.state==='ACTIVE'||((call.state??'PENDING')==='PENDING'&&now-(call.created_ms??now)<600000));
  const liveSignal=[...openCalls].sort((a,b)=>(b.created_ms??0)-(a.created_ms??0))[0];
  const liveSignalR=liveSignal?Math.abs(liveSignal.target-Number(liveSignal.entry_ref??(liveSignal.direction==='LONG'?liveSignal.entry_hi:liveSignal.entry_lo)))/Math.max(0.000001,Math.abs(Number(liveSignal.entry_ref??(liveSignal.direction==='LONG'?liveSignal.entry_hi:liveSignal.entry_lo))-liveSignal.invalidation)):0;
  const signalProcedure=buildSignalProcedure({price:quote?.bid??live?.c??null,tf,structure:frame?.structure_state,objects:frame?.objects??[],pools:frame?.liquidity_pools??[]});
  const thesis=thesisView(frame?.thesis);
  const signalBanner=marketClosed?copy.chart.marketClosed:liveSignal?`LIVE CALL  ${liveSignal.timeframe??tf} ${liveSignal.direction==='LONG'?'BUY':'SELL'} ${fmt.range(liveSignal.entry_lo,liveSignal.entry_hi)}  SL ${fmt.price(liveSignal.invalidation)}  TP1 ${fmt.price(liveSignal.target)}  ${fmt.r(liveSignalR)}  ${liveSignal.state}`:thesis?.headline||signalProcedure.headline;
  const analysisSlides=buildAnalysisSlides({thesis,frame,retention,tf,price:quote?.bid??live?.c??null,liveSignal,liveSignalR,now,planHistory:planHistorySlide(plans),book:frame?.book??null});
  const bookStoryCard=Array.isArray(frame?.book?.story_card)?(frame.book.story_card as unknown[]).map(String).filter(Boolean).slice(0,4):[];
  const notes=[...bookNotes(frame?.book),...notebookNotes(thesis,[...(frame?.candidate_status?.state?decisionWorklog(frame.candidate_worklog??frame.candidate_decisions??[]):frame?.worklog??[]),...analysisWorklog]),...analysisObjectNotes(analysisObjects),...reactionNotes(reactions),...planNotes(plans)].slice(-8);
  if(!analysisSlides.length&&signalBanner)analysisSlides.push({type:'THESIS',content:signalBanner,key:`fallback:${signalBanner}`,changed_ms:now,anchor:true});
  const delta=live&&quote?quote.bid-live.o:0;
  const bidParts=liveParts(quote?.bid??live?.c);
  return <>
    <main className="live-workspace" data-broadcast-layer={mode==='broadcast'?'L0':undefined}>
      <div className="chart-toolbar">
        <div className="identity-zone"><div className="chart-symbol"><strong>XAUUSD</strong><span>{resolved||debug?.resolved_symbol||'Gold'}</span></div>
          <nav aria-label="Chart timeframe">{timeframes.map(t=><button key={t} disabled={loading||!active} aria-pressed={tf===t} onClick={()=>setTf(t)}>{t}</button>)}</nav>
        </div>
        <div className="price-zone"><div className={`price-focal ${feedStale?'is-stale':''}`}><small>BID <i className={`tick-age-dot ${tickAge===null||tickAge>5?'old':tickAge>=1?'aging':'fresh'}`} aria-label="Tick age"/></small><strong ref={priceRef} data-testid="bid-price">{bidParts.main}<sup>{bidParts.last}</sup></strong>
          <span className={`price-delta ${delta>=0?'direction-up':'direction-down'}`}>{fmt.delta(delta)}</span></div>
          {recordedSource?<strong className="replay-badge">REPLAY / {recordedSource}</strong>:<small className="ask-spread" title={quote?`$${fmt.spread((quote.ask-quote.bid)*1000)}/oz`:undefined}>Ask {fmt.live(quote?.ask)}  Spread {fmt.spread(tick?.spread_points??frame?.quality.spread_points)}</small>}<AnalysisSlides slides={analysisSlides} mode={mode}/>
        </div>
        <div className="state-zone"><ClockCluster now={now} countdown={marketClosed?'--':remaining(frame?.next_close_ms,now)}/></div>
      </div>
      {mode==='operator'&&<div className="operator-status" data-operator-only="true"><span className={`status-chip quality-${frame?.quality.state??'NO_DATA'}`} data-testid="data-quality">{frame?.quality.state.replace('_',' ')??'NO DATA'}</span><span>Tick age {tickAge==null?undefined:fmt.usd(tickAge)??'--'}s</span><span>Switch {switchMs==null?undefined:fmt.usd(switchMs)??'--'}ms</span>{frame?.indicator_enabled&&<span>indicator / UT Bot</span>}</div>}
      <div className="content-planes"><div className="chart-stage" data-broadcast-layer="L0"><div ref={el} className="chart-canvas" data-testid="live-chart"/>
        {(loading||error||!active)&&<div className="chart-message" role="status">{!active?copy.chart.feedRetry:error?copy.chart.feedRetry:loading?(frame?copy.chart.feedRetry:mode==='broadcast'?copy.chart.preparing:copy.chart.loading):''}{error&&mode==='operator'&&<><small>{error}</small><button onClick={()=>void window.oracle?.switchAccount()}>Return to preflight</button></>}</div>}
        {retention?.shout&&<div className="shout-strip" aria-live="polite">{retention.shout}</div>}
        {frame?.chart_density==='notebook'&&notes.length>0&&<div className="analyst-notes" aria-label="Analyst notes"><strong>ANALYST NOTES - {tf}<em className="stage-tracker">{['BIAS','ZONE','PULLBACK','TRIGGER','ACTIVE','RESULT'].map(name=>{const activeCall=liveSignal?.state==='ACTIVE';const pendingCall=liveSignal?.state==='PENDING';const current=(activeCall&&name==='ACTIVE')||(pendingCall&&name==='TRIGGER')||(!activeCall&&!pendingCall&&thesis?.stage==='WAITING_FOR_PRICE'&&name==='PULLBACK')||(!activeCall&&!pendingCall&&thesis?.stage==='PRICE_AT_ZONE'&&name==='ZONE')||(thesis?.stage==='JUST_RESOLVED'&&name==='RESULT')||(!activeCall&&!pendingCall&&thesis?.bias&&thesis.bias!=='UNDEFINED'&&name==='BIAS');return <span key={name} className={current?'current':''}>{name}</span>;})}</em></strong>{notes.map((note,i)=><span key={i}>{note}</span>)}</div>}
        {bookStoryCard.length>0&&<div className="book-story-card" aria-live="polite">{bookStoryCard.map((line,i)=><span key={i}>{line}</span>)}</div>}
        {retention?.comment&&now<retention.comment.ends_ms&&<div className="comment-echo" aria-live="polite"><bdi dir="auto">@{retention.comment.handle}</bdi><span>{retention.comment.text}</span></div>}
      </div><RetentionRail thesis={thesis} pools={frame?.liquidity_pools??[]} weeklyOpen={frame?.liquidity_weekly_open??null} structure={frame?.structure_state} tf={tf} frame={retention} now={now} digits={digits} price={quote?.bid??live?.c??null} objects={frame?.objects??[]} worklog={[...(frame?.candidate_status?.state?decisionWorklog(frame.candidate_worklog??frame.candidate_decisions??[]):frame?.worklog??[]),...analysisWorklog]} countdown={remaining(frame?.next_close_ms,now)} comments={comments} plans={plans}/></div>
      <Watching bar={live} price={quote?.bid??live?.c??null} session={retention?.session??'Current market'} objects={frame?.objects??[]} now={now} joins={joins}/>
      {mode==='operator'&&<div className="chart-calendar" data-operator-only="true">{frame?.calendar_detail??'Calendar awaiting observed M1 history'}<span>{frame?.refinement_pending??'Clock transition derivation pending: 30 days of M1 required'} / ` opens operator diagnostics</span></div>}
    </main>
    {drawer&&<aside className="debug-drawer" data-operator-only="true" aria-label="Chart diagnostics"><header><strong>OPERATOR DIAGNOSTICS - OFF STREAM</strong><button aria-label="Close diagnostics" onClick={()=>setDrawer(false)}>CLOSE</button></header><div className="drawer-controls"><ModeBadge mode={session.tradeMode}/><button aria-label="Toggle theme" onClick={toggleTheme}>Theme</button><button onClick={()=>void window.oracle?.switchAccount()}>Switch account</button><span>{session.tradingCapable?"Master access":"Investor access"} / {session.clockProven?"Clock verified":"Clock unproven"}</span></div>{fault&&<pre>{fault.code}{'\n'}{JSON.stringify(fault.detail,null,2)}</pre>}<div className="debug-columns"><section><h3>Crosshair candle</h3>{debugBar(crosshair)}</section><section><h3>Live candle</h3>{debugBar(live)}</section></div><p>{debug?.detail} - timeframe switch {switchMs==null?undefined:fmt.usd(switchMs)??debug?.switch_ms==null?undefined:fmt.usd(debug.switch_ms)??frame?.switch_ms==null?undefined:fmt.usd(frame.switch_ms)??'-'}ms (engine {debug?.switch_ms==null?undefined:fmt.usd(debug.switch_ms)??frame?.switch_ms==null?undefined:fmt.usd(frame.switch_ms)??'--'}ms)</p><details><summary>Gateway queue and missing ranges</summary><pre>{JSON.stringify({gateway:debug?.gateway,missing_ranges:debug?.missing_ranges},null,2)}</pre></details><section className="indicator-settings"><strong>UT Bot - indicator only</strong><label><input type="checkbox" checked={!!frame?.indicator_enabled} onChange={e=>void indicatorSettings({enabled:e.target.checked})}/> Enabled on {tf}</label><label><input type="checkbox" checked={!!debug?.indicator?.show_stop_line} onChange={e=>void indicatorSettings({show_stop_line:e.target.checked})}/> Stop line</label><label><input type="checkbox" checked={!!debug?.indicator?.color_bars} onChange={e=>void indicatorSettings({color_bars:e.target.checked})}/> Colour bars</label><span>Warm-up: first {Number(debug?.indicator?.warmup_bars??30)} bars - provisional {Number(debug?.indicator?.provisional??0)} to confirmed {Number(debug?.indicator?.confirmed??0)} - removed {Number(debug?.indicator?.removed??0)} - conversion {debug?.indicator?.conversion_rate==null?'-':`${fmt.usd(Number(debug.indicator.conversion_rate)*100)}%`}</span></section><details className="signal-evidence"><summary>UT Bot signal evidence</summary>{(frame?.objects??[]).filter(obj=>obj.style.token.startsWith('utbot.')).map(obj=><p key={obj.id}>{utc(obj.points[0].t_ms)} / {obj.reason}</p>)}</details><details><summary>EvalPoint candidate audit</summary><pre>{JSON.stringify(frame?.candidate_status??{},null,2)}</pre></details><ReplayCoverage/><div className="correction-log" aria-label="Broker corrections">{corrections.length?corrections.map((entry,i)=><div key={i}>{entry}</div>):'No broker corrections this session'}</div></aside>}
  </>;
}




