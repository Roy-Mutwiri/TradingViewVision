const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 let pages=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://'));
 let page=pages[pages.length-1];
 await page.waitForTimeout(3000);
 let text=await page.locator('body').innerText().catch(()=> '');
 if(!/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text)){
   const buttons=await page.locator('button').all();
   for(const button of buttons){
     const label=await button.innerText().catch(()=> '');
     if(/^Connect$|Enter Studio|continue|launch|start/i.test(label)){await button.click().catch(()=>{});break;}
   }
   await page.waitForTimeout(7000).catch(()=>{});
   pages=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://'));
   page=pages[pages.length-1];
   text=await page.locator('body').innerText().catch(()=> '');
 }
 for(let i=0;i<24;i++){
   const ready=await page.evaluate(()=>{
     const text=document.body.innerText;
     const labels=typeof window.oracleLabelAudit==='function'?window.oracleLabelAudit():[];
     const chart=typeof window.oracleChartAudit==='function'?window.oracleChartAudit():null;
     return !/Preparing chart|Chart paused/.test(text)&&!!chart?.visible_range&&labels.length>0;
   }).catch(()=>false);
   if(ready)break;
   await page.waitForTimeout(2500);
 }
 await page.screenshot({path:'../runtime/ui-proof/honesty-step5-visual-fixes.png',fullPage:true});
 const audit=await page.evaluate(()=>{
   const labelAudit=typeof window.oracleLabelAudit==='function'?window.oracleLabelAudit():[];
   const chartAudit=typeof window.oracleChartAudit==='function'?window.oracleChartAudit():null;
   return {denominators:{labels_in_audit:labelAudit.length,rendered:labelAudit.filter(x=>!x.dropped).length,dropped:labelAudit.filter(x=>x.dropped).length,pinned_levels:labelAudit.filter(x=>x.pinnedLevel).length,events:labelAudit.filter(x=>/structure|liquidity|utbot/.test(String(x.token))).length},chartAudit,labelAudit,text:document.body.innerText.slice(0,4000)};
 });
 fs.writeFileSync('../runtime/ui-proof/honesty-step5-visual-audit.json',JSON.stringify(audit,null,2));
 text=await page.locator('body').innerText().catch(()=> '');
 fs.writeFileSync('../runtime/ui-proof/honesty-step5-visual-fixes.txt',text);
 console.log(JSON.stringify({pages:pages.length,hasStudio:/XAUUSD|BID|WATCHING|SCOREBOARD/.test(text),screenshot:'runtime/ui-proof/honesty-step5-visual-fixes.png',audit:'runtime/ui-proof/honesty-step5-visual-audit.json',denominators:audit.denominators,chartAudit:audit.chartAudit,head:text.slice(0,500)},null,2));
 await browser.close();
})();
