const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 const out=path.resolve('..','runtime','ui-proof','notebook-mode');fs.mkdirSync(out,{recursive:true});
 let page;
 for(let i=0;i<30;i++){
   const pages=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://'));
   page=pages[pages.length-1];
   const text=page?await page.locator('body').innerText().catch(()=> ''):'';
   if(/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text))break;
   await new Promise(r=>setTimeout(r,1000));
 }
 if(!page) throw new Error('no page');
 const results=[];
 for(const tf of ['M5','M15','M30','H1']){
   await page.getByRole('button',{name:tf,exact:true}).click().catch(()=>{});
   await page.waitForTimeout(8000);
   const audit=await page.evaluate(()=>({chart:typeof window.oracleChartAudit==='function'?window.oracleChartAudit():null, labels:typeof window.oracleLabelAudit==='function'?window.oracleLabelAudit():[]}));
   await page.screenshot({path:path.join(out,`notebook-${tf}.png`),fullPage:true});
   results.push({tf,chart_density:await page.evaluate(()=>window.__oracleLastFrame?.chart_density),labels:audit.labels.length,rendered:audit.labels.filter(x=>!x.dropped).length,dropped:audit.labels.filter(x=>x.dropped).length,chart:audit.chart});
 }
 await page.screenshot({path:path.join(out,'notebook-final-live.png'),fullPage:true});
 fs.writeFileSync(path.join(out,'notebook-audit.json'),JSON.stringify({results},null,2));
 console.log(JSON.stringify({out:'runtime/ui-proof/notebook-mode',results},null,2));
 await browser.close();
})();
