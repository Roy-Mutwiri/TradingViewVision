import {chromium} from 'playwright';
import {mkdirSync, writeFileSync} from 'node:fs';
const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
const page=browser.contexts()[0].pages().at(-1);
mkdirSync('../runtime/ui-proof/analysis-slides-rotation',{recursive:true});
const samples=[];
for(let i=0;i<11;i++){
  await page.screenshot({path:`../runtime/ui-proof/analysis-slides-rotation/${String(i).padStart(2,'0')}.png`,fullPage:false});
  const sample=await page.evaluate(()=>{
    const box=document.querySelector('.analysis-slides');
    const content=document.querySelector('.analysis-slides .slide-content');
    return {t:Date.now(),type:box?.getAttribute('data-slide-type')??null,text:content?.textContent??box?.textContent??null,hasThesis:!!window.__oracleLastFrame?.thesis};
  });
  samples.push(sample);
  await page.waitForTimeout(6000);
}
writeFileSync('../runtime/ui-proof/analysis-slides-rotation.json',JSON.stringify(samples,null,2));
console.log(JSON.stringify({samples:samples.length,types:[...new Set(samples.map(s=>s.type))],samples},null,2));
await browser.close();
