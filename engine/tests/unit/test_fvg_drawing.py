from test_imbalance import candle

from oracle.config import ZonesConfig
from oracle.smc.fvg_drawing import FVGDrawing
from oracle.smc.imbalance import ImbalanceCursor, create_fvg_record, detect_fvg


def test_tick_fill_projection_is_not_a_canonical_transition():
    bars = [candle(0, 99, 100, 98, 99.5), candle(1, 101, 105, 100, 104),
            candle(2, 105, 107, 104, 106)]
    record = create_fvg_record(detect_fvg(bars, atr=10))
    drawing = FVGDrawing(ZonesConfig())
    drawing.cursor = ImbalanceCursor(recent=tuple(bars), records=(record,), next_index=3)
    tick = candle(3, 106, 107, 102, 103).model_copy(update={"complete": False})
    before = drawing.cursor
    obj = drawing.objects([*bars, tick])[0]
    assert obj.text_args["fill_pct"] == .5
    assert obj.text_args["unfilled_lo"] == 100
    assert obj.text_args["unfilled_hi"] == 102
    assert obj.text_args["ce"] == 102
    assert not obj.text_args["weakened"]
    assert drawing.cursor == before
    assert drawing.objects([*bars, tick])[0] == obj


def test_oldest_eviction_retains_records_and_geometry():
    records = []
    for i in range(5):
        bars = [candle(i*3, 99, 100, 98, 99.5), candle(i*3+1, 101, 105, 100, 104),
                candle(i*3+2, 105, 107, 104, 106)]
        records.append(create_fvg_record(detect_fvg(bars, atr=10, start_idx=i*3)))
    drawing = FVGDrawing(ZonesConfig())
    drawing.cursor = ImbalanceCursor(recent=tuple(bars), records=tuple(records), next_index=15)
    output = drawing.objects(bars)
    assert len(output) == 3
    assert [o.text_args["zone_id"] for o in output] == [r.id for r in records[-3:]]
    assert len(drawing.cursor.records) == 5
    assert output[0].points[0].price == records[-3].geometry.price_lo


def test_500_bar_worklog_is_deterministic_and_traces_detector_sources():
    bars = [candle(i, 1000+(i%9)*3, 1001+(i%9)*3, 999+(i%9)*3, 1000.5+(i%9)*3)
            for i in range(500)]
    first = FVGDrawing(ZonesConfig())
    second = FVGDrawing(ZonesConfig())
    for bar in bars:
        assert first.objects([bar]) == second.objects([bar])
    assert first.decisions == second.decisions
    assert first.decisions
    ids = {b.id for b in bars}
    for decision in first.decisions:
        assert decision.source_bars and decision.source_object_ids
        assert set(decision.source_object_ids) <= ids
    before = tuple(first.decisions)
    first.objects(bars)
    assert tuple(first.decisions) == before, "refreshes cannot invent worklog entries"
