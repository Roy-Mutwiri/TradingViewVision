from __future__ import annotations
import argparse,bisect,json,shutil,sys
from collections import Counter,defaultdict
from datetime import UTC,datetime
from pathlib import Path
import duckdb
ROOT=Path(__file__).resolve().parents[2]
ENGINE=ROOT/'engine'
if str(ENGINE) not in sys.path: sys.path.insert(0,str(ENGINE))
from oracle.config import load_config
from oracle.models import Bar,timeframe_ms
from oracle.candidates.lifecycle import CandidateEngine
from oracle.candidates.sources import replay_points
from oracle.smc.swings import load_swing_config
from oracle.analysis.producer import CallProducer
from oracle.analysis.ledger import CallLedger
from oracle.analysis.resolver import CallResolver
from oracle.data.assumed_calendar import assumed_closed

def copy_store(explicit=None):
    if explicit: src=Path(explicit)
    else:
        stores=sorted((ROOT/'runtime').rglob('candles.duckdb'),key=lambda p:p.stat().st_size,reverse=True)
        src=stores[0]
    dst=ROOT/'runtime/ui-proof/always-on-signals/parity-candles.duckdb'; dst.parent.mkdir(parents=True,exist_ok=True)
    for cand in ([src]+[p for p in sorted((ROOT/'runtime').rglob('candles.duckdb'),key=lambda p:p.stat().st_size,reverse=True) if p!=src]):
        try:
            shutil.copy2(cand,dst); return cand,dst
        except PermissionError: continue
    raise RuntimeError('no readable candle store')

def aggregate(minutes,broker,tf,start,end):
    step=timeframe_ms(tf); groups=defaultdict(list)
    for b in minutes:
        if start<=b.t_open_ms<end:
            groups[broker[b.t_open_ms]//step*step].append(b)
    parents=[]
    for _,g in sorted(groups.items()):
        if len(g)==step//60000 and g[-1].t_open_ms-g[0].t_open_ms==step-60000:
            parents.append(Bar(tf=tf,t_open_ms=g[0].t_open_ms,o=g[0].o,h=max(x.h for x in g),l=min(x.l for x in g),c=g[-1].c,tick_volume=sum(x.tick_volume for x in g),source='mt5',complete=True,digits=g[0].digits))
    return parents

def run_tf(tf,minutes,broker,minute_times,cfg,weights,start,end):
    step=timeframe_ms(tf); seed_start=start-14*86400000
    all_parents=aggregate(minutes,broker,tf,seed_start,end)
    seed=[b for b in all_parents if b.t_open_ms<start][-200:]
    parents=[b for b in all_parents if start<=b.t_open_ms<end]
    result={'evaluated':0,'produced':0,'rejections':{},'produced_by_grade':{},'ledger_rows':0,'parent_bars':len(parents)}
    if not parents or not seed: return result
    seed_end=parents[0].t_open_ms
    seed_minutes=[m for m in minutes if seed[0].t_open_ms<=m.t_open_ms+60000<=seed_end]
    eng=CandidateEngine(tf,seed,cfg.zones,order_blocks_enabled=True,structure_config=cfg.structure,swing_config=weights,liquidity_enabled=True,liquidity_config=cfg.liquidity,sessions_config=cfg.sessions,seed_minutes=seed_minutes)
    points,_=replay_points(parents,minutes)
    ledger=CallLedger(None,cfg.retention.min_call_life_ms); producer=CallProducer(cfg.trade,cfg.calls); resolver=CallResolver(ledger,.001)
    mi=bisect.bisect_left(minute_times,seed_start)
    for p in points:
        b=parents[p.bar_index]
        while mi<len(minutes) and minutes[mi].t_open_ms+60000<=p.t_broker_ms: mi+=1
        newmins=[]
        if eng.liquidity:
            lo=eng.liquidity.calendar.last_ms+1
            newmins=minutes[bisect.bisect_left(minute_times,lo):mi]
        eng.process(p,parent_open_ms=b.t_open_ms,closed_bar=b if p.bar_phase=='CLOSE' else None,closed_minutes=newmins)
        if p.bar_phase!='CLOSE': continue
        result['evaluated']+=1
        for row in ledger.rows:
            c=row.call
            if c.state in ('PENDING','ACTIVE'):
                resolver.evaluate(c.id,minutes[bisect.bisect_left(minute_times,c.eval_from_ms):min(bisect.bisect_left(minute_times,c.eval_to_ms),mi)],p.t_broker_ms,clock_version=1,is_tradeable=lambda t:not assumed_closed(t),coverage_through_ms=p.t_broker_ms,can_activate=lambda call:producer.can_activate(call,[r.call for r in ledger.rows]))
            else: producer.mark_resolution(c)
        ob,liq=eng.ob,eng.liquidity
        if not ob or not liq or not ob.structure or eng.atr.value is None:
            producer.reject('NO_STRUCTURE_EVENT',tf); continue
        active=[r.call for r in ledger.rows if r.call.state in ('PENDING','ACTIVE')]
        considered=False
        for record in sorted(ob.records,key=lambda r:(r.geometry.created_ms,r.id)):
            if record.state not in ('FRESH','TOUCHED','MITIGATED'): continue
            considered=True
            event=next((e for e in ob.structure.events if e.id==record.validated_by_event_id),None)
            if not event: continue
            state=ob.structure.state.model_copy(update={'last_event':event})
            direction='LONG' if record.geometry.direction=='BULLISH' else 'SHORT'
            active,_=producer.htf_arbitration(active,direction,record.geometry.tf)
            call=producer.construct(ob=record,fvgs=list(eng.cursor.records),structure=state,liquidity=liq,bar=b,atr=eng.atr.value,clock_version=1,active=active)
            if call:
                ledger.create(call); active.append(call); result['produced']+=1; result['produced_by_grade'][call.grade]=result['produced_by_grade'].get(call.grade,0)+1
        if not considered: producer.reject('NO_STRUCTURE_EVENT',tf)
    result['rejections']={k[1]:v for k,v in producer.rejections_by_tf.items() if k[0]==tf}
    result['ledger_rows']=len(ledger.rows)
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--start-ms',type=int,required=True); ap.add_argument('--end-ms',type=int,default=None); ap.add_argument('--store'); args=ap.parse_args()
    cfg=load_config(ROOT/'config/oracle.yaml'); weights=load_swing_config(ROOT/'config/weights.yaml')
    src,dst=copy_store(args.store)
    with duckdb.connect(str(dst),read_only=True) as db:
        raw=db.execute("select payload,t_broker_ms from bars where broker=? and tf='M1' order by t",[cfg.data.canonical_broker]).fetchall()
    minutes=[Bar.model_validate_json(r[0]) for r in raw if json.loads(r[0])['complete']]
    broker={json.loads(r[0])['t_open_ms']:r[1] for r in raw}; minute_times=[m.t_open_ms for m in minutes]
    end=args.end_ms or (minutes[-1].t_open_ms+60000 if minutes else args.start_ms)
    out={'source_store':str(src),'proof_store':str(dst),'start_ms':args.start_ms,'end_ms':end,'start_utc':datetime.fromtimestamp(args.start_ms/1000,UTC).isoformat(),'end_utc':datetime.fromtimestamp(end/1000,UTC).isoformat(),'tf':{}}
    for tf in cfg.candidates.timeframes:
        out['tf'][tf]=run_tf(tf,minutes,broker,minute_times,cfg,weights,args.start_ms,end)
    path=ROOT/'runtime/ui-proof/always-on-signals/step0-backtest-parity.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(out,indent=2,sort_keys=True),encoding='utf-8')
    print(json.dumps(out,indent=2,sort_keys=True))
if __name__=='__main__': main()
