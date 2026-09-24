import {useEffect,useRef,useState} from 'react';
import type {SessionStatus} from '../net/auth';
import {LiveChart} from '../chart/LiveChart';
import {Settings} from '../stream/Settings';
import {TikTokPill} from '../stream/TikTokPill';
import {SpeakerPanel} from '../stream/SpeakerPanel';
import {SessionRibbon} from '../stream/SessionRibbon';
import {defaultStream,type StreamConfig} from '../stream/types';
import type {TikTokComment,TikTokWelcome,TikTokWelcomeMemory} from '../stream/types';
import {copy} from '../copy';

export type UIMode='broadcast'|'operator';
export function ModeBadge({mode}:{mode:SessionStatus['tradeMode']}) {
  return <span className={`mode-badge mode-${mode}`} aria-label={`${mode} account`} data-testid="account-mode"><i/>{mode}</span>;
}
export function Studio({initial}:{initial:SessionStatus}) {
  const [status,setStatus]=useState(initial);
  const [theme,setTheme]=useState<'dark'|'light'>('dark');
  const [mode,setMode]=useState<UIMode>('broadcast');
  const touched=useRef(false);
  const [stream,setStream]=useState<StreamConfig>(defaultStream);
  const [settingsOpen,setSettingsOpen]=useState(false);
  const welcomeSeq=useRef(0);
  const [welcomes,setWelcomes]=useState<(TikTokWelcome&{id:number;returning:boolean;join_count:number})[]>([]);
  const [joins,setJoins]=useState<(TikTokWelcome&{id:number;returning:boolean;join_count:number})[]>([]);
  const commentSeq=useRef(0);
  const [comments,setComments]=useState<(TikTokComment&{id:number})[]>([]);
  useEffect(()=>{window.oracle?.streamConfig?.().then(setStream).catch(()=>{});return window.oracle?.onStreamConfig?.(setStream);},[]);
  useEffect(()=>{
    const show=(welcome:TikTokWelcome)=>{
      const key=welcome.name.trim().toLowerCase();
      let memory:Record<string,TikTokWelcomeMemory>={};
      try{memory=JSON.parse(localStorage.getItem('oracle.tiktok.viewer-memory')??'{}') as Record<string,TikTokWelcomeMemory>;}catch{memory={};}
      const previous=memory[key];
      const returning=welcome.returning??!!previous;
      const join_count=welcome.join_count??((previous?.join_count??0)+1);
      memory[key]={name:welcome.name,first_seen_ms:welcome.first_seen_ms??previous?.first_seen_ms??welcome.at_ms,last_seen_ms:welcome.at_ms,join_count};
      try{localStorage.setItem('oracle.tiktok.viewer-memory',JSON.stringify(memory));}catch{}
      const item={...welcome,id:++welcomeSeq.current,returning,join_count};
      setWelcomes([item]);
      setJoins(list=>[item,...list].slice(0,6));
      window.setTimeout(()=>setWelcomes(list=>list.filter(row=>row.id!==item.id)),4000);
      window.setTimeout(()=>setJoins(list=>list.filter(row=>row.id!==item.id)),45000);
    };
    const remove=window.oracle?.onTikTokWelcome?.(show);
    const local=(event:Event)=>show((event as CustomEvent<TikTokWelcome>).detail);
    window.addEventListener('oracle:tiktok-welcome',local);
    return()=>{remove?.();window.removeEventListener('oracle:tiktok-welcome',local);};
  },[]);
  useEffect(()=>{const key=(event:KeyboardEvent)=>{if(event.ctrlKey&&event.code==='Comma'){event.preventDefault();setSettingsOpen(true);}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[]);
  useEffect(()=>{
    const show=(comment:TikTokComment)=>{
      const item={...comment,id:++commentSeq.current,text:String(comment.text??'').slice(0,180)};
      setComments(list=>[item,...list].slice(0,5));
      window.setTimeout(()=>setComments(list=>list.filter(row=>row.id!==item.id)),15000);
    };
    const remove=window.oracle?.onTikTokComment?.(show);
    const local=(event:Event)=>show((event as CustomEvent<TikTokComment>).detail);
    window.addEventListener('oracle:tiktok-comment',local);
    return()=>{remove?.();window.removeEventListener('oracle:tiktok-comment',local);};
  },[]);
  useEffect(()=>window.oracle?.onSession(setStatus),[]);
  useEffect(()=>{
    window.oracle?.studioSettings?.().then(settings=>{if(!touched.current)setMode(settings.mode);}).catch(()=>{});
    const key=(event:KeyboardEvent)=>{if(event.key==='F9'){event.preventDefault();touched.current=true;setMode(value=>value==='broadcast'?'operator':'broadcast');}};
    window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
  },[]);
  const active=!status.state||status.state==='connected';
  const toggleTheme=()=>setTheme(value=>value==='dark'?'light':'dark');
  return <div className={`studio ${theme} ui-${mode}`} data-testid="studio" data-ui-mode={mode}>
    <header className="studio-chrome"><div className="wordmark"><span className="oracle-mark">O</span> ORACLE <small>STUDIO</small></div>
      {mode==='operator'&&<div className="chrome-status" data-operator-only="true">
        <ModeBadge mode={status.tradeMode}/>
        <span className={`status-chip ${status.clockProven?'verified':'unproven'}`} data-testid="clock-status">{status.clockProven?'Clock verified':'Clock unproven'}</span>
        {status.tradingCapable&&<span className="status-chip master-chip">Trading-capable session. ORACLE still never trades.</span>}
        <button className="text-button" onClick={()=>void window.oracle?.switchAccount()}>Switch account</button>
        <button className="text-button" onClick={()=>{touched.current=true;setMode('broadcast');}}>Broadcast · F9</button>
      </div>}
      <TikTokPill config={stream} mode={mode} openSettings={()=>setSettingsOpen(true)}/>
      {mode==='operator'&&<SpeakerPanel/>}
      <button className="settings-gear" aria-label="Open settings" title="Settings - Ctrl+," onClick={()=>setSettingsOpen(true)}><svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M19.43 12.98c.04-.32.07-.65.07-.98s-.02-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46a.5.5 0 0 0-.61-.22l-2.49 1a7.3 7.3 0 0 0-1.69-.98L14.5 2.42A.5.5 0 0 0 14 2h-4a.5.5 0 0 0-.5.42L9.12 5.07c-.61.23-1.18.56-1.69.98l-2.49-1a.5.5 0 0 0-.61.22l-2 3.46a.5.5 0 0 0 .12.64l2.11 1.65a7.9 7.9 0 0 0 0 1.96l-2.11 1.65a.5.5 0 0 0-.12.64l2 3.46c.13.22.39.31.61.22l2.49-1c.51.4 1.08.73 1.69.98l.38 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.38-2.65c.61-.25 1.18-.58 1.69-.98l2.49 1c.23.08.48 0 .61-.22l2-3.46a.5.5 0 0 0-.12-.64l-2.11-1.65ZM12 15.5A3.5 3.5 0 1 1 12 8a3.5 3.5 0 0 1 0 7.5Z"/></svg><span>{copy.app.settings}</span></button>
    </header>
    <SessionRibbon/>
    <LiveChart theme={theme} active={active} mode={mode} session={status} toggleTheme={toggleTheme} comments={comments} joins={joins}/>
    <div className="welcome-stack" aria-live="polite">
      {welcomes.map(welcome=><div className={`welcome-toast ${welcome.returning?'welcome-back':'welcome-new'}`} key={welcome.id}>
        <i aria-hidden="true"/>
        <span>{welcome.returning?'WELCOME BACK':'WELCOME LIVE'}</span>
        <bdi dir="auto">@{welcome.name}</bdi>
        {welcome.returning&&<small>{welcome.join_count} visits</small>}
      </div>)}
    </div>
    <footer className="studio-footer">{mode==='operator'&&<span data-operator-only="true"><i className={active?'connection-dot':'connection-dot amber'}/>{active?'Terminal connected':'Session stopped'}</span>}<span className="permanent-disclaimer" data-testid="disclaimer">Educational market analysis · Not financial advice · ORACLE never trades</span></footer>
    {settingsOpen&&<Settings config={stream} onSave={setStream} onClose={()=>setSettingsOpen(false)} theme={theme} onTheme={toggleTheme}/>}
  </div>;
}
