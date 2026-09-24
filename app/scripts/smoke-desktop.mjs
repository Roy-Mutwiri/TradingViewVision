/** Real Electron/preload/worker smoke test; never submits a broker password. */
import { _electron as electron, expect } from '@playwright/test';
import { resolve } from 'node:path';
const desktop = await electron.launch({args:[resolve(import.meta.dirname,'..')]});
try {
  const page = await desktop.firstWindow();
  await expect(page.getByLabel('Account login',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:/Investor/})).toHaveAttribute('aria-pressed','true');
  const result = await page.evaluate(async()=> {
    return window.oracle.connect({login:81740106,password:'fixture-no-real-credential',passwordType:'investor',server:'ExnessKE-MT5Trial10',remember:false,terminalPath:'Z:/oracle-no-terminal/terminal64.exe'});
  });
  if(result.error?.code !== 'TERMINAL_NOT_FOUND') throw new Error('Expected path error from real worker');
  const denied = await page.evaluate(async()=> {try {await window.oracle.enterStudio();return false;}catch{return true;}});
  if(!denied) throw new Error('Unauthenticated Studio entry must be denied');
  const studioDenied = await page.evaluate(async()=> {try {await window.oracle.session();return false;}catch{return true;}});
  if(!studioDenied) throw new Error('Login window must not access Studio IPC');
  const chartDenied=await page.evaluate(async()=>{try{await window.oracle.chartSubscribe('M5');return false;}catch{return true;}});
  if(!chartDenied)throw new Error('Login window must not access chart data');
  if(desktop.windows().length !== 1) throw new Error('Only login may exist before auth');
  console.log('Desktop smoke passed: sandboxed preload, local worker, terminal-path error, and both Studio entry/IPC guards.');
} finally {await desktop.close();}
