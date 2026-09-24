import {chromium} from 'playwright';
const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
const page=browser.contexts()[0].pages()[0];
const buttons=await page.evaluate(()=>[...document.querySelectorAll('button')].map((b,i)=>({i,text:b.innerText,disabled:b.disabled,html:b.outerHTML.slice(0,300),rect:(()=>{const r=b.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()})));
console.log(JSON.stringify(buttons,null,2));
await browser.close();
