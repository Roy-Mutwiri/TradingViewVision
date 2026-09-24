import type {DrawObject} from './net/protocol';
import type {Pool, StructureState} from './net/chart';
import {fmt} from './fmt';

export type SignalProcedure={
  direction:'LONG'|'SHORT';
  gate:'DISCOUNT'|'PREMIUM';
  gateSide:'below'|'above';
  gatePrice:string;
  headline:string;
  steps:string[];
  waitingLine:string;
};

type ZoneInfo={label:string;lo:number;hi:number;mid:number;distance:number};
type PoolInfo={label:string;price:number;distance:number;side:'HIGH'|'LOW'};

const numberValue=(value:unknown):number|null=>typeof value==='number'&&Number.isFinite(value)?value:null;
const cleanLabel=(value:unknown,fallback:string)=>String(value??fallback).replaceAll('_',' ').replace(/\s+/g,' ').trim().toUpperCase();

function zoneInfo(object:DrawObject,price:number):ZoneInfo|null{
  if(object.shape!=='ZONE'||object.state==='INVALID'||object.text_args.confirmed===false)return null;
  const prices=object.points.map(point=>point.price).filter(Number.isFinite);
  if(!prices.length)return null;
  const lo=Math.min(...prices),hi=Math.max(...prices),mid=(lo+hi)/2;
  const tf=cleanLabel(object.text_args.tf,'');
  const kind=cleanLabel(object.text_args.kind??object.text_args.type??object.text_key??object.style.token,'ZONE').replace(/^ANALYSIS\s+/,'');
  const label=[tf,kind].filter(Boolean).join(' ');
  return {label,lo,hi,mid,distance:Math.abs(mid-price)};
}

function poolInfo(pool:Pool,price:number):PoolInfo|null{
  const level=numberValue(pool.geometry?.level);
  if(level==null||pool.state==='BROKEN'||pool.state==='SWEPT')return null;
  const name=cleanLabel(pool.geometry?.name,'LIQ');
  const side=pool.geometry?.side==='LOW'?'LOW':'HIGH';
  const strength=pool.strength&&pool.strength>1?` ${pool.strength}`:'';
  return {label:`${name}${strength}`,price:level,distance:Math.abs(level-price),side};
}

export function buildSignalProcedure(input:{price:number|null;tf:string;structure:StructureState|null|undefined;objects:DrawObject[];pools:Pool[]}):SignalProcedure{
  const {price,tf,structure,objects,pools}=input;
  const trend=structure?.trend??'UNDEFINED';
  const direction:SignalProcedure['direction']=trend==='BEARISH'?'SHORT':'LONG';
  const gate:SignalProcedure['gate']=direction==='SHORT'?'PREMIUM':'DISCOUNT';
  const gateSide:SignalProcedure['gateSide']=direction==='SHORT'?'above':'below';
  const rangeLo=trend==='BULLISH'?numberValue(structure?.protected_low):numberValue(structure?.major_low);
  const rangeHi=trend==='BULLISH'?numberValue(structure?.major_high):numberValue(structure?.protected_high);
  const eq=rangeLo!=null&&rangeHi!=null&&rangeHi>rangeLo?(rangeLo+rangeHi)/2:null;
  const current=price??eq??rangeHi??rangeLo??0;
  const zones=objects.map(object=>zoneInfo(object,current)).filter((zone):zone is ZoneInfo=>!!zone);
  const entryZones=zones.filter(zone=>direction==='SHORT'?zone.mid>=current:zone.mid<=current).sort((a,b)=>a.distance-b.distance);
  const nearestZone=(entryZones[0]??zones.sort((a,b)=>a.distance-b.distance)[0])??null;
  const livePools=pools.map(pool=>poolInfo(pool,current)).filter((pool):pool is PoolInfo=>!!pool);
  const targetPools=livePools.filter(pool=>direction==='SHORT'?pool.side==='LOW'&&pool.price<current:pool.side==='HIGH'&&pool.price>current).sort((a,b)=>a.distance-b.distance);
  const gatePools=livePools.filter(pool=>direction==='SHORT'?pool.price>current:pool.price<current).sort((a,b)=>a.distance-b.distance);
  const watchPool=gatePools[0]??targetPools[0]??livePools.sort((a,b)=>a.distance-b.distance)[0]??null;
  const protectedPrice=direction==='SHORT'?numberValue(structure?.protected_high):numberValue(structure?.protected_low);
  const protectedText=protectedPrice!=null?`protected ${fmt.price(protectedPrice)}`:'protected level pending';
  const gatePrice=eq!=null?fmt.price(eq):protectedPrice!=null?fmt.price(protectedPrice):current?fmt.price(current):'--';
  const zoneText=nearestZone?`${nearestZone.label} ${fmt.range(nearestZone.lo,nearestZone.hi)}`:'entry zone pending';
  const poolText=watchPool?`${watchPool.label} ${fmt.price(watchPool.price)}`:'liquidity pool pending';
  const targetText=targetPools[0]?`${targetPools[0].label} ${fmt.price(targetPools[0].price)}`:'target pool pending';
  const headline=trend==='UNDEFINED'
    ? `${tf} structure forming / waiting for confirmed break`
    : `${tf} ${trend} / ${gate} entry ${gateSide} ${gatePrice}`;
  const steps=[
    `${trend==='UNDEFINED'?'Structure is still forming':`${trend} bias active`}`,
    `Entry area: ${zoneText}`,
    `Waiting for ${gate.toLowerCase()} ${gateSide} ${gatePrice}`,
    `Watching ${poolText}; ${protectedText}`,
    `Target check: ${targetText} + R gate`,
  ];
  const waitingLine=`Waiting for ${gate.toLowerCase()} ${gateSide} ${gatePrice} / entry area ${zoneText}`;
  return {direction,gate,gateSide,gatePrice,headline,steps,waitingLine};
}
