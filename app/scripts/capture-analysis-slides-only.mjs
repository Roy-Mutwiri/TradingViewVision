import {chromium} from 'playwright';
import {mkdirSync, writeFileSync} from 'node:fs';
const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
const pages=browser.contexts()[0].pages();
const page=pages[pages.length-1];
await page.waitForTimeout(3000);
const m15=page.getByRole('button',{name:'M15'}).first();
if(await m15.count()) await m15.click({force:true}).catch(()=>{});
await page.waitForTimeout(6000);
mkdirSync('../runtime/ui-proof',{recursive:true});
await page.screenshot({path:'../runtime/ui-proof/analysis-slides-step1.png',fullPage:false});
const audit=await page.evaluate(()=>{
 const rectOf=(el)=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}};
 return {
  body:document.body.innerText.slice(0,1600),
  slides:[...document.querySelectorAll('.analysis-slides')].map(el=>({type:el.getAttribute('data-slide-type'),text:el.textContent,rect:rectOf(el)})),
  slideParts:[...document.querySelectorAll('.analysis-slides .slide-type,.analysis-slides .slide-content,.analysis-slides .slide-dots')].map(el=>({class:el.className,text:el.textContent,rect:rectOf(el)})),
  frame:window.__oracleLastFrame?.thesis??null,
  tf:[...document.querySelectorAll('nav button')].filter(b=>b.getAttribute('aria-pressed')==='true').map(b=>b.textContent)
 };
});
writeFileSync('../runtime/ui-proof/analysis-slides-step1-audit.json',JSON.stringify(audit,null,2));
console.log(JSON.stringify({slides:audit.slides,tf:audit.tf,hasThesis:!!audit.frame,body:audit.body.slice(0,80)},null,2));
await browser.close();
