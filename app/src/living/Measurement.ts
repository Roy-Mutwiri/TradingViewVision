import type {Decision} from '../net/chart';
import type {DrawObject} from '../net/protocol';
import {livingBudget} from './budget';
import {renderTrace} from './trace';
/** Recorded decision operands/result, never recomputed market arithmetic. */
export class MeasurementGesture {
 private seen=new Set<string>();
 private last=-Infinity;
 private active?:{decision:Decision;at:number;id:string;faded:boolean;opening:boolean};
 consider(decisions:Decision[],now:number,enabled:boolean,interval=180000){
  const fresh=decisions.filter(d=>!this.seen.has(`${d.tf}:${d.seq}:${d.object_id}:${d.action}`));
  for(const d of decisions)this.seen.add(`${d.tf}:${d.seq}:${d.object_id}:${d.action}`);
  if(!enabled||now-this.last<Math.max(180000,interval))return;
  const decision=[...fresh].reverse().find(d=>d.measurement&&d.source_bars.length);
  if(!decision)return;
  const id=`measurement:${decision.tf}:${decision.seq}:${decision.object_id}:${decision.action}`;
  if(!livingBudget.admit([{id,kind:'measurement',duration:450,cancel:()=>{if(this.active?.id===id)this.active.opening=false;}}],now).length)return;
  this.last=now;this.active={decision,at:now,id,faded:false,opening:true};
  renderTrace('MEASUREMENT',id,{seq:decision.seq,object_id:decision.object_id,tf:decision.tf,measurement:decision.measurement,hold_ms:2500});
 }
 object(now:number,t_ms:number):DrawObject|null{
  const active=this.active;if(!active)return null;
  const age=now-active.at;
  if(age>=3100){this.active=undefined;return null;}
  if(age>=2500&&!active.faded){active.faded=true;renderTrace('MEASUREMENT_FADE',active.id,{duration:600});}
  const m=active.decision.measurement!;
  return {id:active.id,layer:'L3',shape:'PATH',points:[{t_ms,price:m.price_a},{t_ms,price:m.price_b}],style:{token:'living.measurement'},text_key:active.id,text_args:{value:m.value,unit:m.unit,opacity:age<2500?1:1-(age-2500)/600,progress:active.opening?Math.min(1,age/450):1},reason:m.criterion,confidence:1,priority:3,z:1,state:'FRESH',ttl_ms:3100,anim:{in_:'none',loop:null},source_bars:[active.decision.source_bars[0],...active.decision.source_bars.slice(1)]};
 }
 clear(){this.active=undefined;}
 isFading(now:number){return !!this.active&&now-this.active.at>=2500&&now-this.active.at<3100;}
}
