const fs=require('fs');
const readline=require('readline');
(async()=>{
 const rl=readline.createInterface({input:fs.createReadStream('runtime/ui-proof/honesty-day/records.jsonl',{encoding:'utf8'}),crlfDelay:Infinity});
 let pass=null,fail=null,flip=null,prev=null;
 for await (let line of rl){
  if(!line)continue; if(line.charCodeAt(0)===0xFEFF)line=line.slice(1);
  const r=JSON.parse(line); const d=r.thesis?.dry_run; if(!d||d.reward_r==null)continue;
  const item={time:r.broker_time,seq:r.eval.seq,passes:d.passes,first_fail:d.first_fail,reward_r:d.reward_r,tp1_name:d.tp1_name,tp1:d.tp1,zone:`${d.zone_lo}-${d.zone_hi}`,target_close_note:d.target_close_note,headline:r.thesis.headline,line:(r.thesis.lines||[])[3]};
  if(d.passes&&!pass)pass=item; if(!d.passes&&!fail)fail=item;
  const key=`${d.zone_id}:${d.passes}:${d.first_fail}:${Math.round(d.reward_r*10)}:${Math.round((d.tp1||0)*100)}`;
  if(prev&&prev.key!==key&&prev.passes!==d.passes&&!flip)flip={from:prev.item,to:item,interruptKey:`DRY:${key}`};
  prev={key,passes:d.passes,item};
  if(pass&&fail&&flip)break;
 }
 const out={pass,fail,flip}; fs.writeFileSync('runtime/ui-proof/honesty-day/dry-run-examples.json',JSON.stringify(out,null,2)); console.log(JSON.stringify(out,null,2));
})();
