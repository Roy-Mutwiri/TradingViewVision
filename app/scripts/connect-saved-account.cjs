const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 const page=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://')).find(p=>p.url().includes('index.html'));
 if(!page) throw new Error('No page');
 await page.getByRole('button',{name:/Connect/i}).click().catch(async()=>{await page.locator('button').filter({hasText:/Connect/i}).first().click()});
 await page.waitForTimeout(60000);
 console.log(await page.locator('body').innerText().then(t=>t.slice(0,500)).catch(e=>String(e)));
 await browser.close();
})();
