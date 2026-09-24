import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from oracle.data.mt5_gateway import Mt5Gateway


class LoadedTerminal:
    TIMEFRAME_M1 = 1

    def __init__(self):
        self.calls = []
        self.started = threading.Event()
        self.quote_times = []
        self.thread_ids = set()

    def symbol_info_tick(self, symbol):
        self.thread_ids.add(threading.get_ident())
        self.quote_times.append(time.monotonic())
        return SimpleNamespace(time_msc=time.time_ns() // 1000000, bid=4300, ask=4300.14)

    def copy_rates_from_pos(self, symbol, tf, pos, count):
        self.thread_ids.add(threading.get_ident())
        self.calls.append((symbol, count))
        self.started.set()
        time.sleep(0.07)
        return [{"time": 100000 - pos - i} for i in range(count)]

    def shutdown(self):
        self.thread_ids.add(threading.get_ident())


def test_ticks_and_foreground_preempt_chunked_bulk():
    terminal = LoadedTerminal()
    gateway = Mt5Gateway(terminal, tick_poll_ms=10)
    gateway.watch("XAUUSDz")

    def bulk():
        with gateway.priority(gateway.PRIORITY_BULK):
            gateway.copy_rates_from_pos("bulk", 1, 0, 18000)

    worker = threading.Thread(target=bulk)
    worker.start()
    assert terminal.started.wait(1)
    started = time.monotonic()
    with gateway.foreground():
        gateway.copy_rates_from_pos("foreground", 1, 0, 10)
    elapsed = (time.monotonic() - started) * 1000
    worker.join(timeout=3)
    assert not worker.is_alive()
    gateway.close()
    assert elapsed < 250
    assert terminal.calls[1][0] == "foreground"
    assert max(count for _, count in terminal.calls) <= 5000
    assert len(terminal.quote_times) >= 4
    assert max(b - a for a, b in zip(terminal.quote_times, terminal.quote_times[1:])) < 0.25
    assert len(terminal.thread_ids) == 1
    assert gateway.telemetry()["priorities"]["2"]["calls"] == 18


def test_no_sdk_import_or_dynamic_load_outside_gateway():
    source = Path(__file__).resolve().parents[2] / "oracle"
    for file in source.rglob("*.py"):
        if file.name == "mt5_gateway.py":
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name != "MetaTrader5" for a in node.names), file
            if isinstance(node, ast.ImportFrom):
                assert node.module != "MetaTrader5", file
            if isinstance(node, ast.Call):
                assert not any(
                    isinstance(a, ast.Constant) and a.value == "MetaTrader5" for a in node.args
                ), file
