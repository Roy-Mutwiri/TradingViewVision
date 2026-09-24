import {useEffect,useState} from 'react';
import type {DrawObject} from '../net/protocol';
import {fmt} from '../fmt';
import {copy} from '../copy';
interface StructureRow {id:string;kind:string;price:number;at:number;direction:string}
export function structureRows(objects:DrawObject[]):StructureRow[]{
  return objects.flatMap(object=>{
    if(object.text_args.confirmed===false||object.text_args.provisional===true)return [];
    const value=String(object.text_args.kind??object.text_args.event??object.style.token??'').toUpperCase();
    const match=value.match(/(?:^|[._\s])(CHOCH|SWEEP|BOS|MSS)(?:$|[._\s])/);
    const point=object.points.at(-1);if(!match||!point)return [];
    return [{id:object.id??`${match[1]}:${point.t_ms}:${point.price}`,kind:match[1]==='CHOCH'?'CHoCH':match[1],price:point.price,at:Number(object.text_args.confirmed_at_ms??point.t_ms),direction:String(object.text_args.direction??'').toUpperCase()}];
  }).sort((a,b)=>b.at-a.at||a.id.localeCompare(b.id)).slice(0,3);
}
export function StructureTicker({objects}:{objects:DrawObject[]}){
  const [history,setHistory]=useState<StructureRow[]>([]);
  useEffect(()=>{const incoming=structureRows(objects);if(!incoming.length)return;setHistory(incoming);},[objects]);
  if(!history.length)return <p className="structure-pending">Structure pending</p>;
  return <section className="structure-ticker" aria-label="Structure ticker"><div className="rail-heading"><span>{copy.rail.structure}</span><small>{copy.rail.utc}</small></div>{history.map(row=><div key={row.id}><time>{fmt.time(row.at)}</time><strong>{row.kind} {row.direction==='DOWN'?'▼':'▲'}</strong><span>{fmt.price(row.price)}</span></div>)}</section>;
}
