import {chromium} from 'playwright';
import {mkdirSync, writeFileSync} from 'node:fs';
const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
let page=browser.contexts()[0].pages()[0];
await page.waitForLoadState('domcontentloaded').catch(()=>{});
let body=await page.locator('body').innerText().catch(()=>'');
if(body.includes('Connect')&&!body.includes('Enter Studio')){
  const connect=page.getByRole('button',{name:/connect/i}).first();
  if(await connect.count()) await connect.click({force:true});
  await page.waitForTimeout(9000).catch(()=>{});
  body=await page.locator('body').innerText().catch(()=>'');
}
if(body.includes('Enter Studio')){
  await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
  await page.waitForTimeout(300);
  await page.locator('button.primary-button').click({force:true}).catch(()=>{});
  await page.waitForTimeout(9000).catch(()=>{});
  page=browser.contexts()[0].pages().at(-1);
}
await page.waitForTimeout(3000);
const m15=page.getByRole('button',{name:'M15'}).first();
if(await m15.count()) await m15.click({force:true}).catch(()=>{});
await page.waitForTimeout(10000);
mkdirSync('../runtime/ui-proof',{recursive:true});
await page.screenshot({path:'../runtime/ui-proof/graded-calls-slide-consistency.png',fullPage:false});
const audit=await page.evaluate(()=>{
 const texts=[...document.querySelectorAll('.analysis-slides,.signal-panel,.bias-pending,.score-card')].map(el=>el.textContent||'');
 const enumHits=texts.flatMap((text,i)=>(text.match(/\b[A-Z]+_[A-Z0-9_]+\b/g)||[]).map(hit=>({i,hit,text})));
 const zeroAway=texts.flatMap((text,i)=>/0\.00 away/i.test(text)?[{i,text}]:[]);
 return {texts,enumHits,zeroAway,slide:document.querySelector('.analysis-slides')?.textContent||'',thesis:window.__oracleLastFrame?.thesis??null,score:window.__oracleLastRetention?.scoreboard??null};
});
writeFileSync('../runtime/ui-proof/graded-calls-slide-consistency-audit.json',JSON.stringify(audit,null,2));
console.log(JSON.stringify({enumHits:audit.enumHits.length,zeroAway:audit.zeroAway.length,slide:audit.slide,hasThesis:!!audit.thesis},null,2));
await browser.close();

