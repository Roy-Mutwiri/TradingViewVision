const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 let page=browser.contexts()[0].pages()[0];
 for(let i=0;i<6;i++){
   await page.waitForTimeout(5000);
   const text=await page.locator('body').innerText().catch(e=>'');
   if(/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text))break;
   const connect=page.getByRole('button',{name:/Connect/i}).first();
   if(await connect.count().catch(()=>0)) await connect.click().catch(()=>{});
   const enter=page.getByRole('button',{name:/Enter Studio/i}).first();
   if(await enter.count().catch(()=>0)) await enter.click().catch(()=>{});
 }
 const m15=page.getByRole('button',{name:/M15/i}).first();
 if(await m15.count().catch(()=>0)) await m15.click().catch(()=>{});
 await page.waitForTimeout(3000);
 await page.screenshot({path:'../runtime/ui-proof/honesty-step1-app-running.png',fullPage:true});
 fs.writeFileSync('../runtime/ui-proof/honesty-step1-app-running.txt',await page.locator('body').innerText().catch(e=>''));
 await browser.close();
})();
