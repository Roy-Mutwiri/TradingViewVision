import {sessionIntervals} from '../stream/SessionRibbon';
export type SessionBoundary={name:string;at:number;id:string};
/** Same calendar as the ribbon; initial load/reconnect never synthesises a crossing. */
export class SessionBoundaries {
 private previous?:number;
 private seen=new Set<string>();
 observe(now:number,connected=true):SessionBoundary|null{
  if(!connected){this.previous=undefined;return null;}
  const before=this.previous;this.previous=now;
  if(before===undefined||now<before)return null;
  const boundary=sessionIntervals(now).map(s=>({name:s.name,at:s.start,id:`session:${s.name}:${s.start}`})).find(s=>before<s.at&&s.at<=now&&!this.seen.has(s.id));
  if(!boundary)return null;
  this.seen.add(boundary.id);return boundary;
 }
}
