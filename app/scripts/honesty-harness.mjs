import esbuild from 'esbuild';
import {pathToFileURL} from 'node:url';
import {mkdtempSync,writeFileSync,existsSync,createReadStream} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import readline from 'node:readline';

const root=process.cwd().endsWith('app')?join(process.cwd(),'..'):process.cwd();
const appDir=join(root,'app');
const outDir=join(root,'runtime/ui-proof/honesty-day');
const arg=(name)=>{const i=process.argv.indexOf(name); return i>=0?process.argv[i+1]:null;};
const recordsPath=arg('--records')?join(root,arg('--records')):join(outDir,'records.jsonl');
const force=!arg('--records')&&(process.argv.includes('--regen')||!existsSync(recordsPath));
if(force){
  const py=process.env.ORACLE_PYTHON||join(root,'.venv/Scripts/python.exe');
  const res=spawnSync(py,[join(root,'engine/scripts/export_honesty_day.py'),'--out',recordsPath],{cwd:root,encoding:'utf-8',stdio:['ignore','pipe','pipe'],env:{...process.env,PYTHONPATH:join(root,'engine')}});
  if(res.status!==0){
    console.error(res.stdout);
    console.error(res.stderr);
    process.exit(res.status||1);
  }
  console.log(res.stdout.trim());
}
const tmp=mkdtempSync(join(tmpdir(),'oracle-honesty-'));
const bundled=join(tmp,'analysisSlides.mjs');
await esbuild.build({entryPoints:[join(appDir,'src/analysisSlides.ts')],bundle:true,platform:'node',format:'esm',outfile:bundled});
const {buildAnalysisSlides}=await import(pathToFileURL(bundled).href);

const rawEnum=/\b[A-Z]+_[A-Z0-9_]+\b/;
const zeroAway=/\b0\.00 away\b/i;
const placeholder=/(^|\s)(--|pending|null|undefined)(\s|$)/i;
const whyBanned=[/institutions?/i,/smart\s*money\s+wants/i,/wants\s+to\s+(?:buy|sell|hunt|take)/i,/market\s+makers?\s+wants/i];
const priceRe=/\b\d{1,2},\d{3}\.\d{2}\b/g;
const violations={truth:{},fact:{},cross_surface:{},consistency:{},eligibility:{},ordering:{}};
const examples={truth:{},fact:{},cross_surface:{},consistency:{},eligibility:{},ordering:{}};
const denominators={records:0,slides:0,checklist_lines:0,headlines:0};
function add(rule,type,row,msg){
  violations[rule][type]=(violations[rule][type]||0)+1;
  const key=type;
  examples[rule][key]??=[];
  if(examples[rule][key].length<3)examples[rule][key].push({time:row.broker_time,seq:row.eval.seq,msg,text:row._text});
}
function collectNumbers(value,set=[]){
  if(value==null)return set;
  if(typeof value==='number'&&Number.isFinite(value))set.push(Number(value));
  else if(Array.isArray(value))for(const v of value)collectNumbers(v,set);
  else if(typeof value==='object')for(const v of Object.values(value))collectNumbers(v,set);
  return set;
}
function numToken(token){return Number(token.replaceAll(',',''));}
function hasNumber(numbers,value){return numbers.some(n=>Math.abs(n-value)<=0.015);}
function textUnit(type,content){return {type,content:String(content||'')};}
function isPremium(row){return row.thesis?.price_position?.label==='PREMIUM';}
function isDiscount(row){return row.thesis?.price_position?.label==='DISCOUNT';}
function inZone(row){
  const p=Number(row.price),lo=Number(row.thesis?.plan?.zone_lo),hi=Number(row.thesis?.plan?.zone_hi);
  return Number.isFinite(p)&&Number.isFinite(lo)&&Number.isFinite(hi)&&lo<=p&&p<=hi;
}
function checkTruth(unit,row){
  const t=unit.content.toLowerCase();
  row._text=unit.content;
  if(/wait(?:ing)? for premium|needs premium|wait premium/.test(t)){
    if(isPremium(row)||row.thesis?.blocking_gate?.passed)add('truth',unit.type,row,'premium wait shown while premium gate is true');
  }
  if(/wait(?:ing)? for discount|needs discount|wait discount/.test(t)){
    if(isDiscount(row)||row.thesis?.blocking_gate?.passed)add('truth',unit.type,row,'discount wait shown while discount gate is true');
  }
  if(/needs return/.test(t)&&inZone(row))add('truth',unit.type,row,'return-to-zone wait shown while price is inside zone');
  if(/price in premium/.test(t)&&!isPremium(row))add('truth',unit.type,row,'premium claim false');
  if(/price in discount/.test(t)&&!isDiscount(row))add('truth',unit.type,row,'discount claim false');
  if(/agrees with bias/.test(t)&&/against bias/.test(t))add('truth',unit.type,row,'agreement contradiction in one text');
}
function checkEligibility(unit,row){
  row._text=unit.content;
  if(rawEnum.test(unit.content))add('eligibility',unit.type,row,'raw enum rendered');
  if(zeroAway.test(unit.content))add('eligibility',unit.type,row,'zero distance rendered');
  if(placeholder.test(unit.content))add('eligibility',unit.type,row,'placeholder rendered');
  if(/\b(?:tapped|testing|swept)\s+v\d/i.test(unit.content))add('ordering',unit.type,row,'level reaction references a plan version instead of a level');
  if(whyBanned.some(pattern=>pattern.test(unit.content)))add('eligibility',unit.type,row,'why-rule banned phrase rendered');
  if(/not evaluated/i.test(unit.content)&&row.thesis?.plan?.zone_lo!=null&&row.thesis?.plan?.zone_hi!=null)add('eligibility',unit.type,row,'not evaluated rendered while a plan zone exists');
}

function checkFact(unit,row,numbers){
  row._text=unit.content;
  for(const token of unit.content.match(priceRe)||[]){
    if(!hasNumber(numbers,numToken(token)))add('fact',unit.type,row,`number ${token} not present in snapshot`);
  }
}
function checklistTexts(row){return Array.isArray(row.thesis?.lines)?row.thesis.lines.slice(0,5):[];}
let hashLines=[];
const rl=readline.createInterface({input:createReadStream(recordsPath,{encoding:'utf-8'}),crlfDelay:Infinity});
for await (const line of rl){
  if(!line)continue;
  const cleanLine=line.charCodeAt(0)===0xFEFF?line.slice(1):line;
  const row=JSON.parse(cleanLine);
  denominators.records++;
  const thesis=row.thesis||null;
  const frame=row.frame||null;
  const open=Array.isArray(row.open_call_ids)&&row.open_call_ids.length>0;
  const slides=buildAnalysisSlides({thesis,frame,retention:null,tf:row.tf||'M15',price:row.price,now:row.eval.t_broker_ms,book:row.book??frame?.book??null});
  denominators.slides+=slides.length;
  denominators.checklist_lines+=checklistTexts(row).length;
  denominators.headlines++;
  const units=[textUnit('HEADLINE',thesis?.headline)];
  for(const s of slides)units.push(textUnit(s.type,s.content));
  for(const [i,text] of checklistTexts(row).entries())units.push(textUnit(`CHECKLIST_${i+1}`,text));
  const numbers=collectNumbers({thesis:row.thesis,frame:row.frame,price:row.price});
  for(const unit of units){
    checkEligibility(unit,row);
    checkTruth(unit,row);
    checkFact(unit,row,numbers);
  }
  const texts=units.map(u=>u.content.toLowerCase()).join('\n');
  row._text=texts;
  if(/wait(?:ing)? for premium|wait premium/.test(texts)&&/price in premium/.test(texts))add('cross_surface','PREMIUM',row,'one surface waits for premium while another says price is in premium');
  if(/wait(?:ing)? for discount|wait discount/.test(texts)&&/price in discount/.test(texts))add('cross_surface','DISCOUNT',row,'one surface waits for discount while another says price is in discount');
  const callSlide=slides.some(s=>s.type==='CALL');
  const callStage=['CALL_PENDING','CALL_ACTIVE'].includes(thesis?.stage);
  if(callSlide!==open)add('consistency','CALL_SLIDE',row,`CALL slide ${callSlide} but open calls ${open}`);
  if(callStage!==open)add('consistency','CALL_STAGE',row,`CALL stage ${callStage} but open calls ${open}`);
  hashLines.push(`${row.eval.seq}:${slides.map(s=>`${s.type}:${s.content}`).join('|')}:${checklistTexts(row).join('|')}:${thesis?.headline||''}`);
}
const crypto=await import('node:crypto');
const report={records_path:recordsPath,denominators,violations,examples,sequence_sha256:crypto.createHash('sha256').update(hashLines.join('\n')).digest('hex')};
writeFileSync(join(outDir,'honesty-harness-report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
const total=Object.values(violations).flatMap(o=>Object.values(o)).reduce((a,b)=>a+Number(b),0);
if(total>0)process.exit(1);









