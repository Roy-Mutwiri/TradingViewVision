const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 let page=browser.contexts()[0].pages()[0];
 for(let i=0;i<12;i++){
  await page.waitForTimeout(3000);
  const pages=browser.contexts().flatMap(c=>c.pages());
  page=pages[pages.length-1];
  const text=await page.locator('body').innerText().catch(()=> '');
  if(/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text))break;
  const connect=page.getByRole('button',{name:/Connect/i}).first();
  if(await connect.count().catch(()=>0)) await connect.click().catch(()=>{});
  const enter=page.getByRole('button',{name:/Enter Studio/i}).first();
  if(await enter.count().catch(()=>0)) await enter.click().catch(()=>{});
 }
 const m15=page.getByRole('button',{name:/M15/i}).first();
 if(await m15.count().catch(()=>0)) await m15.click().catch(()=>{});
 await page.waitForTimeout(4000);
 const text=await page.locator('body').innerText().catch(()=> '');
 await page.screenshot({path:'../runtime/ui-proof/honesty-step2-dry-run-app-running.png',fullPage:true});
 fs.writeFileSync('../runtime/ui-proof/honesty-step2-dry-run-app-running.txt',text);
 console.log(JSON.stringify({hasStudio:/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text),head:text.slice(0,500)},null,2));
 await browser.close();
})();
