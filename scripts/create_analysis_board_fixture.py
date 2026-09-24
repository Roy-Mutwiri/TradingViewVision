"""Renderer fixture from real resolver projections over explicitly synthetic M1."""
import json
from pathlib import Path

from oracle.analysis.contracts import Call
from oracle.analysis.ledger import CallLedger
from oracle.analysis.resolver import CallResolver, QualityWindow
from oracle.analysis.scoring import board
from oracle.models import Bar

root = Path(__file__).resolve().parents[1]
fixture = json.loads((root/'engine/tests/fixtures/analysis_calls.json').read_text())
ledger = CallLedger()
resolver = CallResolver(ledger, fixture['tick_size'])
bars = [Bar.model_validate(value) for value in fixture['bars']]
for index in (0, 1, 3, 4):
    call = ledger.create(Call.model_validate(fixture['calls'][index]))
    resolver.evaluate(call.id, bars, fixture['now_ms'], clock_version=1)
cancel = ledger.create(Call.model_validate(fixture['calls'][5]))
ledger.cancel(cancel.id, 'OPERATOR_CANCELLED', at_ms=cancel.created_ms+1000)
void = ledger.create(Call.model_validate(fixture['calls'][6]))
resolver.evaluate(void.id, bars, fixture['now_ms'], clock_version=1, quality=[QualityWindow(
    start_ms=void.created_ms, end_ms=void.created_ms+60000, state='STALE',
    reason='Synthetic terminal outage')])
(root/'engine/tests/fixtures/analysis_board.json').write_text(board(
    ledger.rows, fixture['now_ms']).canonical_json()+'\n', encoding='utf-8')
