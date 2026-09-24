import {useEffect,useRef,useState} from 'react';
import type {WorkDecision,Decision} from '../net/chart';
import {livingBudget} from './budget';
import {renderTrace} from './trace';
import {fmt} from '../fmt';
import {copy} from '../copy';
const traced=new Set<string>();

export function decisionWorklog(decisions:Decision[]):WorkDecision[]{
 for(const d of decisions){
  const id=`decision:${d.seq}:${d.object_id}:${d.action}`;
  if(!traced.has(id)){traced.add(id);renderTrace('WORKLOG_ENTRY',id,{seq:d.seq,object_id:d.object_id,action:d.action,tf:d.tf,reason:d.reason});}
 }
 return decisions.slice(-8).map(d=>{
  const action=d.action==='CREATE'?'marked':d.action==='PROMOTE'?'confirmed':d.action==='DISCARD'?'discarded':'updated';
  const kind=d.kind==='POOL'?'pool':String(d.kind).toLowerCase();
  const detail=d.reason?String(d.reason).toLowerCase().replaceAll('_',' '):fmt.range(d.geometry.price_lo,d.geometry.price_hi);
  return {id:`decision:${d.seq}:${d.object_id}:${d.action}`,at_ms:d.t_utc_ms,tf:d.tf,object_id:d.object_id,action:'MARKED',label:copy.worklog.decision(action,d.tf,kind,detail),source_bars:d.source_bars,source_object_ids:d.source_object_ids};
 });
}
export function Worklog({entries,now}:{entries:WorkDecision[];now:number}){
  const seen=useRef(new Set<string>()),initial=useRef(true);
  const [motion,setMotion]=useState(true);
  useEffect(()=>{let live=true;window.oracle?.livingConfig?.().then(c=>{if(live)setMotion(c.candidates_enabled||c.attention_enabled||c.reeval_sweep_enabled||c.measurement_gesture.enabled||c.session_scan_enabled||c.camera_drift_enabled);}).catch(()=>{});return()=>{live=false;};},[]);
  useEffect(()=>{
    const fresh=entries.filter(e=>!seen.current.has(e.id));
    for(const e of entries)seen.current.add(e.id);
    if(initial.current){initial.current=false;return;}
    if(!motion)return;
    if(!fresh.length)return;
    livingBudget.admit(fresh.map(e=>({id:`worklog:${e.id}`,kind:'draw',duration:450})),performance.now());
  },[entries,motion]);
  void now;
  return <section className="worklog" aria-label="Analyst worklog"><div className="rail-heading"><span>{copy.rail.worklog}</span><small>{copy.rail.utc}</small></div>
    {!entries.length?<p className="context-note">Waiting for an engine decision</p>:<ol>{[...entries].reverse().slice(0,8).map(entry=><li key={entry.id} data-decision-id={entry.id}><time>{fmt.time(entry.at_ms)}</time><span>{entry.label}</span></li>)}</ol>}
  </section>;
}
