import esbuild from 'esbuild';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const tmp=mkdtempSync(join(tmpdir(),'oracle-analysis-objects-'));
const out=join(tmp,'analysisObjects.mjs');
await esbuild.build({entryPoints:[join(process.cwd(),'src/analysisObjects.ts')],bundle:true,platform:'node',format:'esm',outfile:out});
const {confluenceGroups}=await import(pathToFileURL(out).href);
const close=[{id:'a',price:100,tag:'EQH'},{id:'b',price:100.2,tag:'NY H'},{id:'c',price:100.4,tag:'0.618'}];
const far=[...close,{id:'d',price:104,tag:'PROTECTED'}];
const groups=confluenceGroups(far,1);
if(!groups.length)throw new Error('expected close confluence group');
for(const group of groups){
  const prices=group.map(item=>item.price);
  if(Math.max(...prices)-Math.min(...prices)>1.000001)throw new Error('confluence group exceeds band width');
  if(group.some(item=>item.id==='d'))throw new Error('source 1 ATR away was counted in confluence');
}
console.log(JSON.stringify({groups:groups.length,denominator_sources:far.length,far_source_counted:false},null,2));
