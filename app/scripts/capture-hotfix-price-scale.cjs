const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const tfs=['M5','M15','H1'];
async function waitReady(page){
  for(let i=0;i<30;i++){
    const audit=await page.evaluate(()=>({text:document.body.innerText,chart:window.oracleChartAudit?.()})).catch(()=>({}));
    if(audit.chart?.visible_range&&audit.chart?.candleScale&&audit.text?.includes('BID'))return audit;
    await page.waitForTimeout(1000);
  }
  return await page.evaluate(()=>({text:document.body.innerText,chart:window.oracleChartAudit?.()}));
}
(async()=>{
  const out=path.resolve('..','runtime','ui-proof','hotfix-price-scale');fs.mkdirSync(out,{recursive:true});
  let b,page;
  for(let i=0;i<18;i++){
    try{b=await chromium.connectOverCDP('http://127.0.0.1:9223');page=b.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://')).at(-1);const text=page?await page.locator('body').innerText().catch(()=> ''):'';if(page&&/XAUUSD|BID|SCOREBOARD/.test(text))break;await b.close();b=null;}catch{}
    await new Promise(r=>setTimeout(r,2000));
  }
  if(!b||!page)throw new Error('studio unavailable');
  const results=[];
  for(const tf of tfs){
    await page.getByRole('button',{name:tf,exact:true}).click().catch(()=>{});
    await page.waitForTimeout(2500);
    await waitReady(page);
    const screenshot=`hotfix-${tf}-ready.png`;
    await page.screenshot({path:path.join(out,screenshot),fullPage:true});
    const final=await page.evaluate(tf=>({tf,text:document.body.innerText,html:document.body.innerHTML,chart:window.oracleChartAudit?.(),labels:window.oracleLabelAudit?.()}),tf);
    results.push({tf,screenshot:`runtime/ui-proof/hotfix-price-scale/${screenshot}`,chart:final.chart,scalePass:Boolean(final.chart?.priceScale&&final.chart?.candleScale&&final.chart.priceScale.min>=final.chart.candleScale.lo-0.01&&final.chart.priceScale.max<=final.chart.candleScale.hi+0.01),mojibake:[...'âÃ'].some(ch=>final.text.includes(ch)),bosV:/\bBOS v\b/.test(final.text),planReaction:/tapped v\d/i.test(final.text),stageCurrent:/stage-tracker[\s\S]*current/.test(final.html)});
  }
  fs.writeFileSync(path.join(out,'price-scale-audit-ready.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify({out:'runtime/ui-proof/hotfix-price-scale',results},null,2));
  await page.getByRole('button',{name:'M15',exact:true}).click().catch(()=>{});
  await b.close();
})();
