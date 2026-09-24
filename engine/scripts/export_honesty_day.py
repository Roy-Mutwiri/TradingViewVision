"""Export one stored M15 trading day for the thesis/slide honesty harness."""
from __future__ import annotations

import argparse, bisect, json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from oracle.config import load_config
from oracle.models import Bar, DataQuality, timeframe_ms
from oracle.candidates.lifecycle import CandidateEngine
from oracle.candidates.sources import replay_points
from oracle.smc.swings import load_swing_config
from oracle.smc.ob_drawing import ob_objects
from oracle.smc.liquidity_drawing import liquidity_objects
from oracle.smc.structure_drawing import structure_objects
from oracle.analysis.call_drawing import call_objects
from oracle.analysis.ledger import CallLedger
from oracle.analysis.resolver import CallResolver
from oracle.analysis.producer import CallProducer
from oracle.data.assumed_calendar import assumed_closed
from oracle.thesis import build_thesis
from oracle.transport.chart import BarsSnapshot, ChartFrame


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=Path('runtime/ui-proof/honesty-day/records.jsonl'))
    parser.add_argument('--tf', default='M15')
    parser.add_argument('--day-ms', type=int, default=None)
    parser.add_argument('--max-records', type=int, default=0)
    args=parser.parse_args()
    root=Path.cwd()
    cfg=load_config(root/'config/oracle.yaml')
    weights=load_swing_config(root/'config/weights.yaml')
    out=args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect('runtime/ui-proof/liquidity-history/candles.duckdb', read_only=True) as db:
        raw=db.execute("select payload,t_broker_ms from bars where broker='exness' and tf='M1' and source='mt5' order by t").fetchall()
    minutes=[Bar.model_validate_json(r[0]) for r in raw if json.loads(r[0])['complete']]
    broker={json.loads(r[0])['t_open_ms']:r[1] for r in raw}
    minute_times=[m.t_open_ms for m in minutes]
    tf=args.tf
    step=timeframe_ms(tf)
    # Use a full day safely inside in-sample so there is enough seed and mature state.
    day_start=args.day_ms if args.day_ms is not None else cfg.backtest.in_sample_start_ms + 14*86400000
    day_end=day_start + 86400000
    groups=defaultdict(list)
    for b in minutes:
        if day_start-14*86400000 <= b.t_open_ms < day_end:
            groups[broker[b.t_open_ms]//step*step].append(b)
    parents=[]
    for _,g in sorted(groups.items()):
        if len(g)==step//60000 and g[-1].t_open_ms-g[0].t_open_ms==step-60000:
            parents.append(Bar(tf=tf,t_open_ms=g[0].t_open_ms,o=g[0].o,h=max(x.h for x in g),l=min(x.l for x in g),c=g[-1].c,tick_volume=sum(x.tick_volume for x in g),source='mt5',complete=True,digits=g[0].digits))
    seed=[b for b in parents if b.t_open_ms<day_start][-200:]
    parents=[b for b in parents if day_start<=b.t_open_ms<day_end]
    if not parents:
        raise SystemExit('no complete parent bars for honesty day')
    seed_end=parents[0].t_open_ms
    eng=CandidateEngine(tf,seed,cfg.zones,order_blocks_enabled=True,structure_config=cfg.structure,swing_config=weights,liquidity_enabled=True,liquidity_config=cfg.liquidity,sessions_config=cfg.sessions,seed_minutes=[m for m in minutes if seed and seed[0].t_open_ms<=m.t_open_ms+60000<=seed_end])
    points,_=replay_points(parents,minutes)
    ledger=CallLedger(None,cfg.retention.min_call_life_ms)
    producer=CallProducer(cfg.trade,cfg.calls)
    resolver=CallResolver(ledger,.001)
    mi=bisect.bisect_left(minute_times,day_start-14*86400000)
    records=0
    with out.open('w', encoding='utf-8') as f:
        for p in points:
            b=parents[p.bar_index]
            while mi<len(minutes) and minutes[mi].t_open_ms+60000<=p.t_broker_ms:
                mi+=1
            newmins=[]
            if eng.liquidity:
                lo=eng.liquidity.calendar.last_ms+1
                newmins=minutes[bisect.bisect_left(minute_times,lo):mi]
            eng.process(p,parent_open_ms=b.t_open_ms,closed_bar=b if p.bar_phase=='CLOSE' else None,closed_minutes=newmins)
            if p.bar_phase=='CLOSE':
                # Keep producer/resolver side effects aligned enough for CALL consistency.
                for row in ledger.rows:
                    c=row.call
                    if c.state in ('PENDING','ACTIVE'):
                        resolver.evaluate(c.id,minutes[bisect.bisect_left(minute_times,c.eval_from_ms):min(bisect.bisect_left(minute_times,c.eval_to_ms),mi)],p.t_broker_ms,clock_version=1,is_tradeable=lambda t:not assumed_closed(t),coverage_through_ms=p.t_broker_ms,can_activate=lambda call:producer.can_activate(call,[r.call for r in ledger.rows]))
                    else:
                        producer.mark_resolution(c)
                ob,liq=eng.ob,eng.liquidity
                if ob and liq and ob.structure and eng.atr.value:
                    active=[r.call for r in ledger.rows if r.call.state in ('PENDING','ACTIVE')]
                    for record in sorted(ob.records,key=lambda r:(r.geometry.created_ms,r.id)):
                        if record.state not in ('FRESH','TOUCHED','MITIGATED'):
                            continue
                        event=next((e for e in ob.structure.events if e.id==record.validated_by_event_id),None)
                        if not event:
                            continue
                        state=ob.structure.state.model_copy(update={'last_event':event})
                        direction='LONG' if record.geometry.direction=='BULLISH' else 'SHORT'
                        active,cancelled=producer.htf_arbitration(active,direction,record.geometry.tf)
                        for call_id in cancelled:
                            ledger.cancel(call_id,'SUPERSEDED_BY_NEW_ANALYSIS',at_ms=p.t_broker_ms)
                        call=producer.construct(ob=record,fvgs=list(eng.cursor.records),structure=state,liquidity=liq,bar=b,atr=eng.atr.value,clock_version=1,active=active)
                        if call:
                            ledger.create(call);active.append(call)
            objects=[]
            if eng.ob:
                objects.extend(ob_objects(eng.ob,p.t_broker_ms))
                if eng.ob.structure:
                    objects.extend(structure_objects(eng.ob.structure,p.t_broker_ms))
            if eng.liquidity:
                objects.extend(liquidity_objects(eng.liquidity,p.t_broker_ms,p.price,len(eng.closed)))
            open_rows=[r for r in ledger.rows if r.call.state in ('PENDING','ACTIVE')]
            objects.extend(call_objects(open_rows,p.t_broker_ms,p.price))
            dry_runs=[]
            if eng.ob and eng.liquidity and eng.ob.structure and eng.atr.value:
                active_calls=[r.call for r in ledger.rows if r.call.state in ('PENDING','ACTIVE')]
                for record in sorted(eng.ob.records,key=lambda r:(r.geometry.created_ms,r.id)):
                    if record.state not in ('FRESH','TOUCHED','MITIGATED'):
                        continue
                    event=next((e for e in eng.ob.structure.events if e.id==record.validated_by_event_id),None)
                    if not event:
                        continue
                    evidence_state=eng.ob.structure.state.model_copy(update={'last_event':event})
                    dry_runs.append(producer.dry_run(ob=record,fvgs=list(eng.cursor.records),structure=evidence_state,liquidity=eng.liquidity,bar=b,atr=eng.atr.value,active=active_calls))
            dry_run=sorted(dry_runs,key=lambda item:(not item.passes,item.distance_to_zone,item.first_fail or ''))[0] if dry_runs else None
            thesis=build_thesis(tf=tf,price=p.price,structure=eng.ob.structure.state if eng.ob and eng.ob.structure else None,objects=objects,pools=list(eng.liquidity.pools.values()) if eng.liquidity else [],open_calls=[r.call for r in open_rows],market_closed=False,dry_run=dry_run)
            frame={'now_ms':p.t_broker_ms,'objects':[o.model_dump(mode='json') for o in objects],'structure_state':(eng.ob.structure.state.model_dump(mode='json') if eng.ob and eng.ob.structure else None),'liquidity_pools':[pool.model_dump(mode='json') for pool in (list(eng.liquidity.pools.values()) if eng.liquidity else [])]}
            f.write(json.dumps({'eval':p.model_dump(mode='json'),'tf':tf,'price':p.price,'frame':frame,'thesis':thesis.model_dump(mode='json'),'open_call_ids':[r.call.id for r in open_rows],'broker_time':datetime.fromtimestamp(p.t_broker_ms/1000,UTC).isoformat()},separators=(',',':'))+'\n')
            records+=1
            if args.max_records and records>=args.max_records:
                break
    summary={'records':records,'tf':tf,'day_start_ms':day_start,'day_end_ms':day_end,'day_start_utc':datetime.fromtimestamp(day_start/1000,UTC).isoformat(),'day_end_utc':datetime.fromtimestamp(day_end/1000,UTC).isoformat(),'out':str(out)}
    (out.parent/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()


