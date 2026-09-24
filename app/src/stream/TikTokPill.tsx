import {useEffect,useState} from 'react';
import type {StreamConfig,TikTokStatus} from './types';
import {fmt} from '../fmt';

export function TikTokPill({config,mode,openSettings}:{config:StreamConfig;mode:'broadcast'|'operator';openSettings:()=>void}){
  const [status,setStatus]=useState<TikTokStatus>({state:'CONNECTING',username:config.tiktok.username,viewers:null,live_since_ms:null,last_checked_ms:Date.now(),error:null});
  const [now,setNow]=useState(Date.now());
  useEffect(()=>{const local=(event:Event)=>setStatus((event as CustomEvent<TikTokStatus>).detail);window.addEventListener('oracle:tiktok-status',local);const remove=window.oracle?.onTikTokStatus?.(setStatus);window.oracle?.tikTokStatus?.().then(setStatus).catch(()=>{});return()=>{remove?.();window.removeEventListener('oracle:tiktok-status',local);};},[]);
  useEffect(()=>{
    const username=config.tiktok.username.trim().replace(/^@/,'');
    setStatus(current=>current.username===username?current:{state:username?'CONNECTING':'NOT_CONFIGURED',username:username||null,viewers:null,live_since_ms:null,last_checked_ms:Date.now(),error:null});
  },[config.tiktok.username]);
  useEffect(()=>{if(status.state!=='LIVE')return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[status.state]);
  const elapsed=Math.max(0,Math.floor((now-(status.live_since_ms??now))/1000));
  const clock=[Math.floor(elapsed/3600),Math.floor(elapsed/60)%60,elapsed%60].map(n=>String(n).padStart(2,'0')).join(':');
  const label=status.state==='NOT_CONFIGURED'?'SET USERNAME':status.state==='UNKNOWN'?(mode==='operator'?'TIKTOK UNREACHABLE':''):status.state;
  return <button className={`tiktok-pill tiktok-${status.state.toLowerCase()}`} data-testid="tiktok-status" data-state={status.state} onClick={status.state==='NOT_CONFIGURED'?openSettings:undefined} aria-label={status.state==='NOT_CONFIGURED'?'Set TikTok username':`TikTok ${status.state}`}>
    <i/>{label&&<strong>{label}</strong>}{status.username&&<span>@{status.username}</span>}{status.state==='LIVE'&&<>{config.tiktok.show_viewer_count&&<span className="viewer-count">{status.viewers==null?'--':fmt.int(status.viewers)} viewers</span>}<time>{clock}</time></>}
  </button>;
}
