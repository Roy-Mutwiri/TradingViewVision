const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 const pages=browser.contexts().flatMap(c=>c.pages());
 const page=pages[pages.length-1];
 await page.waitForTimeout(5000);
 const text=await page.locator('body').innerText().catch(e=>'');
 await page.screenshot({path:'../runtime/ui-proof/honesty-step1-app-running.png',fullPage:true});
 fs.writeFileSync('../runtime/ui-proof/honesty-step1-app-running.txt',text);
 console.log(JSON.stringify({pages:pages.length,hasStudio:/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text),head:text.slice(0,300)},null,2));
 await browser.close();
})();
