const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
  const seconds=600;
  const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
  const page=browser.contexts().flatMap(c=>c.pages()).filter(p=>!p.url().startsWith('devtools://')).find(p=>p.url().includes('index.html'));
  if(!page) throw new Error('No ORACLE page found');
  const result=await page.evaluate(async seconds=>{
    const deltas=[];let last=performance.now();const end=last+seconds*1000;
    return await new Promise(resolve=>{
      function frame(now){
        deltas.push(now-last);last=now;
        if(now<end) requestAnimationFrame(frame);
        else {
          const fps=deltas.slice(1).map(ms=>1000/ms).filter(Number.isFinite).sort((a,b)=>a-b);
          const q=p=>fps[Math.max(0,Math.min(fps.length-1,Math.floor((fps.length-1)*p)))]||0;
          resolve({samples:fps.length,min:q(0),p50:q(.5),p95:q(.05),fps_ge_60_pct:fps.filter(x=>x>=60).length/Math.max(1,fps.length)*100,primitive_count:window.__oracleLastFrame?.objects?.length??null,density:window.__oracleLastFrame?.chart_density??null});
        }
      }
      requestAnimationFrame(frame);
    });
  },seconds);
  const out=path.resolve('..','runtime','ui-proof','batch-18h');fs.mkdirSync(out,{recursive:true});
  fs.writeFileSync(path.join(out,'step0-fps-10m.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
  await browser.close();
})();
