"""Validated YAML configuration with explicit ORACLE__SECTION__KEY overrides."""

import json
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from oracle.models import Contract, Language


class DataConfig(Contract):
    authoritative: Literal["mt5"] = "mt5"
    canonical_broker: str = "exness"
    canonical_server: str | None = None
    canonical_symbol: Literal["XAUUSD"] = "XAUUSD"
    broker_symbol_patterns: tuple[str, ...] = (
        "XAUUSD",
        "XAUUSDm",
        "XAUUSDc",
        "XAUUSDz",
    )
    backfill_vendor: Literal["twelve_data"] = "twelve_data"
    expected_offset_s: tuple[int, ...] = (0, 3600)
    broker_clock_path: str = "runtime/broker-clock.json"
    clock_proof_path: str = "runtime/clock-proof.json"
    history_depth: dict[str, str] = Field(
        default_factory=lambda: {
            "M1": "90d",
            "M5": "180d",
            "M15": "1y",
            "H1": "3y",
            "H4": "5y",
            "D1": "10y",
            "W1": "max",
        }
    )
    stale_ms: int = Field(default=15000, gt=0)
    wide_spread_points: float = Field(default=50, gt=0)
    max_spread_points: float = Field(default=200, gt=0)
    poll_ms: int = Field(default=250, ge=50)
    tick_poll_ms: int = Field(default=50, ge=10)
    bar_poll_ms: int = Field(default=1000, ge=250)
    render_throttle_hz: int = Field(default=10, ge=1, le=30)
    max_tick_latency_ms: int = Field(default=250, gt=0)
    grace_ms: int = Field(default=1500, ge=0)
    store_path: str = "runtime/candles.duckdb"
    mt5_path: str | None = None


class StructureConfig(Contract):
    break_mode: Literal["body", "wick"] = "body"
    thin_day_factor: float = Field(default=0.8, ge=0, le=1)
    min_break_atr: float = Field(default=0.05, ge=0)
    internal: Literal[False] = False
    mss_sweep_lookback_bars: int = Field(default=10, ge=1)
    show_protected_swing: bool = True
    max_events_visible: int = Field(default=6, ge=1, le=6)


class ZoneLimits(Contract):
    ob: int = Field(default=3, ge=1)
    fvg: int = Field(default=3, ge=1)


class ZonesConfig(Contract):
    fvg_min_atr: float = Field(default=0.20, ge=0)
    fvg_merge_overlap: float = Field(default=0.5, ge=0, le=1)
    max_merged_span_atr: float = Field(default=2.5, gt=0)
    max_inversion_depth: Literal[1] = 1
    ob_displacement_atr: float = Field(default=1.5, gt=0)
    ob_require_fvg: bool = True
    ob_require_structure_break: bool = True
    ob_boundary: Literal["body_to_wick", "full_range", "body_only"] = "body_to_wick"
    ob_mitigation: Literal["wick_50", "body_inside", "body_through"] = "wick_50"
    ob_max_cluster: int = Field(default=3, ge=1)
    ob_max_leg_bars: int = Field(default=10, ge=1)
    ob_candidate_on_displacement: bool = True
    ob_merge_overlap: float = Field(default=0.5, ge=0, le=1)
    zone_ttl_bars: int = Field(default=50, ge=1)
    max_visible_per_tf: ZoneLimits = ZoneLimits()
    htf_overlay: tuple[Literal["H4", "H1"], ...] = ("H4", "H1")


class ChartConfig(Contract):
    density: Literal["clean", "analyst", "notebook"] = "notebook"
    visible_bars: int = Field(default=1500, ge=50, le=10000)
    lookback: int = Field(default=500, ge=0, le=10000)
    update_hz: int = Field(default=10, ge=1, le=30)


class UTBotOverride(Contract):
    enabled: bool | None = None
    key: float | None = Field(default=None, gt=0)
    atr_period: int | None = Field(default=None, ge=1, le=500)
    heikin_ashi: bool | None = None
    confirm_on_close: bool | None = None
    show_stop_line: bool | None = None
    color_bars: bool | None = None


class UTBotConfig(Contract):
    enabled: bool = True
    key: float = Field(default=1.0, gt=0)
    atr_period: int = Field(default=10, ge=1, le=500)
    heikin_ashi: bool = False
    confirm_on_close: bool = True
    show_stop_line: bool = False
    color_bars: bool = False
    label_budget: int = Field(default=100, ge=1, le=500)
    per_timeframe: dict[str, UTBotOverride] = Field(
        default_factory=lambda: {
            "M1": UTBotOverride(enabled=False),
            "M15": UTBotOverride(key=1),
            "H1": UTBotOverride(key=2),
        }
    )

    def for_tf(self, tf: str) -> "UTBotConfig":
        override = self.per_timeframe.get(tf)
        return UTBotConfig.model_validate(
            self.model_dump() | (override.model_dump(exclude_none=True) if override else {})
        )


class IndicatorsConfig(Contract):
    ut_bot: UTBotConfig = UTBotConfig()


class UIConfig(Contract):
    mode: Literal["broadcast", "operator"] = "broadcast"


class RetentionConfig(Contract):
    min_call_life_ms: int = Field(default=300000, ge=0)
    timeline_dir: str = "runtime/retention"
    gamechanger_events: str | None = "../LetsTalk/data/live_events"


class SpeakerConfig(Contract):
    """Read-only JSONL sink of market frames for the LetsTalk speaker (docs/ORACLE_BRIDGE.md).

    Disabled by default: an ORACLE with no speaker configured behaves exactly as it does today. The sink runs on
    its own daemon thread, drops the oldest frame under backpressure and swallows every exception, so it can
    never block, slow or crash the worker.
    """

    enabled: bool = False
    sink_dir: str = "runtime/speaker"
    hz: float = Field(default=1.0, gt=0, le=10)
    queue_size: int = Field(default=64, ge=1)
    max_bytes: int = Field(default=10_000_000, ge=100_000)
    keep_files: int = Field(default=6, ge=1)


class NarrationConfig(Contract):
    """Compatibility config name for permanently silent on-chart explanations."""
    audio: Literal[False] = False
    on_chart_reasons: Literal[True] = True
    reason_strip_seconds: int = Field(default=20, ge=1)


class SessionsConfig(Contract):
    day_boundary: str = "17:00 America/New_York"
    true_day_open: str = "00:00 America/New_York"


class LiquidityConfig(Contract):
    eq_tolerance_atr: float = Field(default=0.10, gt=0)
    sweep_min_penetration_atr: float = Field(default=0.05, gt=0)
    sweep_reclaim_bars: int = Field(default=3, ge=1)
    max_pools_visible: int = Field(default=6, ge=1)
    named_levels: tuple[Literal["PDH", "PDL", "PWH", "PWL", "ASIA", "LONDON", "NY", "DH", "DL"], ...] = (
        "PDH", "PDL", "PWH", "PWL", "ASIA", "LONDON", "NY", "DH", "DL"
    )


class TradeConfig(Contract):
    min_entry_zone_atr: float = Field(default=0.10, gt=0)
    max_entry_distance_atr: float = Field(default=1.0, gt=0)
    max_live_pending_distance_points: float = Field(default=5.0, gt=0)
    max_pending_age_ms: int = Field(default=600_000, gt=0)
    min_stop_points: float = Field(default=0.0, ge=0)
    stop_buffer_atr: float = Field(default=0.15, ge=0)
    max_stop_atr: float = Field(default=2.0, gt=0)
    min_tp_distance_atr: float = Field(default=0.5, gt=0)
    max_tp_search_atr: float = Field(default=10.0, gt=0)
    tp1_selection: Literal["closer_eq_or_pool"] = "closer_eq_or_pool"
    max_tp_r: float = Field(default=3.0, gt=0)
    min_r: float = Field(default=1.5, gt=0)
    call_expiry_bars: int = Field(default=6, ge=1)


class GradeBConfig(Contract):
    enabled: bool = True


class GradeCConfig(Contract):
    enabled: bool = True
    timeframes: tuple[Literal["M1", "M5"], ...] = ("M1", "M5")
    min_r: float = Field(default=1.0, gt=0)
    stop_buffer_atr: float = Field(default=0.1, ge=0)
    fallback_r: float = Field(default=1.5, gt=0)


class CallsConfig(Contract):
    grade_b: GradeBConfig = GradeBConfig()
    grade_c: GradeCConfig = GradeCConfig()
    max_concurrent: int = Field(default=2, ge=1)
    max_pending: int = Field(default=6, ge=1)
    max_per_direction_per_tf: int = Field(default=1, ge=1)
    allow_opposing_concurrent: Literal[False] = False
    broadcast: Literal["paper", "off", "live"] = "paper"
    require_zone_inside_range: bool = False


class BacktestSplitConfig(Contract):
    """Frozen methodology boundary; timestamps are broker-history UTC milliseconds."""
    in_sample_start_ms: int = Field(default=0, ge=0)
    split_boundary_ms: int = Field(default=1, ge=0)
    out_of_sample_end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "BacktestSplitConfig":
        if self.split_boundary_ms <= self.in_sample_start_ms:
            raise ValueError("Backtest split must follow the in-sample start")
        if self.out_of_sample_end_ms is not None and self.out_of_sample_end_ms <= self.split_boundary_ms:
            raise ValueError("Out-of-sample end must follow the split boundary")
        return self


class DashboardConfig(Contract):
    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)


class BrokerConfig(Contract):
    signup_url: str | None = None
    download_url: str = "https://www.exness.com/metatrader-5/"


class SecurityConfig(Contract):
    idle_lock_min: int | None = Field(default=None, gt=0)


class TelegramConfig(Contract):
    auto_post: bool = False


class DistributionConfig(Contract):
    telegram: TelegramConfig = TelegramConfig()


class EvalConfig(Contract):
    live_bucket_ms: Literal[250] = 250
    replay_source: Literal["m1_synth", "bar_coarse", "recorded"] = "m1_synth"
    record_evalpoints: bool = True


class CandidatesConfig(Contract):
    enabled: bool = True
    candidate_ttl_bars: int = Field(default=3, ge=1)
    fade_ms: Literal[600] = 600
    show_reason_chip: Literal[True] = True
    # Entry and HTF evidence timeframes from the approved Phase 5 configuration.
    timeframes: tuple[Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"], ...] = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1")


class OracleConfig(Contract):
    # Desktop-owned settings are persisted in the same file. They never drive
    # candidate or structure decisions; desktop validation owns their schema.
    stream: dict[str, object] = Field(default_factory=dict)
    living: dict[str, object] = Field(default_factory=dict)
    ui: UIConfig = UIConfig()
    retention: RetentionConfig = RetentionConfig()
    speaker: SpeakerConfig = SpeakerConfig()
    indicators: IndicatorsConfig = IndicatorsConfig()
    chart: ChartConfig = ChartConfig()
    data: DataConfig = DataConfig()
    structure: StructureConfig = StructureConfig()
    zones: ZonesConfig = ZonesConfig()
    eval: EvalConfig = EvalConfig()
    candidates: CandidatesConfig = CandidatesConfig()
    sessions: SessionsConfig = SessionsConfig()
    liquidity: LiquidityConfig = LiquidityConfig()
    trade: TradeConfig = TradeConfig()
    calls: CallsConfig = CallsConfig()
    backtest: BacktestSplitConfig = BacktestSplitConfig()
    narration: NarrationConfig = NarrationConfig()
    broker: BrokerConfig = BrokerConfig()
    security: SecurityConfig = SecurityConfig()
    dashboard: DashboardConfig = DashboardConfig()
    distribution: DistributionConfig = DistributionConfig()
    language: Language = "en"
    log_path: str = "runtime/events.jsonl"


def load_config(path: Path) -> OracleConfig:
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError("configuration root must be a mapping")
    values: dict[str, object] = dict(raw)
    for key, value in sorted(os.environ.items()):
        if not key.startswith("ORACLE__"):
            continue
        parts = key.removeprefix("ORACLE__").lower().split("__")
        target = values
        for part in parts[:-1]:
            child = target.setdefault(part, {})
            if not isinstance(child, dict):
                raise TypeError("override path is not a mapping")
            target = child
        try:
            parsed: object = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        target[parts[-1]] = parsed
    return OracleConfig.model_validate(values)



