/** Explicit local live verification using the already-saved profile; no secret enters Node. */
import {_electron as electron,expect} from '@playwright/test';
import {resolve} from 'node:path';
import {mkdir,writeFile,mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
if(process.env.ORACLE_RUN_WINDOWS_LIVE!=='1')throw new Error('Set ORACLE_RUN_WINDOWS_LIVE=1 to verify the real saved terminal profile.');
const isolated=await mkdtemp(resolve(tmpdir(),'oracle-bootstrap-'));
const desktop=await electron.launch({args:[resolve(import.meta.dirname,'..')],env:{...process.env,ORACLE__DATA__STORE_PATH:JSON.stringify(resolve(isolated,'candles.duckdb'))}});
const errors=[];
try{
  const login=await desktop.firstWindow();await login.waitForFunction(()=>!!window.oracle);
  const report=await login.evaluate(()=>window.oracle.connectProfile({login:81740106,server:'ExnessKE-MT5Trial10',passwordType:'master'}));
  if(report.error)throw new Error(`${report.error.code}: ${report.error.message}`);
  const opened=desktop.waitForEvent('window');
  await login.evaluate(()=>window.oracle.enterStudio()).catch(error=>{if(!/closed/.test(error.message))throw error;});
  const page=await opened;page.on('pageerror',error=>errors.push(error.message));
  const typed=await page.evaluate(async()=>{try{await window.oracle.chartSubscribe('MN1');return null;}catch(error){return {code:error.code,message:error.message,detail:error.detail};}});
  if(typed?.code!=='TF_UNSUPPORTED'||typed.detail.tf!=='MN1')throw new Error('Typed IPC errors must retain code, message and detail across the real preload');
  await expect(page.getByText('XAUUSDz',{exact:true})).toBeVisible({timeout:30000});
  await expect(page.getByTestId('clock-status')).toHaveText('Clock unproven');
  await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
  const frame=await page.evaluate(()=>window.oracle.chartSubscribe('M5'));
  await expect(page.getByTestId('data-quality')).not.toHaveText('NO DATA',{timeout:30000});
  if(frame.snapshot.bars.length!==2000)throw new Error(`Expected 2000 M5 candles; got ${frame.snapshot.bars.length}`);
  if(!frame.snapshot.bars.slice(0,-1).every(bar=>bar.clock_confidence==='ASSUMED'))throw new Error('Fresh historical candles must be ASSUMED');
  await page.keyboard.press('Backquote');
  await page.getByTestId('live-chart').hover({position:{x:450,y:100}});
  await expect(page.getByLabel('Chart diagnostics')).toContainText('clock ASSUMED');
  await expect(page.getByLabel('Candle close countdown')).not.toHaveText('00:00');
  const before=await page.getByLabel('Candle close countdown').innerText();
  await page.waitForTimeout(2500);
  const after=await page.getByLabel('Candle close countdown').innerText();
  if(before===after)throw new Error('Live countdown must advance');
  if(errors.length)throw new Error(errors.join('\n'));
  const dir=resolve(import.meta.dirname,'../../artifacts/phase3b');await mkdir(dir,{recursive:true});
  await page.screenshot({path:resolve(dir,'live-bootstrap.png')});
  await writeFile(resolve(dir,'live-bootstrap.json'),JSON.stringify({live:true,login:81740106,server:'ExnessKE-MT5Trial10',passwordType:'master',tradeMode:'DEMO',symbol:frame.resolved_symbol,bars:frame.snapshot.bars.length,clockVersion:frame.snapshot.clockVersion,historicalConfidence:'ASSUMED',clockProven:false,countdownBefore:before,countdownAfter:after,rendererExceptions:errors,timestamp:new Date().toISOString()},null,2));
  console.log('Live Electron bootstrap passed: 2000 M5 candles, ASSUMED history, XAUUSDz, DEMO, clock unproven, advancing countdown, and no renderer exceptions.');
}finally{await desktop.close();}
