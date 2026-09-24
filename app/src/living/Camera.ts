export interface CameraConfig {enabled:boolean;drift_px_per_min:number;breathe_pct:number;breathe_period_s:number;snap_on_event:boolean;max_offset_px:number}
export const defaultCamera:CameraConfig={enabled:true,drift_px_per_min:6,breathe_pct:.4,breathe_period_s:45,snap_on_event:true,max_offset_px:24};
/** Canvas decoration only. No chart viewport or market state is owned here. */
export class CameraMotion {
 private last?:number;
 private elapsed=0;
 private offset=0;
 private snap?:{at:number;from:number};
 constructor(private config=defaultCamera){}
 configure(config:CameraConfig){this.config=config;if(!config.enabled){this.offset=0;this.snap=undefined;}}
 recentre(now:number){if(this.config.enabled&&this.config.snap_on_event)this.snap={at:now,from:this.offset};}
 cancelSnap(){this.snap=undefined;}
 step(now:number,allowedX:number,paused=false){
  const delta=this.last===undefined?0:Math.max(0,now-this.last);this.last=now;
  if(!this.config.enabled)return {x:0,scaleY:1,paused:false};
  if(!paused){
   this.elapsed+=delta;
   if(this.snap){const p=Math.min(1,(now-this.snap.at)/700);this.offset=this.snap.from*(1-p)**3;if(p>=1)this.snap=undefined;}
   else this.offset+=delta*this.config.drift_px_per_min/60000;
  }
  this.offset=Math.max(0,Math.min(this.offset,Math.max(0,allowedX),Math.min(24,this.config.max_offset_px)));
  const amplitude=Math.max(0,Math.min(.4,this.config.breathe_pct))/100;
  return {x:this.offset,scaleY:1+amplitude*Math.sin(this.elapsed/(Math.max(1,this.config.breathe_period_s)*1000)*2*Math.PI),paused};
 }
}
