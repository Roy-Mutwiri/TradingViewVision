import {readFileSync,readdirSync,existsSync} from 'node:fs';
import {join,relative} from 'node:path';
const root=process.cwd();
const base=existsSync(join(root,'src'))?join(root,'src'):join(root,'app','src');
function walk(dir,out=[]){for(const f of readdirSync(dir,{withFileTypes:true})){const p=join(dir,f.name);if(f.isDirectory())walk(p,out);else if(/\.(ts|tsx|css)$/.test(f.name))out.push(p);}return out;}
const bad=[];
const banned=[/institutions?/i,/smart\s*money\s+wants/i,/wants\s+to\s+(?:buy|sell|hunt|take)/i,/market\s+makers?\s+wants/i];
for(const file of walk(base)){
  const text=readFileSync(file,'utf8');
  for(const [i,line] of text.split(/\r?\n/).entries()){
    if(/[âÃ]/.test(line))bad.push(`${relative(root,file)}:${i+1}: ${line.trim()}`);
  }
}
if(bad.length){console.error('Rendered/source text contains mojibake sentinel bytes or why-rule banned phrases:');console.error(bad.join('\n'));process.exit(1);}
console.log(JSON.stringify({mojibake_patterns:0,files_scanned:walk(base).length},null,2));
