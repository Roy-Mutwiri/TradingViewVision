import {chromium} from 'playwright';
import {readFileSync, mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
const portFile=join(process.env.APPDATA,'ORACLE STUDIO','DevToolsActivePort');
const port=process.env.ORACLE_CDP_PORT||readFileSync(portFile,'utf8').trim().split(/\\r?\\n/)[0];
const browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
const context=browser.contexts()[0];
let page=context.pages()[0];
await page.waitForLoadState('domcontentloaded').catch(()=>{});
const text=await page.locator('body').innerText({timeout:5000}).catch(()=>'');
if(/ENTER STUDIO|Connect|Preflight/i.test(text)){
  const button=page.getByRole('button',{name:/enter studio|connect|launch/i}).first();
  if(await button.count()) await button.click().catch(()=>{});
}
await page.waitForTimeout(6000);
for(const tf of ['M15']){
 const btn=page.getByRole('button',{name:tf}).first();
 if(await btn.count()) await btn.click().catch(()=>{});
}
await page.waitForTimeout(5000);
mkdirSync('runtime/ui-proof',{recursive:true});
await page.screenshot({path:'runtime/ui-proof/analysis-slides-step1.png',fullPage:false});
const audit=await page.evaluate(()=>{
 const box=document.querySelector('.analysis-slides');
 const slides=[...document.querySelectorAll('.analysis-slides')].map(el=>({text:el.textContent,type:el.getAttribute('data-slide-type'),rect:(()=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()}));
 const all=[...document.querySelectorAll('.signal-state-banner,.analysis-slides,.slide-type,.slide-content,.slide-dots')].map(el=>({class:el.className,text:el.textContent,rect:(()=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()}));
 return {url:location.href,body:document.body.innerText.slice(0,1200),slides,all};
});
writeFileSync('runtime/ui-proof/analysis-slides-step1-audit.json',JSON.stringify(audit,null,2));
await browser.close();
console.log(JSON.stringify(audit.slides,null,2));


