import {test,expect,type Page} from '@playwright/test';
import {writeFile} from 'node:fs/promises';

async function fixture(page:Page){
  await page.addInitScript(()=>{
    const data:any=window;data.__subscriptions=[];
    data.__labelPaint=[];
    const originalText=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText=function(...args:Parameters<typeof originalText>){
      if(['?','Buy','Sell'].includes(args[0]))data.__labelPaint.push({text:args[0],ink:this.fillStyle,alpha:this.globalAlpha,font:this.font});
      return originalText.apply(this,args);
    };
    const now=1789684942000;
    const steps:Record<string,number>={M1:60000,M5:300000,M15:900000,M30:1800000,H1:3600000,H4:14400000,D1:86400000,W1:604800000};
    data.__bars=(tf:string)=>{
      const step=steps[tf],end=Math.floor(now/step)*step;
      return Array.from({length:2000},(_,i)=>{
        const t=end-(1999-i)*step;
        const day=new Date(t).getUTCDay();
        if(day===6)return null;
        const o=4350+Math.sin(i/17)*8+Math.sin(i/43)*10;
        return {symbol:'XAUUSD',tf,t_open_ms:t,o,h:o+2.5,l:o-2,c:o+Math.cos(i/13),tick_volume:417,source:'mt5',complete:i!==1999,digits:2};
      }).filter(Boolean);
    };
    data.oracle={
      mode:async()=> 'studio',session:async()=>({tradeMode:'DEMO',clockProven:false,tradingCapable:false,state:'connected'}),
      onSession:()=>()=>{},switchAccount:async()=>{},
      onChart:(cb:any)=>{data.__chart=cb;return()=>{};},
      chartSubscribe:async(tf:string)=>{
        data.__subscriptions.push(tf);const bars=data.__bars(tf);const end=bars.at(-1).t_open_ms;
        const closure=bars.find((b:any,i:number)=>i>0&&b.t_open_ms-bars[i-1].t_open_ms>steps[tf]);
        const previous=closure?bars[bars.indexOf(closure)-1]:null;
        return {kind:'snapshot',snapshot:{symbol:'XAUUSD',tf,bars,clockVersion:1},quality:{state:'OK',staleness_ms:400,spread_points:14,detail:'data.live'},now_ms:now,next_close_ms:end+steps[tf],closures:closure?[{start_ms:previous.t_open_ms+steps[tf],end_ms:closure.t_open_ms,recurring:true}]:[],calendar_detail:'Derived from 180 days of observed M1 (synthetic test fixture)'};
      },
      chartDebug:async()=>({resolved_symbol:'XAUUSDz',bars:data.__bars(data.__subscriptions.at(-1)||'M5').map((b:any)=>({t_open_ms:b.t_open_ms,t_broker_ms:b.t_open_ms,offset_s:0,clock_version:1})),corrections:1,checked:30,last_tick_ms:now-400,spread_points:14,detail:'Synthetic fixture; not a broker proof'}),
    };
  });
  await page.goto('/');
  await expect(page.getByText('XAUUSDz',{exact:true})).toBeVisible();
  await page.keyboard.press('F9');
}

test('typed symbol failure is actionable and zero candles show NO DATA',async({page})=>{
  await fixture(page);
  await page.evaluate(()=>{
    const data:any=window;
    data.oracle.chartSubscribe=async()=>{throw {code:'SYMBOL_UNRESOLVED',message:'Select an available spot gold symbol in preflight.',detail:{candidates:['XAUUSDz'],bars_found:0},recoverable:true};};
  });
  await page.getByRole('button',{name:'M1',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Select an available spot gold symbol in preflight.');
  await expect(page.getByTestId('data-quality')).toHaveText('NO DATA');
  await page.keyboard.press('Backquote');
  await expect(page.getByLabel('Chart diagnostics')).toContainText('SYMBOL_UNRESOLVED');
  await expect(page.getByLabel('Chart diagnostics')).toContainText('candidates');
  await expect(page.getByLabel('Chart diagnostics')).toContainText('XAUUSDz');
});

test('live chart, UTC countdown, timeframe refetch and operator drawer',async({page})=>{
  const exceptions:string[]=[];page.on('pageerror',e=>exceptions.push(e.message));
  await fixture(page);
  await expect(page.getByTestId('data-quality')).toHaveText('OK');
  await expect(page.getByLabel('Candle close countdown')).toHaveText(/0[0-5]:\d{2}/);
  for(const tf of ['M1','H1','M5']){await page.getByRole('button',{name:tf,exact:true}).click();await expect(page.getByRole('button',{name:tf,exact:true})).toHaveAttribute('aria-pressed','true');}
  expect(await page.evaluate(()=>(window as any).__subscriptions)).toEqual(['M5','M1','H1','M5']);
  await page.keyboard.press('Backquote');
  await expect(page.getByLabel('Chart diagnostics')).toBeVisible();
  await expect(page.getByLabel('Chart diagnostics')).toContainText('offset +00:00 · clock v1');
  await page.getByTestId('live-chart').hover({position:{x:450,y:80}});
  await expect(page.locator('.debug-columns section').first()).toContainText('t_open_ms');
  expect(await page.locator('[data-broadcast-layer] [data-operator-only]').count()).toBe(0);
  expect(exceptions).toEqual([]);
});

test('historical broker correction redraws the candle and appears in debug log',async({page})=>{
  await fixture(page);await page.keyboard.press('Backquote');
  await page.evaluate(()=>{
    const data:any=window;const bar=data.__bars('M5').at(-10);
    data.__chart({kind:'correction',update:{symbol:'XAUUSD',tf:'M5',bar:{...bar,c:bar.o+1.2}},quality:{state:'OK',staleness_ms:400,spread_points:14,detail:'data.live'},now_ms:1789684942000,next_close_ms:data.__bars('M5').at(-1).t_open_ms+300000,closures:[],calendar_detail:'Derived calendar'});
  });
  await expect(page.getByLabel('Broker corrections')).toContainText('M5 broker correction');
  await expect(page.getByLabel('Chart diagnostics')).toContainText('1 / 30 checked');
});

test('chart renders candles and session whitespace in both themes',async({page})=>{
  await fixture(page);await expect(page.locator('.chart-canvas canvas').first()).toBeVisible();
  for(const theme of ['dark','light']){
    await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
    await expect(page.getByTestId('live-chart')).toHaveScreenshot(`candles-${theme}.png`,{animations:'disabled'});
    if(theme==='dark')await page.getByRole('button',{name:'Toggle theme'}).click();
  }
});

test('1500 visible candles continue updating without renderer exceptions',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await fixture(page);
  const cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
  const before=await cdp.send('Performance.getMetrics');
  const metrics=await page.evaluate(async()=>{
    const data:any=window;const start=performance.now();const samples:number[]=[];let previous=start;
    for(let i=0;i<120;i++){
      await new Promise<void>(resolve=>requestAnimationFrame(()=>{const now=performance.now();samples.push(now-previous);previous=now;resolve();}));
      if(i%6===0){const bar=data.__bars('M5').at(-1);data.__chart({kind:'update',update:{symbol:'XAUUSD',tf:'M5',bar:{...bar,c:bar.o+Math.sin(i)}},quality:{state:'OK',staleness_ms:100,spread_points:14,detail:'data.live'},now_ms:1789684942000,next_close_ms:bar.t_open_ms+300000});}
    }
    return {frames:samples.length,elapsed:performance.now()-start,p95:samples.sort((a,b)=>a-b)[114]};
  });
  const after=await cdp.send('Performance.getMetrics');
  const task=(v:any)=>v.metrics.find((m:any)=>m.name==='TaskDuration').value;
  const taskCpuPct=(task(after)-task(before))/(metrics.elapsed/1000)*100;
  await writeFile('test-results/synthetic-chart-performance.json',JSON.stringify({...metrics,taskCpuPct,synthetic:true,scope:'Chromium renderer main-thread TaskDuration; not the live terminal soak'},null,2));
  expect(metrics.frames).toBe(120);expect(metrics.p95).toBeLessThan(34);expect(taskCpuPct).toBeLessThan(25);expect(errors).toEqual([]);
  // Synthetic smoke only: live CPU and the 30-minute soak are separate acceptance gates.
});

test('tick quote is independent of candle close and calendar pending is distinct',async({page})=>{
  await fixture(page);
  await page.evaluate(()=>{
    const data:any=window;
    data.__chart({kind:'status',quote:{symbol:'XAUUSD',bid:4399.21,ask:4399.35,t_ms:1789684941900,source:'mt5'},objects:[],indicator_enabled:true,
      quality:{state:'CALENDAR_PENDING',staleness_ms:100,spread_points:14,detail:'data.calendar_pending'},now_ms:1789684942000});
    data.oracle.chartDebug=async()=>({resolved_symbol:'XAUUSDz',bars:[],corrections:0,checked:0,last_tick_ms:1789684941900,spread_points:14,detail:'Pending calendar',switch_ms:42.5,
      gateway:{queue_depth:2,tick_latency_ms:21},missing_ranges:[],indicator:{enabled:true,warmup_bars:30,provisional:4,confirmed:3,removed:1,conversion_rate:.75}});
  });
  await expect(page.getByTestId('bid-price')).toHaveText('4,399.21');
  await expect(page.locator('.price-zone')).toContainText('Ask 4399.35');
  await expect(page.getByLabel('Tick age')).toHaveClass(/fresh/);
  await expect(page.getByTestId('data-quality')).toHaveText('CALENDAR PENDING');
  await expect(page.getByText('indicator · UT Bot',{exact:true})).toBeVisible();
  await page.keyboard.press('Backquote');
  await expect(page.getByLabel('Chart diagnostics')).toContainText('engine 42.5ms');
  await expect(page.getByLabel('Chart diagnostics')).toContainText('Warm-up: first 30 bars');
  await expect(page.getByLabel('Chart diagnostics')).toContainText('conversion 75.0%');
});

test('engine labels render as semibold filled chips including provisional signals',async({page})=>{
  await fixture(page);
  await page.evaluate(()=>{
    const data:any=window,bars=data.__bars('M5'),buy=bars.at(-10),sell=bars.at(-7),forming=bars.at(-1);
    const object=(bar:any,direction:string,provisional=false)=>({id:`label-${bar.t_open_ms}`,object_hash:'fixture',layer:'L2',shape:'LABEL',points:[{t_ms:bar.t_open_ms,price:direction==='BULLISH'?bar.l:bar.h}],style:{token:provisional?'utbot.provisional':direction==='BULLISH'?'utbot.buy':'utbot.sell'},text_key:provisional?'indicator.utbot.provisional':direction==='BULLISH'?'indicator.utbot.buy':'indicator.utbot.sell',text_args:{direction},reason:'Synthetic rendering fixture'});
    data.__chart({kind:'status',objects:[object(buy,'BULLISH'),object(sell,'BEARISH'),object(forming,'BULLISH',true)],indicator_enabled:true,language:'en',quote:{symbol:'XAUUSD',bid:forming.c,ask:forming.c+.14,t_ms:1789684942000,source:'mt5'},quality:{state:'CALENDAR_PENDING',staleness_ms:0,spread_points:14,detail:'data.calendar_pending'},now_ms:1789684942000});
  });
  for(const theme of ['dark','light']){
    await expect.poll(()=>page.evaluate(()=>(window as any).__labelPaint.some((p:any)=>p.text==='Buy'&&p.ink==='#080b10'&&p.alpha===1&&p.font.startsWith('600 12px')))).toBe(true);
    await expect(page.getByTestId('live-chart')).toHaveScreenshot(`utbot-labels-${theme}.png`,{animations:'disabled'});
    if(theme==='dark')await page.getByRole('button',{name:'Toggle theme'}).click();
  }
});
