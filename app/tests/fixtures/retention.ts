import type {Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';

export async function rehearsal(page:Page) {
  const replay=JSON.parse(await readFile('../engine/tests/fixtures/retention_rehearsal.json','utf8'));
  const callboard=JSON.parse(await readFile('../engine/tests/fixtures/analysis_board.json','utf8'));
  await page.addInitScript(({replay,callboard}:any)=>{
    const w:any=window;w.__replay=replay;const start=replay.frames[0].now_ms;
    w.__callboard=callboard;
    const step:Record<string,number>={M1:60000,M5:300000,M15:900000,M30:1800000,H1:3600000,H4:14400000,D1:86400000,W1:604800000};
    w.__bars=(tf:string)=>Array.from({length:2000},(_,i)=>{const t=Math.floor(start/step[tf])*step[tf]-(1999-i)*step[tf],o=4346+Math.sin(i/23)*7;return {symbol:'XAUUSD',tf,t_open_ms:t,o,h:o+3,l:o-3,c:o+Math.cos(i/17),tick_volume:417,source:'synthetic',complete:i<1999,digits:3};});
    const quality={state:'CALENDAR_PENDING',staleness_ms:200,spread_points:50,detail:'data.calendar_pending'};
    w.__frame=(tf:string)=>{const bars=w.__bars(tf);return {kind:'snapshot',resolved_symbol:'XAUUSDz',snapshot:{symbol:'XAUUSD',tf,bars,clockVersion:1},now_ms:start,next_close_ms:bars.at(-1).t_open_ms+step[tf],bar_duration_ms:step[tf],quality,calendar_detail:'Calendar history available: 100,044 M1 bars',refinement_pending:'Clock transition derivation pending: independent UTC feed is not configured',objects:[],language:'en',switch_ms:42};};
    w.oracle={mode:async()=> 'studio',session:async()=>({tradeMode:'DEMO',clockProven:false,tradingCapable:true,state:'connected'}),onSession:()=>()=>{},studioSettings:async()=>({mode:'broadcast',language:'en'}),switchAccount:async()=>{},
      onChart:(cb:any)=>{w.__chart=cb;return()=>{};},onQuote:(cb:any)=>{w.__quote=cb;return()=>{};},onChartError:(cb:any)=>{w.__error=cb;return()=>{};},
      chartSubscribe:async(tf:string)=>{w.__tf=tf;return w.__frame(tf);},chartDebug:async()=>({resolved_symbol:'XAUUSDz',bars:[],corrections:2,checked:30,last_tick_ms:start,spread_points:50,detail:'100,044 M1 bars; clock v1',switch_ms:42,gateway:{queue_depth:1,tick_latency_ms:12},missing_ranges:[]}),
      retentionState:async()=>replay.frames[0],onRetention:(cb:any)=>{w.__retention=cb;return()=>{};},chartIndicator:async()=>w.__frame(w.__tf),
    };
    w.__emit=(index:number)=>{
      const value=replay.frames[index];w.__retention?.(value);const tf=w.__tf??'M5';const t=Math.floor(value.now_ms/step[tf])*step[tf];const c=4346+Math.sin(index/31)*4+index/300;
      w.__chart?.({kind:'update',resolved_symbol:'XAUUSDz',update:{symbol:'XAUUSD',tf,bar:{...w.__bars(tf).at(-1),t_open_ms:t,c,h:4352,l:4340,complete:false}},now_ms:value.now_ms,next_close_ms:t+step[tf],bar_duration_ms:step[tf],quality,objects:[],language:'en',calendar_detail:'Calendar history available: 100,044 M1 bars',refinement_pending:'Clock transition derivation pending: independent UTC feed is not configured'});
      w.__quote?.({quote:{symbol:'XAUUSD',bid:c,ask:c+.05,t_ms:value.now_ms-100,source:'synthetic'},now_ms:value.now_ms,received_ms:value.now_ms,digits:3,spread_points:50});
    };
  },{replay,callboard});
  await page.goto('/');
  await page.getByTestId('account-mode').waitFor();
  return replay;
}
