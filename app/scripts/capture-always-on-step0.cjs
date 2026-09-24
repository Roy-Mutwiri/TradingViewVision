const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 const page=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://')).find(p=>p.url().includes('index.html'));
 if(!page) throw new Error('No ORACLE page found');
 await page.waitForTimeout(2000);
 const data=await page.evaluate(()=>({
   at_ms:Date.now(),
   tf:window.__oracleLastFrame?.tf,
   now_ms:window.__oracleLastFrame?.now_ms,
   candidate_status:window.__oracleLastFrame?.candidate_status,
   scoreboard:window.__oracleLastRetention?.scoreboard,
   liveSignalText:document.querySelector('[aria-label="Audience and market context"]')?.innerText||document.body.innerText,
   openCallObjects:(window.__oracleLastFrame?.objects||[]).filter(o=>o.style?.token==='call.trade').map(o=>({id:o.id,text_args:o.text_args,points:o.points}))
 }));
 const out=path.resolve('..','runtime','ui-proof','always-on-signals');fs.mkdirSync(out,{recursive:true});
 fs.writeFileSync(path.join(out,'step0-live-diagnostic.json'),JSON.stringify(data,null,2));
 console.log(JSON.stringify({out:'runtime/ui-proof/always-on-signals/step0-live-diagnostic.json',tf:data.tf,diag:data.candidate_status?.call_diagnostics,score:data.scoreboard?.all_time,openCallObjects:data.openCallObjects.length},null,2));
 await browser.close();
})();
