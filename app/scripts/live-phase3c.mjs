/** Real local MT5 latency probe; existing keychain profile, no credentials in Node. */
import {_electron as electron,expect} from '@playwright/test';
import {resolve} from 'node:path';
import {mkdir,writeFile,mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
if(process.env.ORACLE_RUN_WINDOWS_LIVE!=='1')throw new Error('Set ORACLE_RUN_WINDOWS_LIVE=1 for the real local terminal probe.');
const isolated=await mkdtemp(resolve(tmpdir(),'oracle-phase3c-'));
const desktop=await electron.launch({args:[resolve(import.meta.dirname,'..')],env:{...process.env,ORACLE__DATA__STORE_PATH:JSON.stringify(resolve(isolated,'candles.duckdb'))}});
const errors=[];
try{
  const login=await desktop.firstWindow();await login.waitForFunction(()=>!!window.oracle);
  const result=await login.evaluate(()=>window.oracle.connectProfile({login:81740106,server:'ExnessKE-MT5Trial10',passwordType:'master'}));
  if(result.error)throw new Error(`${result.error.code}: ${result.error.message}`);
  const opened=desktop.waitForEvent('window');
  await login.evaluate(()=>window.oracle.enterStudio()).catch(error=>{if(!/closed/.test(error.message))throw error;});
  const page=await opened;page.on('pageerror',e=>errors.push(e.message));
  await expect(page.getByText('XAUUSDz',{exact:true})).toBeVisible({timeout:30000});
  await page.evaluate(()=>{
    window.__latency={quotes:[],last:0,backfill:[],faults:[],quality:null};
    window.oracle.onQuote(packet=>{
      const state=window.__latency;if(packet.received_ms===state.last)return;state.last=packet.received_ms;
      state.quotes.push({delivery_ms:Date.now()-packet.received_ms,event_age_ms:Date.now()-packet.quote.t_ms,t_ms:packet.quote.t_ms,bid:packet.quote.bid});
    });
    window.oracle.onChartError(error=>window.__latency.faults.push(error));
    window.oracle.onChart(frame=>{
      const state=window.__latency;
      state.quality=frame.quality;
      if(frame.kind==='status')state.backfill.push(frame.calendar_detail);
    });
  });
  await page.waitForTimeout(15000);
  const switches=[];
  for(const tf of ['M15','H1','M5','M15','H1','M5']){
    await page.getByRole('button',{name:tf,exact:true}).click();
    await expect(page.getByRole('button',{name:tf,exact:true})).toHaveAttribute('aria-pressed','true');
    await expect(page.locator('.chart-message')).toHaveCount(0,{timeout:30000});
    await page.waitForTimeout(200);
    const measured=await page.evaluate(async(tf)=>{const start=performance.now();const frame=await window.oracle.chartSubscribe(tf);return {tf,ipc_ms:performance.now()-start,store_ms:frame.switch_ms,bars:frame.snapshot.bars.length,objects:frame.objects.length};},tf);
    switches.push(measured);
  }
  await page.waitForTimeout(5000);
  const latency=await page.evaluate(()=>window.__latency);
  const debug=await page.evaluate(()=>window.oracle.chartDebug());
  await page.keyboard.press('Backquote');
  const dir=resolve(import.meta.dirname,'../../artifacts/phase3c');await mkdir(dir,{recursive:true});
  await page.screenshot({path:resolve(dir,'live-latency.png')});
  const report={live:true,passwordType:'master',tradeMode:'DEMO',symbol:debug.resolved_symbol,switches,quotes:latency.quotes,backfill:latency.backfill,quality:latency.quality,missing_ranges:debug.missing_ranges,gateway:debug.gateway,indicator:debug.indicator,engineFaults:latency.faults,rendererExceptions:errors,timestamp:new Date().toISOString()};
  await writeFile(resolve(dir,'live-latency.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({switches,quotes:latency.quotes.length,maxDeliveryMs:Math.max(...latency.quotes.map(q=>q.delivery_ms)),maxEventAgeMs:Math.max(...latency.quotes.map(q=>q.event_age_ms)),gateway:debug.gateway,engineFaults:latency.faults,rendererExceptions:errors}));
  if(errors.length)throw new Error('Renderer exceptions during live probe');
  if(latency.faults.length)throw new Error('Engine faults during live probe');
  if(!latency.quotes.length)throw new Error('No real ticks observed; repeat during an active session');
  if(switches.some(s=>s.bars>=2000&&(s.store_ms>=150||s.ipc_ms>=150)))throw new Error('Warm store switch exceeded 150ms');
  if(latency.quotes.some(q=>q.delivery_ms>250))throw new Error('Quote delivery exceeded 250ms');
}finally{await desktop.close();}
