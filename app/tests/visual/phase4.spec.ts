import {test,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {rehearsal} from '../fixtures/retention';

const diagnostics=/Calendar history|M1 bars|derivation|unproven|clock v\d|Trading-capable|Tick age|latency|Switch \d.*ms/i;

test('closed-market retention withholds live references',async({page})=>{
  await rehearsal(page);
  await page.evaluate(()=>{
    const w:any=window,frame=structuredClone(w.__replay.frames[0]);
    frame.session='Market closed';frame.levels=[];frame.marks=[];
    frame.hook={...frame.hook,kind:'SESSION_OPEN',id:'session:pending',headline:'Watch the next session open',sub:'If quotes return, the chart resumes. If delayed, replay continues.',countdown_ms:0,ends_ms:frame.now_ms};
    w.__retention(frame);
  });
  await expect(page.locator('.scenario-card')).toContainText('THE NEXT SESSION');
  expect(await page.locator('.scenario-card .direction-up,.scenario-card .direction-down').count()).toBe(0);
  await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
  await expect(page.getByTestId('disclaimer')).toBeVisible();
});

test('broadcast faults stay audience-readable while operator mode keeps the cause',async({page})=>{
  await rehearsal(page);
  await page.evaluate(()=>(window as any).__error({code:'HISTORY_EMPTY',message:'M1 bars unavailable; download history from the terminal.',detail:{tf:'M1',bars:0},recoverable:true}));
  await expect(page.getByRole('status')).toHaveText('Chart paused. Waiting for verified candles.');
  expect(await page.getByTestId('studio').innerText()).not.toMatch(diagnostics);
  await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
  await expect(page.getByTestId('disclaimer')).toBeVisible();
  await page.keyboard.press('F9');
  await expect(page.getByRole('status')).toContainText('M1 bars unavailable');
  await expect(page.getByRole('button',{name:'Return to preflight'})).toBeVisible();
});

test('broadcast default and F9 split the surfaces without changing the frame',async({page})=>{
  await rehearsal(page);
  const size=await page.evaluate(()=>[innerWidth,innerHeight,devicePixelRatio]);
  await expect(page.getByTestId('studio')).toHaveAttribute('data-ui-mode','broadcast');
  expect(await page.getByTestId('studio').innerText()).not.toMatch(diagnostics);
  await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
  await expect(page.getByTestId('disclaimer')).toBeVisible();
  expect(await page.locator('.chart-watermark').count()).toBe(0);
  await expect(page.getByTestId('bid-price')).toHaveCSS('font-size','42px');
  await page.keyboard.press('F9');
  await expect(page.getByTestId('studio')).toHaveAttribute('data-ui-mode','operator');
  expect(await page.getByTestId('studio').innerText()).toMatch(diagnostics);
  await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
  await expect(page.getByTestId('disclaimer')).toBeVisible();
  await page.keyboard.press('F9');
  expect(await page.getByTestId('studio').innerText()).not.toMatch(diagnostics);
  expect(await page.evaluate(()=>[innerWidth,innerHeight,devicePixelRatio])).toEqual(size);
  await expect(page.getByTestId('studio')).toHaveScreenshot('broadcast-default.png');
});

test('engine analysis results retain losses without audience scores',async({page})=>{
  await rehearsal(page);
  const geometry=await page.evaluate(()=>[innerWidth,innerHeight,devicePixelRatio]);
  await page.evaluate(()=>{
    const w:any=window,frame=structuredClone(w.__replay.frames[0]);
    frame.scoreboard=w.__callboard;w.__retention(frame);
  });
  const scoreboard=page.getByLabel('Prediction scoreboard');
  await expect(scoreboard).toContainText('THE SCOREBOARD');
  await expect(scoreboard).toContainText('LOSSES STAY');
  await expect(scoreboard).toContainText('1W');
  await expect(scoreboard).toContainText('1L');
  await expect(scoreboard).toContainText('1 scratch');
  await expect(scoreboard).toContainText('1 never triggered');
  await expect(scoreboard).toContainText('1 cancelled');
  await expect(scoreboard).toContainText('1 void data');
  await expect(scoreboard).toContainText('50% of 2 resolved');
  await expect(scoreboard).toContainText('0.50R expectancy');
  await expect(scoreboard).toContainText('SETUP · LOSS');
  await expect(scoreboard.getByRole('button',{name:'LAST 20'})).toHaveAttribute('aria-pressed','true');
  await scoreboard.getByRole('button',{name:'TODAY · from 17:00 NY'}).click();
  await expect(scoreboard).toContainText('1 cancelled');
  await scoreboard.getByRole('button',{name:'ALL TIME'}).click();
  await expect(page.locator('.score-results>div')).toHaveCount(6);
  await scoreboard.locator('summary').filter({hasText:'VOID_DATA'}).click();
  await expect(scoreboard).toContainText('STALE: Synthetic terminal outage');
  await expect(page.locator('.hook-strip')).toHaveCount(0);
  expect(await page.getByTestId('studio').innerText()).not.toMatch(/YOUR NEXT DECISION|NEXT UP|UP wins|DOWN wins/);
  expect(await page.evaluate(()=>[innerWidth,innerHeight,devicePixelRatio])).toEqual(geometry);
});

test('named answer arrives within two seconds and hostile handles stay plain text',async({page})=>{
  await rehearsal(page);
  const start=performance.now();await page.evaluate(()=>(window as any).__emit(30));
  await expect(page.locator('.answer-card')).toContainText('@Sara');
  expect(performance.now()-start).toBeLessThan(2000);
  for(const name of ['Amina💛','مرحبا_ذهب','z'.repeat(40),'<img src=x onerror=alert(1)>']){
    await page.evaluate((name)=>{const w:any=window,value=structuredClone(w.__replay.frames[30]);value.card.handle=name;value.card.question='<script>layout-breaking</script>';w.__retention(value);},name);
    await expect(page.locator('.answer-card bdi')).toBeVisible();
    expect(await page.locator('.answer-card img,.answer-card script').count()).toBe(0);
    const box=await page.locator('.answer-card').boundingBox(),text=await page.locator('.answer-card bdi').boundingBox();
    expect(text!.width).toBeLessThanOrEqual(box!.width);
    expect(Array.from(await page.locator('.answer-card bdi').innerText()).length).toBeLessThanOrEqual(19);
  }
  await expect(page.getByTestId('disclaimer')).toBeVisible();
});

test('only calls paint compact three-line strips; levels have chips without reasons',async({page})=>{
  await page.addInitScript(()=>{
    const w:any=window;w.__reasonPaint=[];
    const paint=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText=function(text,x,y,maxWidth){
      w.__reasonPaint.push({text,ink:this.fillStyle,alpha:this.globalAlpha});
      if(maxWidth===undefined)return paint.call(this,text,x,y);
      return paint.call(this,text,x,y,maxWidth);
    };
  });
  await rehearsal(page);
  await page.evaluate(()=>{
    const w:any=window,frame=structuredClone(w.__replay.frames[0]),t=w.__bars('M5').at(-1).t_open_ms;
    frame.marks=[
      {id:'existing-object-reason',object_hash:'fixture',layer:'L2',shape:'LABEL',points:[{t_ms:t,price:4343}],style:{token:'retention.level'},text_key:'fixture.level',text_args:{label:'PDH'},reason:'Stored object evidence'},
      {id:'call-reason-strip',object_hash:'fixture',layer:'L3',shape:'LABEL',points:[{t_ms:t,price:4349}],style:{token:'analysis.reason'},text_key:'analysis.reason.fixture',text_args:{label:'EQL 4,331.40\nCHOCH 4,350.20\nH1 OB DISCOUNT'},reason:'EQL 4,331.40\nCHOCH 4,350.20\nH1 OB DISCOUNT'},
    ];w.__retention(frame);
  });
  await expect.poll(()=>page.evaluate(()=>(window as any).__reasonPaint.filter((p:any)=>['EQL 4,331.40','CHOCH 4,350.20','H1 OB DISCOUNT'].includes(p.text)&&p.ink==='#080b10'&&p.alpha===1).length)).toBeGreaterThanOrEqual(3);
  expect(await page.evaluate(()=>(window as any).__reasonPaint.some((p:any)=>p.text==='Stored object evidence'))).toBe(false);
  await expect(page.getByTestId('live-chart')).toHaveScreenshot('silent-reasons.png');
});

test('sampled sixty-minute replay preserves the badge disclaimer and scoreboard in both modes',async({page})=>{
  await rehearsal(page);const samples=[];
  for(const mode of ['broadcast','operator']){
    if(mode==='operator')await page.keyboard.press('F9');
    for(let minute=0;minute<60;minute++){
      const sample=await page.evaluate(async({minute,mode})=>{
        const w:any=window,value=structuredClone(w.__replay.frames[0]);value.now_ms+=minute*60000;value.hook.ends_ms=value.now_ms+60000;value.hook.id=`sample-${minute}`;w.__retention(value);
        await new Promise(requestAnimationFrame);
        return {mode,minute,badge:document.querySelector('[data-testid="account-mode"]')?.textContent,disclaimer:document.querySelector('[data-testid="disclaimer"]')?.textContent,scoreboard:document.querySelector('[aria-label="Prediction scoreboard"]')?.textContent};
      },{minute,mode});
      expect(sample.badge).toBe('DEMO');expect(sample.disclaimer).toContain('Not financial advice');expect(sample.scoreboard?.trim()).toBeTruthy();samples.push(sample);
    }
  }
  await mkdir('../artifacts/phase4',{recursive:true});await writeFile('../artifacts/phase4/replay-samples.json',JSON.stringify({synthetic:true,scope:'Sampled renderer replay; not a real-time sixty-minute live capture',samples},null,2));
});

test('health and connection colours are neutral or gold, and market chips meet contrast',async({page})=>{
  await rehearsal(page);await page.evaluate(()=>(window as any).__emit(20));
  const colors=await page.locator('.health-dot,.tick-age-dot,.mode-badge').evaluateAll(elements=>elements.map(e=>getComputedStyle(e).color+' '+getComputedStyle(e).backgroundColor));
  expect(colors.join(' ')).not.toMatch(/rgb\(83, 212, 182\)|rgb\(241, 139, 145\)/);
  const contrast=(hex:string,bg:string)=>{
    const lum=(value:string)=>{const c=value.match(/\w\w/g)!.map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2];};
    const a=lum(hex),b=lum(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  };
  for(const chip of ['53d4b6','f18b91','dec38c'])expect(contrast(chip,'080b10')).toBeGreaterThan(4.5);
  // Provisional ink remains 45% opacity, with an opaque backplate and large bold text.
  const blend=(ink:string)=>ink.match(/\w\w/g)!.map((v,i)=>Math.round(.45*parseInt(v,16)+.55*parseInt('080b10'.slice(i*2,i*2+2),16)).toString(16).padStart(2,'0')).join('');
  expect(contrast(blend('f3f0e8'),'080b10')).toBeGreaterThan(3);
});
