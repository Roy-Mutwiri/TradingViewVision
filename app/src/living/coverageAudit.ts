export interface CoveragePoint {t_broker_ms:number;fidelity:'TICK'|'M1'|'BAR'}
export interface CoverageSpan {start_ms:number;end_ms:number;state:'SYNTHETIC_COARSE'}
export interface ReplayCoverageData {from:number;to:number;points:CoveragePoint[];spans:CoverageSpan[];server:string}
/** Read an existing audit only. Moving its cursor never changes the live chart or engine. */
export function readReplayCoverage(files:Record<string,string>):ReplayCoverageData{
 const meta=JSON.parse(files['metadata.json']??'null');
 if(!meta||meta.schema_version!==2)throw Error('regenerate: candidate audit schema mismatch');
 if(!Number.isFinite(meta.offset_s)||typeof meta.server!=='string')throw Error('Invalid replay metadata');
 const rows=(name:string)=>{if(!(name in files))throw Error(`Missing ${name}`);return files[name].split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line));};
 const points:CoveragePoint[]=rows('evalpoints.jsonl').map(p=>{
  if(!Number.isFinite(p.t_broker_ms)||!['TICK','M1','BAR'].includes(p.fidelity))throw Error('Invalid EvalPoint');
  return {t_broker_ms:p.t_broker_ms-meta.offset_s*1000,fidelity:p.fidelity};
 });
 if(!points.length)throw Error('Empty replay');
 for(let i=1;i<points.length;i++)if(points[i].t_broker_ms<points[i-1].t_broker_ms)throw Error('Unordered EvalPoints');
 const spans:CoverageSpan[]=rows('coarse-spans.jsonl').map(s=>{
  if(s.state!=='SYNTHETIC_COARSE'||!Number.isFinite(s.start_ms)||!Number.isFinite(s.end_ms)||s.end_ms<=s.start_ms)throw Error('Invalid coarse span');
  return {start_ms:s.start_ms,end_ms:s.end_ms,state:s.state};
 }).sort((a,b)=>a.start_ms-b.start_ms);
 return {from:points[0].t_broker_ms,to:points.at(-1)!.t_broker_ms,points,spans,server:meta.server};
}
export function coverageAt(data:ReplayCoverageData,at:number){
 if(data.spans.some(s=>s.start_ms<=at&&at<s.end_ms))return 'SYNTHETIC_COARSE';
 let lo=0,hi=data.points.length-1;
 while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(data.points[mid].t_broker_ms<=at)lo=mid;else hi=mid-1;}
 return data.points[lo].fidelity;
}
