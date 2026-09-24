import {useEffect,useState} from 'react';
import sessions from '../../../config/session-definitions.json';
export function sessionIntervals(now:number){
  const date=new Date(now);const day=Date.UTC(date.getUTCFullYear(),date.getUTCMonth(),date.getUTCDate());
  return sessions.map(session=>{
    const value=new Intl.DateTimeFormat('en-US',{timeZone:session.zone,timeZoneName:'longOffset'}).formatToParts(day+12*3600000).find(part=>part.type==='timeZoneName')!.value;
    const match=value.match(/GMT([+-])(\d{2}):(\d{2})/);const offset=match?(match[1]==='-'?-1:1)*(Number(match[2])*60+Number(match[3])):0;
    return {name:session.name,start:day+(session.open*60-offset)*60000,end:day+(session.close*60-offset)*60000,day};
  });
}
export function SessionRibbon(){
  const [now,setNow]=useState(Date.now());useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
  const intervals=sessionIntervals(now);const day=intervals[0].day;
  const boundaries=[...intervals,...sessionIntervals(day+86400000)].flatMap(session=>[{at:session.start,label:`${session.name} open`},{at:session.end,label:`${session.name} close`}]).filter(item=>item.at>now).sort((a,b)=>a.at-b.at);
  const next=boundaries[0];const time=(ms:number)=>new Date(ms).toISOString().slice(11,16);
  return <section className="session-ribbon" aria-label="24 hour session ribbon"><div className="ribbon-caption"><span>SESSIONS · UTC</span><span>NEXT · {next.label.toUpperCase()} {time(next.at)}</span></div>
    <div className="session-track">{intervals.map(session=>{const active=now>=session.start&&now<session.end;return <div key={session.name} className={`session-block session-${session.name.toLowerCase().replace(' ','-')} ${active?'is-active':''}`} style={{left:`${(session.start-day)/864000}%`,width:`${(session.end-session.start)/864000}%`}}><span>{session.name.toUpperCase()}</span></div>;})}
      <div className="session-now" style={{left:`${(now-day)/864000}%`}}><span>NOW</span></div>
    </div><div className="session-hours">{['00','06','12','18','24'].map(hour=><span key={hour}>{hour}</span>)}</div>
  </section>;
}