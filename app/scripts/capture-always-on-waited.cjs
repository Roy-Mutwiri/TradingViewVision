const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
 const page=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://')).find(p=>p.url().includes('index.html'));
 if(!page) throw new Error('No ORACLE page found');
 let data=null;
 for(let i=0;i<90;i++){
  await page.waitForTimeout(1000);
  data=await page.evaluate(()=>({
   at_ms:Date.now(), tf:window.__oracleLastFrame?.tf, now_ms:window.__oracleLastFrame?.now_ms,
   candidate_status:window.__oracleLastFrame?.candidate_status,
   scoreboard:window.__oracleLastRetention?.scoreboard,
   text:document.body.innerText,
   openCallObjects:(window.__oracleLastFrame?.objects||[]).filter(o=>o.style?.token==='call.trade').map(o=>({id:o.id,text_args:o.text_args,points:o.points}))
  }));
  if(data?.candidate_status?.call_diagnostics?.source_marker || data?.candidate_status?.active_timeframes) break;
 }
 const out=path.resolve('..','runtime','ui-proof','always-on-signals'); fs.mkdirSync(out,{recursive:true});
 fs.writeFileSync(path.join(out,'step0-live-diagnostic-waited.json'),JSON.stringify(data,null,2));
 console.log(JSON.stringify({diag:data?.candidate_status?.call_diagnostics,active_timeframes:data?.candidate_status?.active_timeframes,init_skips:data?.candidate_status?.init_skips,openCallObjects:data?.openCallObjects?.length},null,2));
 await browser.close();
})();
