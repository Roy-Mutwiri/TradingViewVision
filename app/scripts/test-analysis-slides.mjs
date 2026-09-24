import esbuild from 'esbuild';
import {pathToFileURL} from 'node:url';
import {mkdtempSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const dir=mkdtempSync(join(tmpdir(),'oracle-slides-'));
const out=join(dir,'analysisSlides.mjs');
await esbuild.build({entryPoints:['src/analysisSlides.ts'],bundle:true,platform:'node',format:'esm',outfile:out});
const {buildAnalysisSlides,rotateAnalysisSlides,validateSlideLengths}=await import(pathToFileURL(out).href);
const now=Date.UTC(2026,8,23,11,0,0);
const thesis={headline:'M15 BEARISH  in premium  no valid short zone',stage:'NO_VALID_ZONE',bias:'BEARISH',key:'m15:nozone',why:'Sellers in control since 01:00',if_then:'Close < 4,308.23  next target 4,291.46  Close > 4,320.54  bearish view off',plan:{side:'SHORT',zone_id:'ob1',zone_lo:4322.64,zone_hi:4331.45,zone_ok:false,zone_problem:'OB above protected high 4,320.54'},dealing_range:{lo:4308.23,hi:4320.54,eq:4314.38},blocking_gate:{code:'PREMIUM',threshold:4314.38,distance:1.92,passed:true},invalidation:{level:4320.54,rule:'close above protected_high'},targets:[{id:'p1',name:'LONDON L',level:4308.23,distance:8.07}],bias_cause:{event_id:'evt1',level:4315.33,t_ms:now-3600000},htf_alignment:'H1 disagrees'};
const frame={now_ms:now,structure_state:{trend:'BEARISH',trend_since_ms:now-3600000},liquidity_pools:[{id:'below',strength:3,state:'FRESH',scope_key:'LONDON L',geometry:{level:4308.23,name:'LONDON L'}},{id:'above',strength:4,state:'TOUCHED',scope_key:'EQH',geometry:{level:4323.82,name:'EQH'}}],objects:[{indicator:'utbot',direction:'BEARISH',id:'ut1',points:[{t_ms:now-900000,price:4317}],style:{token:'utbot.sell'},source_bars:[1],reason:'',shape:'LABEL',layer:'L2',priority:1,state:'FRESH',text_args:{},text_key:'',ttl_ms:0,z:1,anim:{in_:'none',loop:null},confidence:1,t_open_ms:now-900000,tf:'M15'}]};
const retention={scoreboard:{today:{wins:2,losses:1,resolved:3,expectancy:null}}};
const slides=buildAnalysisSlides({thesis,frame,retention,tf:'M15',price:4316.3,now});
const types=new Set(slides.map(s=>s.type));
const required=['THESIS','WHY','PLAN','LIQUIDITY','TIMEFRAMES','MOMENTUM','INVALIDATION','SCENARIOS','SCORE'];
const missing=required.filter(t=>!types.has(t));
if(missing.length)throw new Error(`Missing slides: ${missing.join(', ')}`);
const bad=validateSlideLengths(slides,116);
if(bad.length)throw new Error(`Slide length failures: ${bad.join(', ')}`);
for(const slide of slides){
  if(/--|pending|undefined|null/i.test(slide.content))throw new Error(`Placeholder in ${slide.type}: ${slide.content}`);
  if(/[A-Z]+_[A-Z0-9_]+/.test(slide.content))throw new Error(`Raw enum in ${slide.type}: ${slide.content}`);
  if(/0\\.00 away/i.test(slide.content))throw new Error(`Zero-away text in ${slide.type}: ${slide.content}`);
  if(/(?<!\d)\s*\/\s*(?!\d)/.test(slide.content))throw new Error(`Forbidden slash separator in ${slide.type}: ${slide.content}`);
}
const rotated=rotateAnalysisSlides(slides);
for(let i=0;i<rotated.length;i+=3){
  if(!rotated.slice(i,i+3).some(s=>s.type==='THESIS'||s.type==='CALL'))throw new Error('Anchor absent inside a 3-slide span');
}
const callSlides=buildAnalysisSlides({thesis,frame,retention,tf:'M15',price:4316.3,now,liveSignal:{clock_version:1,created_ms:now-120000,created_trading_day:'2026-09-23',day_boundary:'17:00 America/New_York',direction:'SHORT',entry_hi:4319,entry_lo:4318,entry_ref:4318,expires_ms:now+300000,invalidation:4325,kind:'SETUP',reason:'fixture',state:'ACTIVE',state_hash:'x',symbol:'XAUUSD',target:4308,timeframe:'M5',tp2:4300},liveSignalR:1.67});
if(callSlides[0]?.type!=='CALL')throw new Error('CALL slide did not replace the anchor');
writeFileSync('runtime-ui-slides-test.json',JSON.stringify({eligible:slides.length,types:[...types],rotated:rotated.map(s=>s.type),callAnchor:callSlides[0].type},null,2));
console.log(JSON.stringify({eligible:slides.length,required:required.length,lengthFailures:bad.length,callAnchor:callSlides[0].type},null,2));

