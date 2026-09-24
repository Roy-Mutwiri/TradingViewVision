import {test,expect} from '@playwright/test';
import {rehearsal} from '../fixtures/retention';

test('call strip expires without ticks while its chip stays',async({page})=>{
  await page.clock.install();
  await page.addInitScript(()=>{
    const w:any=window;w.__callText=[];
    const scale=CanvasRenderingContext2D.prototype.scale,paint=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.scale=function(x,y){if(this.canvas.classList.contains('session-shading'))w.__callText=[];return scale.call(this,x,y);};
    CanvasRenderingContext2D.prototype.fillText=function(text,x,y,maxWidth){if(this.canvas.classList.contains('session-shading'))w.__callText.push(text);return maxWidth===undefined?paint.call(this,text,x,y):paint.call(this,text,x,y,maxWidth);};
  });
  await rehearsal(page);
  await page.clock.runFor(1000);
  await page.evaluate(()=>{
    const w:any=window,frame=structuredClone(w.__replay.frames[0]),t=w.__bars('M5').at(-1).t_open_ms;
    const base={object_hash:'fixture',layer:'L3',shape:'LABEL',points:[{t_ms:t,price:4356}],state:'FRESH'};
    frame.marks=[
      {...base,id:'call-chip',style:{token:'analysis.entry'},text_key:'entry',text_args:{label:'ENTRY'},reason:'Stored evidence',ttl_ms:0},
      {...base,id:'call-strip',style:{token:'analysis.reason'},text_key:'reason',text_args:{label:'CHOCH 4,350.20'},reason:'CHOCH 4,350.20',ttl_ms:20000},
    ];w.__retention(frame);
  });
  await page.clock.runFor(100);
  await expect.poll(async()=>{await page.clock.runFor(100);return page.evaluate(()=>(window as any).__callText);}).toContain('CHOCH 4,350.20');
  await page.clock.fastForward(20100);
  await page.clock.runFor(100);
  await expect.poll(async()=>{await page.clock.runFor(100);return page.evaluate(()=>(window as any).__callText);}).not.toContain('CHOCH 4,350.20');
  await expect.poll(async()=>{await page.clock.runFor(100);return page.evaluate(()=>(window as any).__callText);}).toContain('ENTRY 4,356.00');
});

test('dense day caps annotation text, clears candles, and keeps indicator evidence in the drawer',async({page})=>{
  await page.addInitScript(()=>{
    const w:any=window;w.__annotations=[];w.__axisText=[];
    const scale=CanvasRenderingContext2D.prototype.scale,round=CanvasRenderingContext2D.prototype.roundRect,paint=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.scale=function(x,y){if(this.canvas.classList.contains('session-shading'))w.__annotations=[];return scale.call(this,x,y);};
    CanvasRenderingContext2D.prototype.roundRect=function(x,y,width,height,radii){if(this.canvas.classList.contains('session-shading'))(this as any).__chip={x,y,width,height};return round.call(this,x,y,width,height,radii);};
    CanvasRenderingContext2D.prototype.fillText=function(text,x,y,maxWidth){
      if(this.canvas.classList.contains('session-shading'))w.__annotations.push({text,font:this.font,box:(this as any).__chip});
      else if(/^4[,\d]*\.?\d*$/.test(text))w.__axisText.push(text);
      return maxWidth===undefined?paint.call(this,text,x,y):paint.call(this,text,x,y,maxWidth);
    };
  });
  await rehearsal(page);
  await page.evaluate(()=>{
    const w:any=window,bars=w.__bars('M5');
    const objects=bars.slice(-180).filter((_:any,i:number)=>i%2===0).map((bar:any,i:number)=>({id:`dense-${i}`,object_hash:'fixture',layer:'L2',shape:'LABEL',points:[{t_ms:bar.t_open_ms,price:i%2?bar.h:bar.l}],style:{token:i%2?'utbot.sell':'utbot.buy'},text_key:'indicator.utbot',text_args:{direction:i%2?'BEARISH':'BULLISH'},reason:'close 4360.703 crossed below UT stop 4374.082 (ATR 13.379, k=1.0, period=14)'}));
    w.__chart({...w.__frame('M5'),objects,indicator_enabled:true});
  });
  await expect.poll(()=>page.evaluate(()=>(window as any).__annotations.length)).toBeGreaterThan(0);
  const painted=await page.evaluate(()=>(window as any).__annotations);
  expect(painted.length).toBeLessThanOrEqual(10);
  expect(painted.every((p:any)=>['Buy','Sell'].includes(p.text)&&p.font.startsWith('600 12px'))).toBe(true);
  for(let i=0;i<painted.length;i++)for(let j=i+1;j<painted.length;j++){
    const a=painted[i].box,b=painted[j].box;
    expect(a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y).toBe(false);
  }
  const axes=await page.evaluate(()=>(window as any).__axisText);
  expect(axes.length).toBeGreaterThan(0);expect(axes.every((s:string)=>!s.includes('.'))).toBe(true);
  expect(painted.map((p:any)=>p.text).join(' ')).not.toMatch(/ATR|k=|period|crossed|stop/i);
  await expect(page.locator('.bias-pending')).toHaveText('Bias: pending structure engine');
  await expect(page.locator('.bias-card,.levels-card,.bias-stack,.chart-indicator-chip')).toHaveCount(0);
  expect(await page.locator('.scenario-card').innerText()).not.toMatch(/Watch|market fact|Confirmed close/);
  await expect(page.getByLabel('Next close countdown',{exact:true})).toHaveText(/\d{2}:\d{2}/);
  await expect(page.getByTestId('live-chart')).toHaveScreenshot('dense-minimal-labels.png');
  await page.keyboard.press('Backquote');
  await page.getByText('UT Bot signal evidence',{exact:true}).click();
  await expect(page.getByLabel('Chart diagnostics')).toContainText('ATR 13.379, k=1.0, period=14');
});
