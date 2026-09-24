import type {DrawObject} from '../net/protocol';
import type {Pool} from '../net/chart';
import {fmt} from '../fmt';
import {copy} from '../copy';

type LevelRow={name:string;price:number;current?:boolean};
export function KeyLevels({price,objects,pools,weeklyOpen}:{price:number|null;objects:DrawObject[];pools:Pool[];weeklyOpen:number|null}){
  const edges=objects.filter(o=>o.shape==='ZONE'&&o.state!=='INVALID'&&o.text_args.confirmed!==false).flatMap(o=>o.points.map(p=>p.price));
  const nearest=price!=null&&edges.length?edges.sort((a,b)=>Math.abs(a-price)-Math.abs(b-price))[0]:null;
  const raw:LevelRow[]=[
    {name:'PDH',price:pools.find(p=>p.geometry.name==='PDH')?.geometry.level??NaN},
    {name:'WEEKLY OPEN',price:weeklyOpen??NaN},
    {name:'NEAREST ZONE',price:nearest??NaN},
    {name:'PDL',price:pools.find(p=>p.geometry.name==='PDL')?.geometry.level??NaN},
  ].filter(row=>Number.isFinite(row.price));
  const rows:LevelRow[]=[...raw.filter(row=>row.name&&Number.isFinite(row.price)),...(price==null?[]:[{name:'PRICE',price,current:true}])].sort((a,b)=>b.price-a.price);
  return <section className="key-levels rail-grow" aria-label="Key levels"><div className="rail-heading"><span>{copy.rail.keyLevels}</span><small>{copy.rail.deltaUsd}</small></div>
    {rows.map(level=><div className={`key-level-row ${level.current?'current-price':''}`} key={level.name}><strong>{level.name}</strong><b>{fmt.price(level.price)}</b><span>{price==null?'--':level.current?'0.00':fmt.usd(level.price-price)}</span></div>)}
    {!rows.length&&<p className="bias-pending">--</p>}
  </section>;
}