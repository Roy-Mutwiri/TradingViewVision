import {useEffect,useState} from 'react';
import type {ConnectionTest,StreamConfig} from './types';
export function Settings({config,onSave,onClose,theme,onTheme}:{config:StreamConfig;onSave:(value:StreamConfig)=>void;onClose:()=>void;theme:'dark'|'light';onTheme:()=>void}){
  const [draft,setDraft]=useState(()=>structuredClone(config));
  const [tab,setTab]=useState('Stream');const [test,setTest]=useState<ConnectionTest|null>(null);
  const [busy,setBusy]=useState(false);const [saving,setSaving]=useState(false);const [message,setMessage]=useState('');
  useEffect(()=>{const key=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose();};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[onClose]);
  const probe=async()=>{setBusy(true);setTest(null);try{setTest(await window.oracle!.streamTest!(draft.tiktok.username));}catch{setTest({outcome:'UNREACHABLE',message:'Could not reach TikTok',profile_name:null});}finally{setBusy(false);}};
  const save=async()=>{setSaving(true);setMessage('');try{
    const username=draft.tiktok.username.trim().replace(/^@/,'').trim();
    if(username&&username!==config.tiktok.username.trim().replace(/^@/,'')){const result=await window.oracle!.streamTest!(username);setTest(result);if(result.outcome==='NOT_FOUND'){setMessage('Username not found. Correct it before saving.');return;}if(result.outcome==='UNREACHABLE'){setMessage('Could not reach TikTok. Username was not saved.');return;}}
    const saved=await window.oracle!.streamSave!(draft);onSave(saved);setDraft(structuredClone(saved));setMessage('Saved. Applied to the studio.');
  }catch(error){setMessage((error as Error).message??'Settings could not be saved.');}finally{setSaving(false);}};
  return <div className="settings-backdrop" onClick={onClose}><section className="settings-modal" role="dialog" aria-modal="true" aria-label="Studio settings" onClick={e=>e.stopPropagation()}>
    <header><strong>SETTINGS</strong><button aria-label="Close settings" onClick={onClose}>CLOSE</button></header>
    <nav aria-label="Settings tabs">{['Stream','Chart','Data','Advanced'].map(name=><button key={name} aria-selected={name===tab} onClick={()=>setTab(name)}>{name}</button>)}</nav>
    {tab==='Stream'?<div className="stream-fields">
      <h3>TikTok</h3><label htmlFor="tiktok-username">Username</label><div className="field-row"><input id="tiktok-username" value={draft.tiktok.username?`@${draft.tiktok.username.replace(/^@/,'')}`:''} onChange={e=>{setDraft({...draft,tiktok:{...draft.tiktok,username:e.target.value.trimStart().replace(/^@/,'')}});setTest(null);}}/><button disabled={busy||saving} onClick={()=>void probe()}>{busy?'Checking…':'Test connection'}</button></div>
      {test&&<div className="connection-result" role="status"><strong>{test.message}</strong>{test.profile_name&&<span>Profile: {test.profile_name}</span>}</div>}
      <label htmlFor="tiktok-sessionid">TikTok sessionid <span className="label-note">Required for age-restricted comments</span></label><input id="tiktok-sessionid" type="password" value={draft.tiktok.sessionid??''} onChange={e=>setDraft({...draft,tiktok:{...draft.tiktok,sessionid:e.target.value.trim()}})} placeholder="Paste sessionid cookie if comments are blocked"/>
      <label htmlFor="tiktok-idc">tt-target-idc <span className="label-note">Optional</span></label><input id="tiktok-idc" value={draft.tiktok.tt_target_idc??''} onChange={e=>setDraft({...draft,tiktok:{...draft.tiktok,tt_target_idc:e.target.value.trim()}})} placeholder="Optional, e.g. eu-ttp2"/>
      <div className="stream-checks"><label><input type="checkbox" checked={draft.tiktok.show_viewer_count} onChange={e=>setDraft({...draft,tiktok:{...draft.tiktok,show_viewer_count:e.target.checked}})}/> Show viewer count</label><label><input type="checkbox" checked={draft.tiktok.auto_connect_comments} onChange={e=>setDraft({...draft,tiktok:{...draft.tiktok,auto_connect_comments:e.target.checked}})}/> Connect live comments automatically</label></div>
      <h3>Watermark</h3><label><input type="checkbox" checked={draft.watermark.enabled} onChange={e=>setDraft({...draft,watermark:{...draft.watermark,enabled:e.target.checked}})}/> Enabled</label>
      <label htmlFor="watermark-text">Text</label><input id="watermark-text" value={draft.watermark.text} onChange={e=>setDraft({...draft,watermark:{...draft.watermark,text:e.target.value}})}/>
      <label htmlFor="watermark-opacity">Opacity <span>{Math.round(draft.watermark.opacity*100)}%</span></label><input id="watermark-opacity" type="range" min="0" max="0.3" step="0.01" value={draft.watermark.opacity} onChange={e=>setDraft({...draft,watermark:{...draft.watermark,opacity:Number(e.target.value)}})}/>
      <label htmlFor="watermark-position">Position</label><select id="watermark-position" value={draft.watermark.position} onChange={e=>setDraft({...draft,watermark:{...draft.watermark,position:e.target.value as StreamConfig['watermark']['position']}})}><option value="center">Center</option><option value="bottom_right">Bottom right</option><option value="tiled">Tiled</option></select>
      <label htmlFor="corner-handle">Corner handle</label><input id="corner-handle" value={draft.brand.handle} onChange={e=>setDraft({...draft,brand:{handle:e.target.value}})}/>
    </div>:tab==='Chart'?<div className="stream-fields"><h3>Theme</h3><p className="settings-scaffold compact">Broadcast default is dark. Light remains available for operator review.</p><button onClick={onTheme}>Switch to {theme==='dark'?'light':'dark'} mode</button></div>:<p className="settings-scaffold">{tab} settings are coming in a later UI pass.</p>}
    <footer><span role="status">{message}</span><button className="settings-save" disabled={saving||busy} onClick={()=>void save()}>{saving?'Saving…':'Save'}</button></footer>
  </section></div>;
}
