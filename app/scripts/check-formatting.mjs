import {readFileSync,readdirSync,existsSync} from 'node:fs';
import {join} from 'node:path';
const root=process.cwd();
function walk(dir,out=[]){for(const f of readdirSync(dir,{withFileTypes:true})){const p=join(dir,f.name);if(f.isDirectory())walk(p,out);else if(/\.(ts|tsx)$/.test(f.name))out.push(p);}return out;}
const base=existsSync(join(root,'src'))?join(root,'src'):join(root,'app','src');
const files=walk(base).map(f=>f.replaceAll('\\','/'));
const offenders=[];
for(const abs of files){
  const rel=abs.slice(root.replaceAll('\\','/').length+1);
  if(rel.endsWith('/fmt.ts')||rel.includes('/net/')||rel.includes('/scripts/'))continue;
  const text=readFileSync(abs,'utf8');
  for(const [i,line] of text.split(/\r?\n/).entries()){
    if(/\.toFixed\s*\(|\.toLocaleString\s*\(/.test(line))offenders.push(`${rel}:${i+1}: ${line.trim()}`);
  }
}
if(offenders.length){console.error('Number formatting must go through src/fmt.ts');console.error(offenders.join('\n'));process.exit(1);} 
