const fs=require('fs');
const events=fs.readFileSync('runtime/ui-proof/call-in-sample-target-eq-2/ledger.jsonl','utf8').trim().split(/\r?\n/).filter(Boolean).map(l=>JSON.parse(l));
const latest=new Map(); for(const e of events){latest.set(e.call_id,e.call);} const rows=[...latest.values()];
function stats(calls){
 const wins=calls.filter(c=>c.state==='WIN'), losses=calls.filter(c=>c.state==='LOSS'), resolved=[...wins,...losses];
 let streak=0,best=0; for(const c of resolved.sort((a,b)=>(a.resolved_ms||0)-(b.resolved_ms||0))){streak=c.state==='LOSS'?streak+1:0; best=Math.max(best,streak);} 
 const ret=resolved.map(c=>c.state==='WIN'?Math.abs(c.target-(c.entry_ref??((c.entry_lo+c.entry_hi)/2)))/Math.abs((c.entry_ref??((c.entry_lo+c.entry_hi)/2))-c.invalidation):-1);
 const states={}; for(const c of calls)states[c.state]=(states[c.state]||0)+1;
 return {calls:calls.length,states,hit_rate:resolved.length?wins.length/resolved.length:null,expectancy_r:ret.length?ret.reduce((a,b)=>a+b,0)/ret.length:null,longest_losing_streak:best,calls_per_day:calls.length/((1789751280000-1780958160000)/86400000)};
}
const out={A:stats(rows.filter(c=>(c.grade||'A')==='A')),B:stats(rows.filter(c=>c.grade==='B')),overall:stats(rows)};
fs.writeFileSync('runtime/ui-proof/call-in-sample-target-eq-2/grade-table-step4.json',JSON.stringify(out,null,2));
console.log(JSON.stringify(out,null,2));
