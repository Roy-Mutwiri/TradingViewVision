import {build} from 'esbuild';
import assert from 'node:assert/strict';
const b=await build({stdin:{contents:"export * from './src/chart/FVGZones';export * from './src/chart/labels';export * from './src/living/trace';export * from './src/living/types';",resolveDir:process.cwd()},bundle:true,platform:'node',format:'esm',write:false});
const {FVGZones,labelLines,traceSnapshot,defaultLiving,placeLabels}=await import(`data:text/javascript;base64,${Buffer.from(b.outputFiles[0].text).toString('base64')}`);
globalThis.requestAnimationFrame=()=>1;globalThis.cancelAnimationFrame=()=>{};
let now=0;Object.defineProperty(globalThis,'performance',{value:{now:()=>now},configurable:true});
const pool=(id,args={})=>({id,layer:'L2',shape:'LINE',points:[{t_ms:0,price:100},{t_ms:1000,price:100}],style:{token:'liquidity.pool'},text_key:id,text_args:{zone_id:id,tf:'M15',name:'EQH',strength:3,pool_state:'FRESH',confirmed:true,end_ms:2000,ce:100,opacity:1,...args}});
const zones=new FVGZones();zones.setLiving({...defaultLiving,candidates_enabled:false,attention_enabled:false});zones.update(Array.from({length:20},(_,i)=>pool(`pool${i}`)));assert.equal(zones.visibleObjects().length,6);
assert.deepEqual(labelLines(pool('equal')),['EQH 3']);assert.deepEqual(labelLines(pool('named',{name:'PDH',strength:1})),['PDH']);
const pending=pool('pending',{confirmed:false,lifecycle:'CANDIDATE',bars_left:2});assert.deepEqual(labelLines(pending),['SWEEP? 2 bars']);assert.equal(zones.opacity(pending),.45);
const swept=pool('swept',{pool_state:'SWEPT',swept_ms:Date.UTC(2026,8,18,14,22),opacity:.35});assert.deepEqual(labelLines(swept),['SWEPT 14:22']);assert.equal(zones.opacity(swept),.35);
for(const reason of ['INVALIDATED','STALE','DATA_GAP']){
 const object=pool(reason,{confirmed:false,lifecycle:'DISCARDED',discard_reason:reason,decision_id:`discard.${reason}`});zones.update([object]);assert.ok(traceSnapshot().some(t=>t.event==='FADE'&&t.reason===reason&&t.mandatory&&t.duration===600));now+=300;assert.equal(zones.opacity(object),.225);now+=300;assert.equal(zones.visibleObjects().length,0);
}
const labels=Array.from({length:30},(_,i)=>({id:String(i),t:i,priority:3,x:80+(i%5)*130,anchor:40+Math.floor(i/5)*70,below:false,lines:['EQH 3'],width:75,height:26,color:'#dec38c'}));assert.ok(placeLabels(labels,[],800,600).filter(x=>x.box).length<=10);
console.log('Liquidity renderer passed: six pools, strength/countdown/swept chips, 45% candidates, 35% swept and mandatory reasoned 600ms fades; ten-label cap.');
