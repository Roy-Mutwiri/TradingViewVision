import type {RetentionFrame} from '../net/retention';
import {useState} from 'react';
import {KeyLevels} from './KeyLevels';
import {StructureTicker} from './StructureTicker';
import type {DrawObject} from '../net/protocol';
import type {WorkDecision,StructureState,Pool} from '../net/chart';
import {Worklog} from '../living/Worklog';
import type {TikTokComment} from '../stream/types';
import {fmt} from '../fmt';
import {copy} from '../copy';
import {sessionIntervals} from '../stream/SessionRibbon';
import {buildSignalProcedure} from '../signalProcedure';
import type {ThesisView} from '../thesisView';
import type {PlanVersion} from '../planHistory';

export function Handle({name}:{name:string}) {const letters=Array.from(new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(name),part=>part.segment);return <bdi className="viewer-handle" dir="auto">@{letters.length>18?letters.slice(0,17).join('')+'...':name}</bdi>;}

const railCountdown=(target:number,now:number)=>{const s=Math.max(0,Math.ceil((target-now)/1000));return `${Math.floor(s/3600).toString().padStart(2,'0')}:${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;};
const displayState=(value:string|undefined|null)=>String(value??'').replaceAll('_',' ').toLowerCase();

const normalizeSignalCopy=(line:string)=>{
  let text=line.replace(/(\d{4}(?:\.\d{1,3})?)\s*-\s*(\d{4}(?:\.\d{1,3})?)/g,(_,a,b)=>fmt.range(Number(a),Number(b)));
  text=text.replace(/(?<![\d,])\d{4}(?:\.\d{1,3})?(?![\d,])/g,match=>fmt.price(Number(match)));
  text=text.replace(/^Only\s+M\d+\s+(OB|FVG)\s+(.+?)\s+M\d+\s+\1\s+(below|above)\s+EQ\s+([\d,.]+)/i,(_,kind,range,side,eq)=>copy.signal.onlyZone(kind,range,side,eq));
  return text;
};

export function RetentionRail({frame,now,digits,countdown,price=null,objects=[],worklog=[],structure=null,tf='M15',pools=[],weeklyOpen=null,comments=[],thesis=null,plans=[]}:{frame:RetentionFrame|null;now:number;digits:number;countdown:string;price?:number|null;objects?:DrawObject[];worklog?:WorkDecision[];structure?:StructureState|null;tf?:string;pools?:Pool[];weeklyOpen?:number|null;comments?:(TikTokComment&{id:number})[];thesis?:ThesisView|null;plans?:PlanVersion[]}) {
  const [window,setWindow]=useState<'last_20'|'today'|'all_time'>('last_20');
  const board=frame?.scoreboard;
  const planScore={total:plans.length,a:plans.filter(p=>p.outcome==='A_REACHED').length,b:plans.filter(p=>p.outcome==='B_HIT').length,replaced:plans.filter(p=>p.outcome==='REPLACED').length,expired:plans.filter(p=>p.outcome==='EXPIRED').length};
  const stats=board?.[window];
  const completed=(board?.rows??[]).filter(row=>!['PENDING','ACTIVE'].includes(row.call.state??'PENDING')).sort((a,b)=>(a.call.resolved_ms??0)-(b.call.resolved_ms??0)||(a.call.id??'').localeCompare(b.call.id??''));
  const visible=window==='all_time'?board?.rows??[]:window==='today'?completed.filter(row=>row.call.resolved_trading_day===board?.today_trading_day):completed.slice(-20);
  const open=window==='all_time'?[]:(board?.rows??[]).filter(row=>['PENDING','ACTIVE'].includes(row.call.state??'PENDING'));
  const liveSignal=[...open].sort((a,b)=>(b.call.created_ms??0)-(a.call.created_ms??0))[0]?.call;
  const latestUt=[...objects].filter(o=>o.style.token.startsWith('utbot.')).sort((a,b)=>(Number(b.points?.[0]?.t_ms??0)-Number(a.points?.[0]?.t_ms??0)))[0];
  const utState=latestUt?(latestUt.style.token==='utbot.buy'||latestUt.text_args.direction==='BULLISH'?'BUY':'SELL'):null;
  const utSince=latestUt?fmt.time(Number(latestUt.points?.[0]?.t_ms??0)):null;
  const rows=[...open,...visible];
  const resolved=(stats?.wins??0)+(stats?.losses??0);
  const gradeRows=rows.reduce((acc,row)=>{const grade=row.call.grade??'A'; const state=row.call.state??'PENDING'; if(grade==='A'){if(state==='WIN')acc.aW++; if(state==='LOSS')acc.aL++;} else if(grade==='B'){if(state==='WIN')acc.bW++; if(state==='LOSS')acc.bL++;} else {if(state==='WIN')acc.cW++; if(state==='LOSS')acc.cL++;} return acc;},{aW:0,aL:0,bW:0,bL:0,cW:0,cL:0});
  const closed=frame?.session==='Market closed';
  const card=frame?.card;
  const activeCard=card&&now<card.ends_ms;
  const intervals=sessionIntervals(now);
  const day=intervals[0]?.day??Date.UTC(new Date(now).getUTCFullYear(),new Date(now).getUTCMonth(),new Date(now).getUTCDate());
  const nextEvent=[...intervals,...sessionIntervals(day+86400000)].flatMap(session=>[{at:session.start,name:session.name,kind:'OPENS'},{at:session.end,name:session.name,kind:'CLOSES'}]).filter(event=>event.at>now).sort((a,b)=>a.at-b.at)[0];
  const sessionTitle=closed?copy.rail.nextSession:(nextEvent?`${nextEvent.name.toUpperCase()} ${nextEvent.kind} IN`:copy.rail.nextClose);
  const sessionCountdown=nextEvent?railCountdown(nextEvent.at,now):(closed&&countdown==='00:00'?'--':countdown);
  const signalProcedure=buildSignalProcedure({price,tf,structure,objects,pools});
  const thesisLines=(thesis?.lines?.length?thesis.lines:signalProcedure.steps).map(normalizeSignalCopy).slice(0,5);
  const liveEntryRef=liveSignal?Number(liveSignal.entry_ref??(liveSignal.direction==='LONG'?liveSignal.entry_hi:liveSignal.entry_lo)):null;
  const liveRisk=liveSignal&&liveEntryRef!=null?Math.abs(liveSignal.target-liveEntryRef)/Math.max(0.000001,Math.abs(liveEntryRef-liveSignal.invalidation)):null;
  const liveGrade=liveSignal?.grade??'A';
  const liveGradeNotes=(liveSignal?.grade_notes??[]).join('  ');
  const pendingMinutes=liveSignal?.expires_ms?Math.max(0,Math.ceil((liveSignal.expires_ms-now)/60000)):null;
  const cWatch=!liveSignal&&!thesis?.dry_run?{tf:'M1/M5',direction:thesis?.bias==='BEARISH'?'SHORT':thesis?.bias==='BULLISH'?'LONG':utState==='SELL'?'SHORT':'LONG',grade:'C',grade_notes:[thesis?.bias&&thesis.bias!=='UNDEFINED'?'next UT flip':'bias confirmation'],zone_lo:null,zone_hi:null,stop:null,tp1:null,reward_r:null,distance_to_zone:null,min_r:null,first_fail:thesis?.bias&&thesis.bias!=='UNDEFINED'?null:'M15_BIAS_CONFIRM',passes:false}:null;
  const watch=(!liveSignal&&(thesis?.dry_run||cWatch))?(thesis?.dry_run??cWatch):null;
  return <aside className="retention-rail" data-broadcast-layer="L4" aria-label="Audience and market context">
    <div className="retention-top">
    {activeCard&&<section className={`rail-card answer-card ${card.kind==='THANKS'?'gift-card':''}`} aria-live="polite"><div className="rail-heading"><Handle name={card.handle}/><span>{card.kind==='THANKS'?'THANK YOU':'ASKED'}</span></div><p className="viewer-question">{card.question}</p><p>{card.answer}</p></section>}
    {!activeCard&&
    <section className="rail-card scenario-card"><div className="rail-heading"><span>{sessionTitle}</span><small>{copy.rail.utc}</small></div>
      <strong className="rail-countdown" aria-label="Session countdown">{sessionCountdown}</strong><div className="session-progress" aria-hidden="true"><span/></div>
    </section>}
    </div><div className="retention-middle">
    {structure?<p className="bias-pending trend-row"><span>{tf}</span><strong>{structure.trend}</strong><em>{structure.trend_since_ms?`since ${fmt.time(structure.trend_since_ms)}`:''}</em></p>:<p className="bias-pending">Bias: pending structure engine</p>}
    <section className={`rail-card live-signal-card signal-panel ${liveSignal?.state==='ACTIVE'?'is-active':liveSignal?.state==='PENDING'||watch?'is-pending':'is-scanning'}`} aria-live="polite"><div className="rail-heading"><span>{copy.rail.liveSignal}</span><small>{liveSignal?`${liveSignal.state} / ${liveSignal.direction}`:watch?`WATCH / ${watch.direction}`:thesis?.bias&&thesis.bias!=='UNDEFINED'?`${tf} ${thesis.bias}`:signalProcedure.direction}</small></div>{liveSignal?<div className="signal-levels"><strong>{liveSignal.timeframe??tf} {liveSignal.direction==='LONG'?'BUY':'SELL'} {liveGrade} <em>PAPER</em></strong><span>ENTRY <b>{fmt.range(liveSignal.entry_lo,liveSignal.entry_hi)}</b></span><span>SL <b>{fmt.price(liveSignal.invalidation)}</b></span><span>TP1 <b>{fmt.price(liveSignal.target)}</b></span><span>R <b>{liveRisk!=null?fmt.r(liveRisk):'--'}</b></span>{liveSignal.tp2!=null&&<span>TP2 <b>{fmt.price(liveSignal.tp2)}</b></span>}{liveGradeNotes&&<span>GRADE <b>{liveGradeNotes}</b></span>}<p className="signal-process-line"><b>{liveSignal.state==='PENDING'?'PENDING':'TRACKING'}</b>{liveSignal.state==='PENDING'?` waiting for price to enter the zone${pendingMinutes!=null?` / ${pendingMinutes}m left`:''}`:' updating SL / TP progress live'}</p></div>:watch?<div className="signal-levels"><strong>WATCH {watch.tf??tf} {watch.direction==='LONG'?'BUY':'SELL'} {watch.grade??'A'} <em>PAPER</em></strong>{watch.zone_lo!=null&&watch.zone_hi!=null?<span>ENTRY <b>{fmt.range(Number(watch.zone_lo),Number(watch.zone_hi))}</b></span>:<span>TRIGGER <b>{watch.grade==='C'?'next M1/M5 UT flip':'producer trigger'}</b></span>}{watch.stop!=null&&<span>SL <b>{fmt.price(Number(watch.stop))}</b></span>}{watch.tp1!=null&&<span>TP1 <b>{fmt.price(Number(watch.tp1))}</b></span>}{watch.reward_r!=null&&<span>R <b>{fmt.r(Number(watch.reward_r))}</b></span>}<p className="signal-process-line"><b>WATCH</b>{watch.grade==='C'?(watch.first_fail==='M15_BIAS_CONFIRM'?` after M15 bias confirms`: ` next M1/M5 UT flip (${thesis?.bias==='BEARISH'?'M15 bearish':'M15 bullish'})`):watch.passes?` if price returns / ${fmt.price(Number(watch.distance_to_zone))} away`:watch.first_fail==='R_MIN'?` R ${fmt.one(Number(watch.reward_r))} < ${fmt.one(Number(watch.min_r??1.5))} / target too close`:` waiting for ${String(watch.first_fail??'producer gate').replaceAll('_',' ').toLowerCase()}`}</p></div>:<div className="signal-process-list signal-procedure" aria-label="Signal execution process">{thesisLines.filter(step=>!/[A-Z]+_[A-Z0-9_]+/.test(step)&&!/0\.00 away/i.test(step)).map((step,index)=><span key={index} className={thesis?.stage==='NO_VALID_ZONE'&&index===2?'blocking':index<2?'passed':''}><b>{index+1}</b>{step}</span>)}</div>}</section>
    <section className="indicator-section" aria-label="Indicators"><div className="rail-heading"><span>{copy.rail.indicators}</span><small>{copy.rail.state}</small></div><div className="indicator-row"><strong>UT BOT</strong><b>{utState??copy.rail.waiting}</b><span>{utSince?`since ${utSince}`:copy.rail.waiting.toLowerCase()}</span></div></section>
    <KeyLevels price={price} objects={objects} pools={pools} weeklyOpen={weeklyOpen}/>
    <StructureTicker objects={objects}/>
    <Worklog entries={worklog} now={now}/>
    <section className="rail-comments" aria-live="polite"><div className="rail-heading"><span>LIVE COMMENTS</span><small>{comments.length?`${comments.length} visible`:copy.rail.waiting.toLowerCase()}</small></div>{comments.length?comments.slice(0,3).map(comment=><div className="rail-comment" key={comment.id}><bdi dir="auto">@{comment.name}</bdi><span>{comment.text}</span></div>):<p className="bias-pending">{copy.commentsWaiting}</p>}</section>
    </div>
    <section className="rail-card score-card" aria-label="Prediction scoreboard"><div className="rail-heading"><span>{copy.rail.scoreboard}</span><small>{copy.rail.lossesStay}</small></div>
      <nav className="score-windows" aria-label="Scoreboard window">{(['last_20','today','all_time'] as const).map(value=><button key={value} aria-pressed={window===value} onClick={()=>setWindow(value)}>{value==='last_20'?copy.rail.last20:value==='today'?copy.rail.today:copy.rail.allTime}</button>)}</nav>
      <div className="score-matrix">
        <span><b>{copy.score.win}</b><strong>{stats?.wins??0}</strong></span><span><b>{copy.score.loss}</b><strong>{stats?.losses??0}</strong></span><span><b>{copy.score.scratch}</b><strong>{stats?.scratch??0}</strong></span><span><b>{copy.score.hit}</b><strong>{resolved>=20&&stats?.hit_rate!=null?`${Math.round(stats.hit_rate*100)}%`:(stats?.wins??0)+' / '+resolved}</strong></span>
        <span><b>{copy.score.never}</b><strong>{stats?.never_triggered??0}</strong></span><span><b>{copy.score.cancelled}</b><strong>{stats?.cancelled??0}</strong></span><span><b>{copy.score.void}</b><strong>{stats?.void_data??0}</strong></span><span><b>{copy.score.expect}</b><strong>{stats?.expectancy!=null?resolved>=20?fmt.r(stats.expectancy):'n<20':'--'}</strong></span>
      </div><p className="score-footer"><span>{copy.score.produced} <b>{stats?.produced??0}</b></span><span>{copy.score.triggered} <b>{stats?.triggered??0}</b></span><span>{copy.score.resolved} <b>{resolved}</b></span></p><p className="score-grade-line">A {gradeRows.aW}W {gradeRows.aL}L  B {gradeRows.bW}W {gradeRows.bL}L  C {gradeRows.cW}W {gradeRows.cL}L</p><p className="score-grade-line">Plans today {planScore.total}  A reached {planScore.a}  B hit {planScore.b}  replaced {planScore.replaced}</p>
      {rows.length?<div className="score-results">{rows.map(row=><div key={row.call.id}><details><summary><span>{displayState(row.call.kind)}  {displayState(row.call.state)}{row.ambiguous?'  ambiguous':''}{row.call.gap_skipped?'  gap skipped':''}</span></summary><p>{row.call.reason}</p><p>{displayState(row.cancellation_reason??row.resolution_reason)}</p><p>{row.call.direction} / entry {fmt.range(row.call.entry_lo,row.call.entry_hi)} / target {fmt.price(row.call.target)} / invalidation {fmt.price(row.call.invalidation)}</p><p>Created {fmt.utcTime(row.call.created_ms)} / deadline {fmt.utcTime(row.call.expires_ms)}</p><p>Evaluation {fmt.utcTime(row.call.eval_from_ms!)}-{fmt.utcTime(row.call.eval_to_ms!)} / created day {row.call.created_trading_day} / resolved day {row.call.resolved_trading_day??'pending'}</p></details></div>)}</div>:<p className="context-note">No calls recorded</p>}
    </section>
    {frame?.supporters?.length?<div className="supporters"><small>SUPPORTERS / ACCESS STAYS FREE</small>{frame.supporters.map((name,i)=><Handle key={`${name}-${i}`} name={name}/>)}</div>:null}
  </aside>;
}



