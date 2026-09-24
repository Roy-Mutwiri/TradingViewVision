import {build} from 'esbuild';import assert from 'node:assert/strict';
const b=await build({stdin:{contents:"export * from './src/chart/FVGZones';export * from './src/chart/labels';export * from './src/living/types';",resolveDir:process.cwd()},bundle:true,platform:'node',format:'esm',write:false});
const {FVGZones,labelLines,labelPriority,defaultLiving}=await import(`data:text/javascript;base64,${Buffer.from(b.outputFiles[0].text).toString('base64')}`);
globalThis.requestAnimationFrame=()=>1;globalThis.cancelAnimationFrame=()=>{};Object.defineProperty(globalThis,'performance',{value:{now:()=>0},configurable:true});
const call={id:'c',layer:'L2',shape:'ZONE',points:[{t_ms:1,price:93},{t_ms:2,price:94}],style:{token:'call.trade'},text_key:'c',text_args:{call_id:'c',call_state:'ACTIVE',direction:'BULLISH',entry_lo:93,entry_hi:94,stop:92,tp1:97,tp2:99,reward_r:2.33,live_r:.7,end_ms:3},state:'FRESH'};
const zones=new FVGZones();zones.setLiving({...defaultLiving,attention_enabled:false});zones.update([call]);assert.equal(zones.visibleObjects()[0].id,'c');assert.equal(labelPriority(call),5);const lines=labelLines(call);assert.equal(lines.length,5);assert.match(lines[0],/^ENTRY 93\.00.+94\.00  ACTIVE$/);assert.deepEqual(lines.slice(1),['SL 92.00','TP1 97.00  2.3R','TP2 99.00','LIVE +0.7R']);console.log('Call rendering passed.');
const cancelled={...call,text_args:{...call.text_args,call_state:'CANCELLED',lifecycle:'DISCARDED',resolution_reason:'SUPERSEDED_BY_NEW_ANALYSIS'}};assert.deepEqual(labelLines(cancelled),['CANCELLED  superseded by new analysis']);

