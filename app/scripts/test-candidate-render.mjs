import {build} from 'esbuild';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const bundle=await build({stdin:{contents:"export * from './src/chart/FVGZones';export * from './src/living/trace';export * from './src/living/types';",resolveDir:process.cwd()},bundle:true,platform:'node',format:'esm',write:false});
const {FVGZones,traceSnapshot,defaultLiving}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const snapshots=readFileSync('../runtime/ui-proof/render-replay.jsonl','utf8').trim().split('\n').map(JSON.parse);
globalThis.requestAnimationFrame=()=>1;globalThis.cancelAnimationFrame=()=>{};
let now=0;Object.defineProperty(globalThis,'performance',{value:{now:()=>now},configurable:true});
const expected=snapshots.flatMap(s=>s.decisions).filter(d=>d.action==='DISCARD');
for(const speed of [1,100])for(const enabled of [true,false]){
 const primitive=new FVGZones(),traceStart=traceSnapshot().length;
 primitive.setLiving({...defaultLiving,candidates_enabled:enabled,attention_enabled:enabled,reeval_sweep_enabled:enabled});
 const input=JSON.stringify(snapshots);
 for(const snapshot of snapshots){now=snapshot.at/speed;primitive.update(snapshot.objects);primitive.visibleObjects();}
 const fades=traceSnapshot().slice(traceStart).filter(t=>t.event==='FADE');
 assert.equal(fades.length,expected.length,`one actual fade per discard at speed ${speed}, motion ${enabled}`);
 assert.deepEqual(new Set(fades.map(t=>t.object_id)),new Set(expected.map(d=>d.object_id)));
 assert.ok(fades.every(t=>t.duration===600&&t.reason_chip&&t.reason&&t.mandatory));
 now+=600;assert.equal(primitive.visibleObjects().filter(o=>o.text_args.lifecycle==='DISCARDED').length,0);
 assert.equal(JSON.stringify(snapshots),input,'living flags and renderer must not alter the DrawPlan');
 primitive.detached();
}
console.log(`Actual renderer trace verified: ${expected.length} reasoned fades per run, both speeds and motion flag states; DrawPlans unchanged.`);
