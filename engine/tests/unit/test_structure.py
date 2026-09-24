"""Synthetic corner cases plus a genuine ExnessKE-MT5Trial10 500-bar golden."""
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from oracle.config import StructureConfig
from oracle.models import Bar
from oracle.smc.structure import StructureState, advance_structure, evaluate_structure, structure
from oracle.smc.structure_drawing import structure_objects
from oracle.smc.swing_contracts import Pivot
from oracle.smc.swings import load_swing_config

ROOT=Path(__file__).resolve().parents[3]
FIXTURES=Path(__file__).parents[1]/'fixtures'

def bars(rows):
    return [Bar(tf='M15',t_open_ms=1700000100000+i*900000,o=o,h=h,l=l,c=c,source='synthetic',complete=True,tick_volume=1,digits=3)
            for i,(o,h,l,c) in enumerate(rows)]

def seeded():
    return StructureState(major_high=100,major_high_idx=1,major_high_id='confirmed.high',
                          major_low=90,major_low_idx=0,major_low_id='confirmed.low')

@pytest.mark.parametrize('amount,event',[(.04,False),(.06,True)])
def test_minimum_body_break_and_first_break_is_bos(amount,event):
    data=bars([[99,100,98,99]]*5+[[100,101,99,100+amount]])
    result=evaluate_structure(seeded(),data,[],1,StructureConfig())
    assert bool(result.last_event)==event
    if event:
        assert result.last_event.kind=='BOS'
        assert result.last_event.trend_before=='UNDEFINED'
        assert result.trend=='BULLISH'

def test_wick_only_and_forming_bars_cannot_break():
    data=bars([[99,100,98,99]]*5+[[99,102,89,99]])
    assert evaluate_structure(seeded(),data,[],1,StructureConfig()).last_event is None
    forming=data[-1].transition(complete=False)
    assert advance_structure(None,forming) is None
    assert advance_structure(None,data[-1],bar_phase='INTRA') is None

def test_protected_interval_and_frozen_geometry():
    fixture=json.loads((FIXTURES/'synthetic/structure_protected_interval.json').read_text())
    data=bars(fixture['bars'])
    result=evaluate_structure(seeded(),data,[],1,StructureConfig())
    assert result.protected_low==fixture['expected_protected_low']
    assert result.major_low_idx==fixture['expected_protected_idx']
    assert result.major_low==97
    assert result.major_high is None  # A consumed high cannot produce a BOS each bar.
    with pytest.raises(ValidationError):
        result.last_event.kind='CHoCH'
    again=evaluate_structure(result,data,[],1,StructureConfig())
    assert again.last_event==result.last_event

def test_protection_survives_new_pivots_and_only_choch_flips_defined_trend():
    data=bars([[99,100,98,99]]*5+[[99,100,97,99]])
    state=seeded().model_copy(update={'trend':'BULLISH','protected_low':90})
    pivot=Pivot(tf='M15',idx=2,t_ms=data[2].t_open_ms,price=98,side='LOW',kind='HL',confirmed=True,
                confirmed_at_idx=4,confirmed_at_ms=data[4].t_open_ms+900000,atr=1,leg_atr=2,significant=True,
                opposite_pivot_id='high',gap_adjacent=False,source_bars=(0,1,2,3,4),source_object_ids=tuple(b.id for b in data[:5]))
    assert evaluate_structure(state,data,[pivot],1,StructureConfig()).major_low==90
    lower=bars([[99,100,98,99]]*5+[[89,99,88,89]])
    result=evaluate_structure(state,lower,[],1,StructureConfig())
    assert result.last_event.kind=='CHoCH' and result.trend=='BEARISH'
    assert result.protected_high==100

def test_sweep_query_is_dormant_and_injected():
    data=bars([[99,100,98,99]]*5+[[89,99,88,89]])
    state=seeded().model_copy(update={'trend':'BULLISH','protected_low':90})
    assert evaluate_structure(state,data,[],1,StructureConfig()).last_event.is_mss is False
    calls=[]
    def query(tf,idx,lookback,direction):
        calls.append((tf,idx,lookback,direction));return 'real-sweep-provenance'
    result=evaluate_structure(state,data,[],1,StructureConfig(),query)
    assert result.last_event.is_mss and result.last_event.sweep_id=='real-sweep-provenance'
    assert calls==[('M15',5,10,'DOWN')]

def real_run():
    fixture=json.loads((FIXTURES/'real/candidates-ExnessKE-MT5Trial10-M15-500.json').read_text())
    data=[Bar.model_validate(b) for b in fixture['seed']+fixture['parents'][:500]]
    cursor=structure(data,swing_config=load_swing_config(ROOT/'config/weights.yaml'))
    return fixture,data,cursor

def test_real_500_golden_and_structure_draw_contract():
    fixture,data,first=real_run();_,_,second=real_run()
    text='\n'.join(e.canonical_json() for e in first.events)
    assert text=='\n'.join(e.canonical_json() for e in second.events)
    golden=json.loads((FIXTURES/'real/structure-ExnessKE-MT5Trial10-golden.json').read_text())
    for key in ['server','clock_version','weights_hash']:
        assert golden[key]==fixture['metadata'][key], f'regenerate: {key}'
    assert golden['schema_version']==first.state.schema_version, 'regenerate: structure schema'
    assert golden['weights_hash']==hashlib.sha256((ROOT/'config/weights.yaml').read_bytes()).hexdigest(), 'regenerate: weights'
    assert golden['config']==StructureConfig().model_dump(), 'regenerate: structure configuration'
    assert golden['events_sha256']==hashlib.sha256(text.encode()).hexdigest(), 'regenerate: structure events'
    assert {e.kind for e in first.events}=={'BOS','CHoCH'}
    for event in first.events:
        assert not event.is_mss
        assert event.kind!='CHoCH' or event.trend_before!='UNDEFINED'
        assert event.kind!='BOS' or event.trend_before in ('UNDEFINED',event.trend_after)
    objects=structure_objects(first,data[-1].t_open_ms+900000)
    events=[o for o in objects if o.style.token=='structure.event']
    assert len(events)<=6
    assert len([o for o in objects if o.style.token=='structure.protected'])==1
    for obj,event in zip(events,first.events[-6:],strict=True):
        assert obj.points[-1].t_ms==data[event.break_bar_idx].t_open_ms
        assert obj.text_args['dashed'] and obj.text_args['label_at_end']

def test_prefix_causality_and_no_provisional_inputs():
    _,data,_=real_run();cursor=None;cached=[]
    for bar in data[:90]:
        cursor=advance_structure(cursor,bar)
        cached.append(tuple(e.canonical_json() for e in cursor.events))
    for i in range(20,90,7):
        prefix=structure(data[:i+1])
        assert tuple(e.canonical_json() for e in prefix.events)==cached[i]
