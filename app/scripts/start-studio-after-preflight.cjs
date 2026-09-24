const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 const page=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://')).find(p=>p.url().includes('index.html'));
 if(!page) throw new Error('No page');
 const buttons=await page.locator('button').allTextContents();
 console.log(JSON.stringify(buttons));
 for(const name of ['Continue','Start','Open studio','Enter studio','OK']){
   const btn=page.getByRole('button',{name:new RegExp(name,'i')});
   if(await btn.count()){ await btn.first().click().catch(()=>{}); await page.waitForTimeout(8000); break; }
 }
 console.log((await page.locator('body').innerText()).slice(0,800));
 await browser.close();
})();
