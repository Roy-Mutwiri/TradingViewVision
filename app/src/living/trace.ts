export type RenderEvent={at:number;event:string;id:string;duration?:number;[key:string]:unknown};
const events:RenderEvent[]=[];
/** Presentation audit only; never read by the engine or used as market evidence. */
export function renderTrace(event:string,id:string,detail:Record<string,unknown>={}){
  events.push({at:performance.now(),event,id,...detail});
  if(events.length>50000)events.splice(0,events.length-50000);
}
export function traceSnapshot(){return events.map(e=>({...e}));}
if(typeof window!=='undefined')Object.assign(window,{oracleRenderTrace:traceSnapshot});
