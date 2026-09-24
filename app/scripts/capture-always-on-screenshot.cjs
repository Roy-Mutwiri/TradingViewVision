const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 const page=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://')).find(p=>p.url().includes('index.html'));
 if(!page) throw new Error('No page');
 await page.waitForTimeout(2000);
 const out=path.resolve('..','runtime','ui-proof','always-on-signals');fs.mkdirSync(out,{recursive:true});
 await page.screenshot({path:path.join(out,'step0-final-live.png'),fullPage:false});
 console.log('runtime/ui-proof/always-on-signals/step0-final-live.png');
 await browser.close();
})();
