import {renderTrace} from './trace';
export type VisualKind='call'|'structure'|'promotion'|'discard'|'measurement'|'session'|'sweep'|'drift'|'attention'|'draw';
const priority:Record<VisualKind,number>={call:8,structure:7.5,promotion:7,discard:6,measurement:5,attention:4,draw:4,session:3,sweep:3,drift:2};
export interface VisualRequest {id:string;kind:VisualKind;duration:number;cancel?:()=>void}
/** Explicit clock, bounded sliding window, no delayed animation queue. */
export class VisualBudget {
  private starts:number[]=[];
  private active=new Map<string,{until:number;priority:number;cancel?:()=>void}>();
  private reserved=0;
  dropped=0;
  constructor(private perMinute=12,private concurrent=3){}
  reserve(count:number,now:number){
    this.reserved=Math.max(0,Math.min(this.concurrent,count));
    for(const [id,item] of this.active)if(item.until<=now)this.active.delete(id);
    while(this.active.size>this.concurrent-this.reserved){
      const lowest=[...this.active].sort((a,b)=>a[1].priority-b[1].priority||a[0].localeCompare(b[0]))[0];
      this.active.delete(lowest[0]);lowest[1].cancel?.();renderTrace('ANIMATION_CANCEL',lowest[0],{reason:'reserved motion slot'});
    }
  }
  admit(requests:VisualRequest[],now:number):VisualRequest[]{
    this.starts=this.starts.filter(at=>at>now-60000);
    for(const [id,item] of this.active)if(item.until<=now)this.active.delete(id);
    const accepted:VisualRequest[]=[];
    for(const request of [...requests].sort((a,b)=>priority[b.kind]-priority[a.kind]||a.id.localeCompare(b.id))){
      if(this.active.has(request.id))continue;
      if(this.starts.length<this.perMinute&&this.active.size>=this.concurrent-this.reserved&&this.active.size){
        const lowest=[...this.active].sort((a,b)=>a[1].priority-b[1].priority||a[0].localeCompare(b[0]))[0];
        if(priority[request.kind]>lowest[1].priority){this.active.delete(lowest[0]);lowest[1].cancel?.();renderTrace('ANIMATION_CANCEL',lowest[0],{reason:'higher priority animation'});}
      }
      if(this.starts.length>=this.perMinute||this.active.size>=this.concurrent-this.reserved){this.dropped++;renderTrace('ANIMATION_DROP',request.id,{kind:request.kind});continue;}
      const duration=Math.max(0,Math.min(request.kind==='session'?1200:800,request.duration));
      this.starts.push(now);this.active.set(request.id,{until:now+duration,priority:priority[request.kind],cancel:request.cancel});
      renderTrace('ANIMATION',request.id,{kind:request.kind,duration,reserved:this.reserved,concurrent:this.active.size});
      accepted.push({...request,duration});
    }
    return accepted;
  }
  get running(){return this.active.size;}
}
export let livingBudget=new VisualBudget();
export function configureBudget(perMinute:number,concurrent:number){livingBudget=new VisualBudget(Math.min(12,Math.max(0,perMinute)),Math.min(3,Math.max(0,concurrent)));}
