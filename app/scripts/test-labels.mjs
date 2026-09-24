import {build} from 'esbuild';
import assert from 'node:assert/strict';
const bundle=await build({entryPoints:['src/chart/labels.ts'],bundle:true,platform:'node',format:'esm',write:false});
const {axisPrice,chipPrice,compactCallReason,labelLines,labelPriority,measurementColumn,overlaps,placeLabels}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const rulerBodies=[{x:280,y:70,width:120,height:90}];
const rulerX=measurementColumn(440,[100,120],rulerBodies,400,80);
assert.ok(rulerX<=388&&rulerX<280,'ruler stays inside the plot and leaves crowded candles');
const rulerLabel=placeLabels([{id:'ruler',t:1,x:rulerX-54,priority:3,anchor:100,below:false,lines:['4.75 pts'],width:80,height:26,color:'#dec38c'}],rulerBodies,400,300)[0];
assert.ok(rulerLabel.box,'ruler value remains visible beside its bracket');
const belowBodies=[{x:260,y:112,width:130,height:100}];
const chipColumn=measurementColumn(380,[100,134],belowBodies,400,80);
const candidateChip=placeLabels([{id:'ob-candidate',t:1,x:chipColumn-54,priority:4.5,anchor:100,below:true,lines:['OB? M15'],width:80,height:26,color:'#dec38c'}],belowBodies,400,300)[0];
assert.ok(candidateChip.box,'candidate clearance includes the below-wick chip area');
assert.ok(!overlaps(rulerLabel.box,rulerBodies[0],2));
assert.equal(axisPrice(4390.000),'4,390');assert.equal(axisPrice(4390.8),'4,391');
assert.equal(chipPrice(4374.082),'4,374.08');
const object={id:'signal',shape:'LABEL',points:[{t_ms:1,price:4360.703}],style:{token:'utbot.sell'},text_args:{label:'ATR 13.379 k=1.0'},reason:'close 4360.703 crossed below UT stop 4374.082 (ATR 13.379, k=1.0)'};
assert.deepEqual(labelLines(object),[]);
assert.deepEqual(labelLines({...object,text_args:{active_signal:true}}),['SELL']);
const fvg={...object,shape:'ZONE',style:{token:'zone.fvg'},text_args:{strength:3,fill_pct:.41}};
assert.deepEqual(labelLines(fvg),['FVG 3  41%']);
assert.deepEqual(labelLines({...fvg,text_args:{strength:1,fill_pct:.62}}),['FVG  62%']);
assert.deepEqual(labelLines({...fvg,text_args:{weakened:true}}),['FVG  CE lost']);
assert.deepEqual(labelLines({...fvg,text_args:{kind:'IFVG'}}),['IFVG']);
assert.deepEqual(labelLines({...object,style:{token:'utbot.provisional'},text_args:{direction:'BULLISH',active_signal:true}}),['BUY']);
assert.deepEqual(labelLines({...object,style:{token:'retention.level'},text_args:{label:'PDH'}}),['PDH 4,360.70']);
assert.deepEqual(labelLines({...object,style:{token:'structure.event'},text_args:{kind:'CHoCH'}})[0].startsWith('CHoCH'),true);
assert.deepEqual(labelLines({...object,style:{token:'structure.protected'},text_args:{}}),['PROTECTED']);
assert.ok(labelPriority({...object,style:{token:'structure.event'},text_args:{kind:'CHoCH'}})>labelPriority({...object,style:{token:'structure.event'},text_args:{kind:'BOS'}}));
assert.equal(compactCallReason('Swept EQL 4,331.40 at 13:47, reclaimed in 2 bars (ATR 13.379, k=1.0)'),'EQL 4,331.40 13:47');
assert.equal(compactCallReason('CHoCH 4350.202 (ATR(123), period=5000, k=1,234.56)'),'CHOCH 4,350.20');
const candidate=(id,t,x,priority=1)=>({id,t,x,priority,anchor:100,below:true,lines:['Buy'],width:45,height:26,color:'#53d4b6'});
const dense=Array.from({length:200},(_,i)=>candidate(String(i),i,20+(i%20)*50));
const placements=placeLabels(dense,[],1100,400);
assert.equal(placements.filter(p=>p.box).length,10,'annotation text cap');
assert.equal(placements.filter(p=>!p.box).length,190,'excess signals become markers');
assert.deepEqual(placements.filter(p=>p.box).map(p=>p.candidate.t),[199,198,197,196,195,194,193,192,191,190],'latest signals win');
const bodies=[{x:80,y:105,width:40,height:65}];
const nudged=placeLabels([candidate('nudge',1,100)],bodies,400,300)[0];
assert.equal(overlaps(nudged.box,bodies[0],2),false,'label clears candle body');
assert.equal(placeLabels([candidate('blocked',1,100)],[{x:0,y:0,width:400,height:400}],400,400)[0].box,null);
const call={...candidate('call',0,100,5),lines:['EQL 4,331.40','CHOCH 4,350.20','H1 OB'],height:66};
const level={...candidate('level',0,100,50),pinnedLevel:true,levelPrice:4300,lines:['EQL 2'],width:54,height:26,color:'#97A0AE'};
const event={...candidate('event',1,100,80),lines:['BOS'],width:38,height:26,color:'#D9A441'};
const cross=placeLabels([event,level],[],400,300);
assert.ok(cross.find(p=>p.candidate.id==='level')?.box,'level label reserves its line');
assert.equal(overlaps(cross.find(p=>p.candidate.id==='event').box,cross.find(p=>p.candidate.id==='level').box,3),false,'events collision-test against level labels');
const reserved=placeLabels([{...level,id:'brand-level',anchor:284,x:380}],[],420,320,10,[{x:294,y:288,width:122,height:28}]);
assert.ok(!reserved[0].box||!overlaps(reserved[0].box,{x:294,y:288,width:122,height:28},3),'labels avoid the corner brand box');
const mixed=placeLabels([call,...dense],[],1100,600);
assert.equal(mixed[0].candidate.id,'call');assert.ok(mixed[0].box);
assert.equal(mixed.filter(p=>p.box).reduce((n,p)=>n+p.candidate.lines.length,0),10,'strips share the cap');
const boxes=mixed.filter(p=>p.box).map(p=>p.box);
for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++)assert.equal(overlaps(boxes[i],boxes[j],3),false);
assert.ok(labelPriority({...object,style:{token:'analysis.entry'}})>labelPriority({...object,shape:'ZONE'}));
assert.ok(labelPriority({...object,shape:'ZONE'})>labelPriority({...object,style:{token:'retention.level'}}));
assert.ok(labelPriority({...object,style:{token:'structure.event'},text_args:{kind:'BOS'}})>labelPriority({...object,style:{token:'retention.level'}}));
assert.ok(labelPriority({...object,style:{token:'structure.bos'}})>labelPriority(object));
console.log('Label checks passed: cap, priority, two nudges, candle clearance, markers, formats and drawer-only signal reasons.');








const bosDown=labelLines({...object,style:{token:'structure.event'},text_args:{kind:'BOS',direction:'DOWN'}})[0];
assert.ok(!/BOS v/.test(bosDown),'structure down label must not fall back to ASCII v');
assert.ok(/BOS ?/.test(bosDown),'structure down label uses UTF-8 arrow');
