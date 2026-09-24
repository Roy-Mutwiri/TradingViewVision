/** Real MT5 candles with explicitly labelled, isolated scripted audience inputs. */
import {_electron as electron,expect} from '@playwright/test';
import {resolve} from 'node:path';
import {mkdir,writeFile,appendFile,mkdtemp,readFile,copyFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';

if(process.env.ORACLE_RUN_WINDOWS_LIVE!=='1')throw new Error('Set ORACLE_RUN_WINDOWS_LIVE=1 to use the local terminal.');
const root=resolve(import.meta.dirname,'../..');
const directory=resolve(root,'artifacts/phase4');await mkdir(directory,{recursive:true});
const temporary=await mkdtemp(resolve(tmpdir(),'oracle-phase4-'));
const events=resolve(temporary,'audience.jsonl');await writeFile(events,'');
const timeline=resolve(temporary,'timeline');
const minutes=Number(process.env.ORACLE_CAPTURE_MINUTES??3);
const desktop=await electron.launch({args:[resolve(root,'app')],env:{...process.env,ORACLE__RETENTION__GAMECHANGER_EVENTS:JSON.stringify(events),ORACLE__RETENTION__TIMELINE_DIR:JSON.stringify(timeline)}});
const frames=[],samples=[],errors=[],faults=[];
let page,client,recording=false,sequence=0,started=0;
const writes=[];
async function audience(name,text,type='comment'){
  await appendFile(events,JSON.stringify({kind:'event',action:'submitted',arrived_at:Date.now()/1000,live:{type,name,text,event_id:`proof-${++sequence}`,source:'rehearsal'}})+'\n');
}
try{
  const login=await desktop.firstWindow();await login.waitForFunction(()=>!!window.oracle);
  const result=await login.evaluate(()=>window.oracle.connectProfile({login:81740106,server:'ExnessKE-MT5Trial10',passwordType:'master'}));
  if(result.error)throw new Error(`${result.error.code}: ${result.error.message}`);
  console.log('Authenticated the saved local DEMO profile.');
  const opened=desktop.waitForEvent('window');await login.evaluate(()=>window.oracle.enterStudio()).catch(error=>{if(!/closed/.test(error.message))throw error;});
  page=await opened;page.on('pageerror',error=>errors.push(error.message));
  await expect(page.getByTestId('bid-price')).not.toHaveText('--',{timeout:30000});
  await page.evaluate(()=>{window.__proof={retention:[],quotes:[],faults:[]};window.oracle.onRetention(value=>window.__proof.retention.push({at_ms:Date.now(),hook:value.hook,card:value.card,scoreboard:value.scoreboard,rehearsal:value.rehearsal}));window.oracle.onQuote(value=>window.__proof.quotes.push({delivery_ms:Date.now()-value.received_ms,event_age_ms:Date.now()-value.quote.t_ms}));window.oracle.onChartError(value=>window.__proof.faults.push(value));});
  await page.waitForTimeout(1500);
  await page.waitForTimeout(Number(process.env.ORACLE_CAPTURE_WARM_MS??60000));
  client=await desktop.context().newCDPSession(page);
  const screenshots=resolve(temporary,'frames');await mkdir(screenshots);
  client.on('Page.screencastFrame',packet=>{
    void client.send('Page.screencastFrameAck',{sessionId:packet.sessionId}).catch(()=>{});
    if(!recording)return;
    const name=`frame-${String(frames.length).padStart(6,'0')}.jpg`;frames.push({name,t:performance.now()-started});
    writes.push(writeFile(resolve(screenshots,name),Buffer.from(packet.data,'base64')));
  });
  await page.bringToFront();await page.waitForTimeout(1000);
  const original=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio}));
  started=performance.now();recording=true;
  console.log(`Capturing ${minutes} minutes at the unchanged native window size.`);
  await client.send('Page.startScreencast',{format:'jpeg',quality:95,everyNthFrame:3});
  const duration=minutes*60000;
  let first=false,second=false,follow=false,master=false;
  while(performance.now()-started<duration){
    const elapsed=performance.now()-started;
    if(!first&&elapsed>10000){first=true;await audience('Amina💛','What is gold watching?');}
    if(!second&&elapsed>70000){second=true;await audience('HaddanFx','!score');}
    if(!follow&&elapsed>95000){follow=true;await audience('مرحبا_ذهب','','follow');}
    if(!master&&elapsed>120000){master=true;await audience('Supporter','','gift');}
    // A full-hour soak visits both surfaces; the three-minute proof stays broadcast.
    if(minutes>=60&&samples.length%300===299)await page.keyboard.press('F9');
    const sample=await page.evaluate(()=>{
      const badge=document.querySelector('[data-testid="account-mode"]'),disclaimer=document.querySelector('[data-testid="disclaimer"]'),scoreboard=document.querySelector('[aria-label="Prediction scoreboard"]');
      const inFrame=element=>{const r=element?.getBoundingClientRect();return !!r&&r.top>=0&&r.bottom<=innerHeight&&r.width>0;};
      return {at_ms:Date.now(),mode:document.querySelector('[data-testid="studio"]')?.getAttribute('data-ui-mode'),badge:badge?.textContent,disclaimer:disclaimer?.textContent,scoreboard:scoreboard?.textContent,badgeInFrame:inFrame(badge),disclaimerInFrame:inFrame(disclaimer),text:document.querySelector('[data-testid="studio"]')?.innerText,error:document.querySelector('.chart-message')?.innerText,geometry:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio}};
    });
    if(sample.error&&!/Loading|Reconnecting|Preparing the chart/.test(sample.error)){
      if(sample.mode==='broadcast')await page.keyboard.press('F9');
      await page.keyboard.press('`');
      const detail=await page.locator('.debug-drawer pre').first().textContent().catch(()=>null);
      throw new Error(`Chart fault visible: ${sample.error}; ${detail??JSON.stringify(faults)}`);
    }
    if(sample.badge!=='DEMO'||!sample.disclaimer?.includes('Not financial advice')||!sample.badgeInFrame||!sample.disclaimerInFrame||!sample.scoreboard?.trim())throw new Error('Permanent badge/disclaimer/scoreboard missing from a sampled frame');
    if(sample.mode==='broadcast'&&/Calendar history|M1 bars|derivation|unproven|clock v\d|Trading-capable|Tick age|latency/i.test(sample.text))throw new Error('Diagnostic text leaked into broadcast');
    if(JSON.stringify(sample.geometry)!==JSON.stringify(original))throw new Error(`Capture geometry changed: ${JSON.stringify({original,actual:sample.geometry})}`);
    delete sample.text;samples.push(sample);
    if(samples.length%60===0){console.log(JSON.stringify({elapsedSeconds:Math.round(elapsed/1000),mode:sample.mode,samples:samples.length,badge:sample.badge,geometry:sample.geometry}));await writeFile(resolve(directory,'capture-progress.json'),JSON.stringify({elapsedSeconds:Math.round(elapsed/1000),mode:sample.mode,samples:samples.length,errors,faults}));}
    await page.waitForTimeout(1000);
  }
  recording=false;await client.send('Page.stopScreencast');await Promise.all(writes);
  const state=await page.evaluate(()=>window.__proof);faults.push(...state.faults);
  await page.screenshot({path:resolve(directory,'broadcast-live.png')});
  const naming=minutes>=60?'hour-soak':'broadcast-proof';
  const report={source:'REAL EXNESS MT5 candles; scripted audience explicitly labelled REHEARSAL',minutes,geometry:original,frames:frames.length,samples,errors,faults,retention:state.retention,quotes:state.quotes};
  await writeFile(resolve(directory,`${naming}.json`),JSON.stringify(report,null,2));
  if(errors.length||faults.length)throw new Error('Renderer or engine faults during capture');
  if(!state.retention.some(value=>value.card?.handle==='Amina💛')||!state.retention.some(value=>value.card?.handle==='HaddanFx'))throw new Error('Both named answers were not rendered');
  const python=resolve(root,'.venv312/Scripts/python.exe');
  const executable=spawnSync(python,['-c','import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())'],{encoding:'utf8'}).stdout.trim();
  const list=frames.map((frame,i)=>`file '${frame.name}'\nduration ${Math.max(.001,((frames[i+1]?.t??duration)-frame.t)/1000)}`).join('\n')+`\nfile '${frames.at(-1).name}'\n`;
  const concat=resolve(screenshots,'frames.ffconcat');await writeFile(concat,list);
  const movie=resolve(directory,`${naming}-3.5Mbps.mp4`);
  const pixelFormat=original.width%2||original.height%2?'yuv444p':'yuv420p';
  const {readdir}=await import('node:fs/promises');
  const encoded=spawnSync(executable,['-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',concat,'-an','-c:v','libx264','-preset','veryfast','-b:v','3500k','-minrate','3500k','-maxrate','3500k','-bufsize','7000k','-x264-params','nal-hrd=cbr:force-cfr=1','-r','30','-t',String(duration/1000),'-pix_fmt',pixelFormat,'-movflags','+faststart',movie],{encoding:'utf8'});
  if(encoded.status!==0)throw new Error(`Streaming encode failed: ${encoded.stderr}`);
  const playback=spawnSync(executable,['-hide_banner','-loglevel','error','-y','-ss','90','-i',movie,'-frames:v','1',resolve(directory,`${naming}-decoded.png`)],{encoding:'utf8'});
  if(playback.status!==0)throw new Error('Could not decode streaming-bitrate capture');
  console.log(JSON.stringify({minutes,frames:frames.length,samples:samples.length,movie,errors,faults}));
}finally{
  if(recording&&client){recording=false;await client.send('Page.stopScreencast').catch(()=>{});}
  await desktop.close();
}
// After worker shutdown the append-only timeline contains all final beat endings.
const {readdir}=await import('node:fs/promises');
const files=await readdir(timeline);
const last=files.filter(name=>name.endsWith('.jsonl')).sort().at(-1);
if(last){await copyFile(resolve(timeline,last),resolve(directory,'recorded-timeline.jsonl'));const result=spawnSync(resolve(root,'.venv312/Scripts/python.exe'),['-m','oracle.director.timeline',resolve(directory,'recorded-timeline.jsonl'),'--output',resolve(directory,'recorded-retention-report.json')],{cwd:resolve(root,'engine'),encoding:'utf8'});if(result.status!==0)throw new Error('Recorded retention report failed');}
