import type {Bar,DrawObject} from '../net/protocol';
import type {TikTokWelcome} from '../stream/types';
import {fmt} from '../fmt';
import {copy} from '../copy';
export function Watching({bar,price,session,objects,now,joins=[]}:{bar:Bar|null;price:number|null;session:string;objects:DrawObject[];now:number;joins?:(TikTokWelcome&{id:number;returning:boolean;join_count:number})[]}){
  const pending=objects.find(o=>o.style.token==='liquidity.pool'&&o.text_args.lifecycle==='CANDIDATE');
  const difference=bar&&price!=null?price-bar.o:null;
  const first=difference==null?'Awaiting price':`${fmt.usd(difference)} vs ${bar!.tf} open`;
  const edges=objects.filter(o=>o.shape==='ZONE'&&o.state!=='INVALID'&&o.text_args.provisional!==true).flatMap(o=>o.points.map(p=>p.price));
  const nearestEdge=price!=null&&edges.length?edges.slice().sort((a,b)=>Math.abs(a-price)-Math.abs(b-price))[0]:null;
  const nearest=price!=null&&nearestEdge!=null?Math.abs(nearestEdge-price):null;
  const side=price!=null&&nearestEdge!=null?(nearestEdge>price?'above':'below'):'away';
  const third=pending?`CLOSE ${pending.text_args.side==='HIGH'?'BELOW':'ABOVE'} ${fmt.price(pending.points[0].price)} IN ${pending.text_args.bars_left} BARS  sweep confirmed  beyond break`:nearest==null?'Structure pending':`Nearest zone ${fmt.price(nearestEdge!)}  ${fmt.price(nearest!)} ${side}`;
  const sessionLabel=String(session).split('/')[0].replace(/\s+session$/i,'').trim()||'Current';
  const join=joins[0];
  return <div className="watching-strip" aria-label="Watching strip"><div className="watching-facts"><strong>WATCHING</strong><span>{first}</span><i aria-hidden="true"/><span>{sessionLabel} session</span><i aria-hidden="true"/><span>{third}</span><time>{new Date(now).toISOString().slice(11,19)} UTC</time></div><div className="join-ticker" aria-live="polite">{join?<><bdi dir="auto">@{join.name}</bdi><span>{join.returning?`${copy.joins.welcomeBack} / ${join.join_count}`:copy.joins.joined}</span></>:<span>{copy.joins.none}</span>}</div></div>;
}
