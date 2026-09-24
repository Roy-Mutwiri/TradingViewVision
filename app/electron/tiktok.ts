import {spawn,type ChildProcessWithoutNullStreams} from 'node:child_process';
import {createInterface} from 'node:readline';
import {appendFileSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import type {ConnectionTest,StreamConfig,TikTokStatus,TikTokWelcome,TikTokComment} from '../src/stream/types';
type StoredViewer={name:string;first_seen_ms:number;last_seen_ms:number;join_count:number};
export class TikTokService {
  private child:ChildProcessWithoutNullStreams|null=null;
  status:TikTokStatus={state:'NOT_CONFIGURED',username:null,viewers:null,live_since_ms:null,last_checked_ms:Date.now(),error:null};
  constructor(private root:string,private publish:(status:TikTokStatus)=>void,private publishWelcome:(welcome:TikTokWelcome)=>void,private publishComment:(comment:TikTokComment)=>void){}
  private rememberViewer(welcome:TikTokWelcome):TikTokWelcome{
    const dir=resolve(this.root,'runtime/desktop'),path=resolve(dir,'tiktok-viewers.json');
    mkdirSync(dir,{recursive:true});
    let db:Record<string,StoredViewer>={};
    try{db=JSON.parse(readFileSync(path,'utf8')) as Record<string,StoredViewer>;}catch{db={};}
    const key=welcome.name.trim().toLowerCase();
    const previous=db[key];
    const join_count=(previous?.join_count??0)+1;
    const stored={name:welcome.name,first_seen_ms:previous?.first_seen_ms??welcome.at_ms,last_seen_ms:welcome.at_ms,join_count};
    db[key]=stored;
    writeFileSync(path,JSON.stringify(db,null,2));
    return {...welcome,returning:!!previous,join_count,first_seen_ms:stored.first_seen_ms};
  }
  configure(config:StreamConfig){
    const username=config.tiktok.username.trim().replace(/^@/,'');
    this.status={state:username?'CONNECTING':'NOT_CONFIGURED',username:username||null,viewers:null,live_since_ms:null,last_checked_ms:Date.now(),error:null};
    this.publish(this.status);
    if(!this.child){
      const child=spawn(resolve(this.root,'app/.venv-stream/Scripts/python.exe'),[resolve(this.root,'app/desktop/tiktok_status.py'),'--watch'],{cwd:this.root,windowsHide:true,env:{...process.env,PYTHONUNBUFFERED:'1',PYTHONIOENCODING:'utf-8'}});
      this.child=child;child.stderr.resume();
      const unavailable=()=>{if(this.child!==child)return;this.child=null;this.status={...this.status,state:'UNKNOWN',last_checked_ms:Date.now(),error:'TikTok service unavailable'};this.publish(this.status);};
      child.on('error',unavailable);child.on('exit',unavailable);
      createInterface({input:child.stdout}).on('line',line=>{try{const packet=JSON.parse(line);if(packet.welcome)this.publishWelcome(this.rememberViewer(packet.welcome));if(packet.comment)this.publishComment(packet.comment);if(packet.status){this.status=packet.status;this.publish(this.status);}if(packet.event&&packet.event!=='status'){mkdirSync(resolve(this.root,'runtime/desktop'),{recursive:true});appendFileSync(resolve(this.root,'runtime/desktop/tiktok-events.jsonl'),JSON.stringify(packet)+'\n');}}catch{/* TikTok failures never cross into chart IPC. */}});
    }
    this.child?.stdin.write(JSON.stringify(config.tiktok)+'\n');
  }
  stop(){const child=this.child;this.child=null;child?.stdin.end();if(child)setTimeout(()=>child.kill(),3000).unref();}
}
export function testTikTok(root:string,username:string):Promise<ConnectionTest>{
  return new Promise(resolveTest=>{
    const child=spawn(resolve(root,'app/.venv-stream/Scripts/python.exe'),[resolve(root,'app/desktop/tiktok_status.py'),username],{cwd:root,windowsHide:true,stdio:['ignore','pipe','ignore'],env:{...process.env,PYTHONIOENCODING:'utf-8'}});
    let output='',done=false;
    const finish=(result:ConnectionTest)=>{if(done)return;done=true;clearTimeout(timer);resolveTest(result);};
    const unavailable:ConnectionTest={outcome:'UNREACHABLE',message:'Could not reach TikTok',profile_name:null};
    const timer=setTimeout(()=>{child.kill();finish(unavailable);},25000);
    child.stdout.on('data',data=>{output+=data;});child.on('error',()=>finish(unavailable));
    child.on('exit',()=>{try{finish(JSON.parse(output.trim()));}catch{finish(unavailable);}});
  });
}
