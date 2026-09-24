"""Create declared future-phase modules without implementing later phases."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "data": "mt5_feed vendor_feed candle_store quality",
    "smc": "swings structure order_blocks imbalance liquidity ranges killzones htf confluence",
    "forecast": "scenarios features model backtest scoring",
    "intel": "calendar news correlations positioning sentiment fuser",
    "director": "director budget policy segments camera",
    "transport": "ws_server protocol",
    "distribution": "telegram obs",
    "ops": "supervisor health dashboard telemetry",
    "replay": "harness golden",
}
for package, modules in MODULES.items():
    directory = ROOT / "engine/oracle" / package
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "__init__.py").touch()
    phase = {"data": 1, "replay": 1, "smc": 2, "forecast": 7, "intel": 6,
             "director": 8, "transport": 3, "distribution": 9,
             "ops": 9}[package]
    for module in modules.split():
        path = directory / f"{module}.py"
        if not path.exists():
            path.write_text(f'"""Phase {phase} owns {package}.{module}; intentionally unavailable."""\n'
                            'from typing import NoReturn\n\n\n'
                            'def unavailable() -> NoReturn:\n'
                            f'    """Explicit failure; never pretend a future service is working."""\n'
                            f'    raise NotImplementedError("phase_{phase}:{package}.{module}")\n',
                            encoding="utf-8")

TS_MODULES = {
    "chart": "LightweightChartsCore AdvancedChartsCore",
    "primitives": "OrderBlock FVG StructureLine LiquidityPool Sweep RangeSplit Killzone ScenarioPath TargetLadder",
    "fx": "strokeOn pulse sweepFlash heatStrip camera",
    "hud": "BiasPanel ScenarioCards IntelTicker SessionStrip Scoreboard StatusChips Subtitles",
    "net": "socket",
}
for directory, modules in TS_MODULES.items():
    target = ROOT / "app/src" / directory
    target.mkdir(parents=True, exist_ok=True)
    for module in modules.split():
        suffix = ".tsx" if directory == "hud" else ".ts"
        path = target / (module + suffix)
        if not path.exists():
            path.write_text(f'/** Future phase owns {directory}/{module}. */\n'
                            'export function unavailable(): never {\n'
                            f'  throw new Error("unimplemented:{directory}/{module}");\n'
                            '}\n', encoding="utf-8")
for module in ("main", "preload"):
    path = ROOT / "app/electron" / (module + ".ts")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text('/** Phase 3 owns the Electron shell. */\nexport {};\n', encoding="utf-8")
for directory in ("engine/tests/unit", "engine/tests/golden", "engine/tests/integration",
                  "engine/tests/property", "engine/tests/chaos", "app/tests/unit",
                  "app/tests/visual", "artifacts/phase0", "artifacts/phase1"):
    path = ROOT / directory
    path.mkdir(parents=True, exist_ok=True)
    (path / ".gitkeep").touch()
for theme in ("dark", "light", "brand"):
    path = ROOT / "app/src/theme" / f"{theme}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text('{"tokens":{},"status":"phase3_pending"}\n', encoding="utf-8")
