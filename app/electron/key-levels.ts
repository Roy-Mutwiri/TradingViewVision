import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import type {KeyLevelContext} from '../src/stream/types';
export function captureHistory(root:string,profile:{login:number;server:string}):Promise<void>{
  return new Promise(done=>{const child=spawn(resolve(root,'.venv312/Scripts/python.exe'),[resolve(root,'app/desktop/snapshot_history.py'),root],{cwd:root,windowsHide:true});
    child.stdout.resume();child.stderr.resume();const timer=setTimeout(()=>{child.kill();done();},5000);
    child.on('error',()=>{clearTimeout(timer);done();});child.on('exit',()=>{clearTimeout(timer);done();});child.stdin.end(JSON.stringify(profile));});
}
export function readKeyLevels(root:string,profile:{login:number;server:string},now_ms:number):Promise<KeyLevelContext>{
  return new Promise(resolveResult=>{
    const child=spawn(resolve(root,'.venv312/Scripts/python.exe'),[resolve(root,'app/desktop/key_levels.py'),root],{cwd:root,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
    let output='';let done=false;const finish=(result:KeyLevelContext)=>{if(done)return;done=true;clearTimeout(timer);resolveResult(result);};
    const empty:KeyLevelContext={pdh:null,pdl:null,weekly_open:null};
    const timer=setTimeout(()=>{child.kill();finish(empty);},30000);
    child.stdout.on('data',chunk=>output+=chunk);child.stderr.resume();child.on('error',()=>finish(empty));
    child.on('exit',()=>{try{finish(JSON.parse(output.trim()));}catch{finish(empty);}});
    child.stdin.end(JSON.stringify({profile,now_ms}));
  });
}
