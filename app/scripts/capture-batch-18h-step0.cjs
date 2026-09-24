const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
  const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
  const pages=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://'));
  const page=pages.find(p=>p.url().includes('index.html'))||pages[0];
  if(!page) throw new Error('No ORACLE page found');
  await page.waitForTimeout(2000);
  const out=path.resolve('..','runtime','ui-proof','batch-18h');
  fs.mkdirSync(out,{recursive:true});
  const audit=await page.evaluate(()=>{
    const labels=typeof window.oracleLabelAudit==='function'?window.oracleLabelAudit():[];
    const boxes=labels.filter(x=>!x.dropped&&x.box).map(x=>({id:x.id,token:x.token,lines:x.lines,box:x.box,pinnedLevel:x.pinnedLevel,anchor:x.anchor}));
    const overprints=[];
    const overlaps=(a,b,p=0)=>a.x<b.x+b.width+p&&a.x+a.width+p>b.x&&a.y<b.y+b.height+p&&a.y+a.height+p>b.y;
    for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++)if(overlaps(boxes[i].box,boxes[j].box,1))overprints.push([boxes[i],boxes[j]]);
    return {text:document.body.innerText, chart:typeof window.oracleChartAudit==='function'?window.oracleChartAudit():null, labels, denominators:{labels_in_draw:labels.length, rendered:boxes.length, dropped:labels.filter(x=>x.dropped).length}, overprint_count:overprints.length, overprints:overprints.slice(0,10)};
  });
  fs.writeFileSync(path.join(out,'step0-m15-audit.json'),JSON.stringify(audit,null,2));
  console.log(JSON.stringify({audit:'runtime/ui-proof/batch-18h/step0-m15-audit.json',overprint_count:audit.overprint_count,labels:audit.denominators.labels_in_draw,rendered:audit.denominators.rendered,dropped:audit.denominators.dropped},null,2));
  await browser.close();
})();
