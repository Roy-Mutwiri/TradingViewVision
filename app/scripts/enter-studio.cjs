const {chromium}=require('playwright');
async function clickAny(page,patterns){
 const buttons=await page.locator('button').all();
 for(const button of buttons){
   const label=(await button.innerText().catch(()=> '')).trim();
   if(patterns.some(re=>re.test(label))){await button.click().catch(()=>{});return label;}
 }
 return null;
}
(async()=>{
 let browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 let pages=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://'));
 let page=pages[pages.length-1];
 let clicked=[];
 for(let step=0;step<3&&page;step++){
   const text=await page.locator('body').innerText().catch(()=> '');
   if(/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text))break;
   const label=await clickAny(page,[/^Connect$/i,/Enter Studio/i,/continue/i,/launch/i,/start/i]);
   if(label)clicked.push(label);
   await page.waitForTimeout(6000).catch(()=>{});
   pages=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://'));
   page=pages[pages.length-1];
 }
 const text=page?await page.locator('body').innerText().catch(()=> ''):'';
 console.log(JSON.stringify({clicked,pages:pages.length,hasStudio:/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text),head:text.slice(0,600)},null,2));
 await browser.close();
})();
