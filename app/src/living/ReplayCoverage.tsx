import {useState} from 'react';
import {coverageAt,readReplayCoverage,type ReplayCoverageData} from './coverageAudit';
export function ReplayCoverage(){
 const [data,setData]=useState<ReplayCoverageData|null>(null),[at,setAt]=useState(0),[error,setError]=useState('');
 async function load(files:FileList|null){
  if(!files)return;
  try{const contents=Object.fromEntries(await Promise.all(Array.from(files).map(async f=>[f.name,await f.text()])));const result=readReplayCoverage(contents);setData(result);setAt(result.from);setError('');}
  catch(e){setData(null);setError(e instanceof Error?e.message:String(e));}
 }
 return <section aria-label="Replay audit coverage"><h3>Replay audit coverage</h3><label>Open metadata.json, evalpoints.jsonl and coarse-spans.jsonl<input type="file" multiple accept=".json,.jsonl" onChange={e=>void load(e.target.files)}/></label>{error&&<p role="alert">{error}</p>}{data&&<>
  <p>{data.server} · {data.spans.length} coarse spans</p>
  <div aria-label="Replay coverage markers" style={{height:12,background:'#343b45',position:'relative'}}>{data.spans.map((s,i)=><span key={i} data-coarse-span="SYNTHETIC_COARSE" title={`${new Date(s.start_ms).toISOString()} — ${new Date(s.end_ms).toISOString()} SYNTHETIC_COARSE`} style={{position:'absolute',top:0,bottom:0,left:`${100*Math.max(0,s.start_ms-data.from)/Math.max(1,data.to-data.from)}%`,width:`${100*(Math.min(data.to,s.end_ms)-Math.max(data.from,s.start_ms))/Math.max(1,data.to-data.from)}%`,minWidth:3,background:'#d9af68'}}/>)}</div>
  <input aria-label="Replay audit position" type="range" min={data.from} max={data.to} step={1} value={at} onChange={e=>setAt(Number(e.target.value))} style={{width:'100%'}}/>
  <p>{new Date(at).toISOString()} · <strong style={{color:coverageAt(data,at)==='SYNTHETIC_COARSE'?'#d9af68':undefined}}>{coverageAt(data,at)}</strong></p><small>Audit cursor only; the live chart continues independently.</small>
 </>}</section>;
}
