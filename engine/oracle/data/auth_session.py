"""Terminal-mediated operator login and sequential preflight at the feed edge."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, cast

from oracle.auth.contracts import (
    Check,
    ClockReport,
    ConnectError,
    ConnectProgress,
    ConnectRequest,
    ConnectResult,
    GateSettings,
    HistoryDepth,
    OperatorAccount,
    PreflightReport,
    Profile,
    SessionStatus,
    SymbolReport,
)
from oracle.auth.discovery import locate_terminal, server_choices
from oracle.auth.profiles import ProfileStore
from oracle.config import OracleConfig
from oracle.data.candle_store import CandleStore
from oracle.data.history_warmup import warm_history
from oracle.data.instrument import Instrument
from oracle.data.mt5_feed import MT5Feed, UTCFeed
from oracle.data.mt5_gateway import Mt5Gateway
from oracle.data.symbol_policy import assert_gold_symbol
from oracle.data.vendor_feed import TwelveDataFeed
from oracle.models import TF_MS, Timeframe
from oracle.transport.errors import EngineError

log = logging.getLogger(__name__)


ReadTerminal = Mt5Gateway  # Compatibility name; SDK access lives only in the gateway.


def required_bars(depth: str | None, tf: str) -> int:
    if depth is None or depth == "max":
        return 0
    match = re.fullmatch(r"(\d+)(d|y)", depth)
    if match is None or TF_MS[tf] is None:
        raise ValueError("History depth must be a duration for a fixed timeframe")
    days = int(match[1]) * (365 if match[2] == "y" else 1)
    step = TF_MS[tf]
    assert step is not None
    return math.ceil(days * 86400000 / step)


def account_directory(config: OracleConfig, login: int, server: str) -> Path:
    identity = hashlib.blake2b(
        f"{config.data.canonical_broker}:{server}:{login}".encode(), digest_size=8
    ).hexdigest()
    return Path(config.data.store_path).parent / "accounts" / identity


class LoginGate:
    def __init__(
        self,
        config: OracleConfig,
        config_dir: Path,
        profiles: ProfileStore,
        api: Any = None,
        locator: Callable[[str | None], Path | None] = locate_terminal,
        vendor: UTCFeed | None = None,
    ) -> None:
        self.config, self.config_dir, self.profiles = config, config_dir, profiles
        self.api, self.locator, self.vendor = api, locator, vendor
        self.report: PreflightReport | None = None
        self.feed: MT5Feed | None = None
        self.authorized: OperatorAccount | None = None
        self.checks: list[Check] = []
        self.symbols: list[str] = []
        self.emit: Callable[[ConnectProgress], None] = lambda event: None

    def settings(self) -> GateSettings:
        profiles, last_server = self.profiles.read()
        path = self.locator(self.config.data.mt5_path)
        return GateSettings(
            profiles=profiles,
            servers=server_choices(
                self.config_dir / "brokers/exness.yaml", [p.server for p in profiles]
            ),
            lastServer=last_server,
            terminalPath=str(path) if path else None,
            idleLockMin=self.config.security.idle_lock_min,
            signupUrl=self.config.broker.signup_url or "https://my.exness.com/accounts/sign-up/",
            downloadUrl=self.config.broker.download_url,
        )

    def _check(self, id: str, state: str, message: str, stage: str) -> None:
        check = Check.model_validate({"id": id, "state": state, "message": message})
        self.checks = [c for c in self.checks if c.id != id] + [check]
        self.emit(
            ConnectProgress.model_validate(
                {"stage": stage, "ok": state != "halt", "detail": message, "check": check}
            )
        )

    def _stage(self, stage: str, detail: str) -> None:
        self.emit(ConnectProgress.model_validate({"stage": stage, "ok": True, "detail": detail}))

    def close(self) -> None:
        if self.feed and self.feed.store:
            self.feed.store.close()
        self.feed, self.report, self.authorized = None, None, None
        if self.api is not None:
            self.api.shutdown()

    def _error(self, code: str, message: str, field: str, actions: list[str]) -> ConnectResult:
        return ConnectResult(
            error=ConnectError.model_validate(
                {"code": code, "message": message, "field": field, "actions": actions}
            )
        )

    def _terminal_error(self, server: str) -> ConnectResult:
        code = int(self.api.last_error()[0])
        if code == -6:
            return self._error(
                "AUTH_FAILED",
                f"Login or password rejected by {server}.",
                "password",
                ["re-enter", "forgot-password"],
            )
        if code == -2:
            return self._error(
                "WRONG_SERVER", f"That login isn't on {server}.", "server", ["choose-server"]
            )
        if code in (-10003, -5):
            return self._error(
                "TERMINAL_START",
                "MetaTrader 5 won't start. It may be mid-update.",
                "terminalPath",
                ["retry", "open-terminal"],
            )
        return self._error(
            "NO_CONNECTION",
            f"The terminal can't reach {server}.",
            "server",
            ["retry", "check-internet"],
        )

    def connect_profile(
        self, login: int, server: str, password_type: str, emit: Callable[[ConnectProgress], None]
    ) -> ConnectResult:
        profiles, _ = self.profiles.read()
        profile = next(
            (
                p
                for p in profiles
                if p.login == login and p.server == server and p.password_type == password_type
            ),
            None,
        )
        if profile is None:
            return self._error(
                "PROFILE_MISSING",
                "Choose an account or enter its credentials.",
                "login",
                ["re-enter"],
            )
        try:
            password = self.profiles.password(profile)
        except Exception:
            password = None
        if not password:
            return self._error(
                "KEYCHAIN_MISSING",
                "Saved password is unavailable. Re-enter it to connect.",
                "password",
                ["re-enter"],
            )
        request = ConnectRequest.model_validate(
            {
                "login": profile.login,
                "server": profile.server,
                "password": password,
                "passwordType": profile.password_type,
                "remember": True,
                "terminalPath": profile.terminal_path,
            }
        )
        password = ""
        return self.connect(request, emit)

    def connect(
        self, request: ConnectRequest, emit: Callable[[ConnectProgress], None]
    ) -> ConnectResult:
        self.close()
        self.emit, self.checks = emit, []
        self._stage("locating_terminal", "Locating terminal")
        path = self.locator(request.terminal_path or self.config.data.mt5_path)
        if path is None:
            return self._error(
                "TERMINAL_NOT_FOUND",
                "MetaTrader 5 isn't installed, or ORACLE can't find it.",
                "terminalPath",
                ["pick-path", "download"],
            )
        if self.api is None:
            if sys.platform != "win32":
                return self._error(
                    "WINDOWS_REQUIRED",
                    "MT5 authentication requires Windows.",
                    "terminalPath",
                    ["download"],
                )
            try:
                self.api = Mt5Gateway(tick_poll_ms=self.config.data.tick_poll_ms)
            except ImportError:
                return self._error(
                    "SDK_MISSING",
                    "Install ORACLE's MT5 Python integration to attach to the terminal.",
                    "terminalPath",
                    ["install-sdk"],
                )
        self._stage("attaching", "Attaching")
        self._stage("authorizing", "Authorizing")
        password = request.password.get_secret_value()
        try:
            attached = self.api.initialize(
                str(path),
                login=request.login,
                password=password,
                server=request.server.strip(),
                timeout=30000,
            )
        finally:
            password = ""
        if not attached:
            result = self._terminal_error(request.server)
            self.api.shutdown()
            return result
        self._check("terminal", "pass", "Terminal attached", "authorizing")
        account = self.api.account_info()
        if account is None:
            result = self._terminal_error(request.server)
            self.api.shutdown()
            return result
        if (
            int(account.login) != request.login
            or str(account.server).casefold() != request.server.strip().casefold()
        ):
            self.api.shutdown()
            return self._error(
                "WRONG_SERVER",
                f"That login isn't on {request.server}.",
                "server",
                ["choose-server"],
            )
        prefix = str(account.server).split("-", 1)[0].casefold()
        if not prefix.startswith(self.config.data.canonical_broker.casefold()):
            self.api.shutdown()
            return self._error(
                "WRONG_BROKER",
                "This studio is pinned to Exness. Choose your Exness server.",
                "server",
                ["choose-server"],
            )
        if (
            self.config.data.canonical_server
            and account.server != self.config.data.canonical_server
        ):
            self.api.shutdown()
            return self._error(
                "WRONG_SERVER",
                "Connected server differs from the pinned canonical server.",
                "server",
                ["choose-server"],
            )
        modes = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
        mode = modes.get(int(account.trade_mode))
        if mode is None:
            self.api.shutdown()
            return self._error(
                "ACCOUNT_TYPE", "Unable to verify DEMO / REAL account type.", "server", ["retry"]
            )
        readonly = not bool(account.trade_allowed)
        if request.password_type == "investor" and not readonly:
            self.api.shutdown()
            return self._error(
                "PASSWORD_TYPE",
                "This password grants trading access. Use your investor password or select Master.",
                "password",
                ["switch-to-investor"],
            )
        self.authorized = OperatorAccount.model_validate(
            {
                "login": int(account.login),
                "server": str(account.server),
                "name": str(account.name),
                "currency": str(account.currency),
                "tradeMode": mode,
                "readOnly": readonly,
            }
        )
        self._check("account", "pass", "Account authorized", "authorizing")
        self._check("account_type", "pass", f"{mode} account verified", "authorizing")
        directory = account_directory(self.config, request.login, str(account.server))
        directory.mkdir(parents=True, exist_ok=True)
        scoped = self.config.data.model_copy(
            update={
                "store_path": str(directory / "candles.duckdb"),
                "broker_clock_path": str(directory / "broker-clock.json"),
                "clock_proof_path": str(directory / "clock-proof.json"),
            }
        )
        store = CandleStore(scoped.store_path, scoped.canonical_broker)
        store.bind_server(str(account.server))
        store.bind_account(str(account.server), int(account.login))
        self.feed = MT5Feed(self.api, scoped, store=store, allow_unproven=True)
        result = self.preflight()
        try:
            if request.remember:
                profile = Profile(
                    login=request.login,
                    server=str(account.server),
                    passwordType=request.password_type,
                    name=str(account.name),
                    tradeMode=cast(Any, mode),
                    lastUsedMs=time.time_ns() // 1000000,
                    terminalPath=str(path),
                )
                self.profiles.save(profile, request.password.get_secret_value())
            else:
                self.profiles.remember_server(str(account.server))
        except Exception:
            self._check(
                "remember",
                "warn",
                "Account connected, but native keychain saving failed. Nothing was written to a password file.",
                "loading_history",
            )
            if self.report:
                self.report = self.report.model_copy(update={"checks": list(self.checks)})
                result = ConnectResult(report=self.report)
        return result

    def preflight(
        self, symbol_override: str | None = None, download: bool = False
    ) -> ConnectResult:
        if self.authorized is None or self.feed is None:
            return self._error(
                "AUTH_REQUIRED", "Authenticate before running preflight.", "login", ["re-enter"]
            )
        self.report = None
        self.checks = [
            c for c in self.checks if c.id in ("terminal", "account", "account_type", "remember")
        ]
        self._stage("resolving_symbol", "Resolving symbol")
        self.symbols = sorted(s.name for s in self.api.symbols_get() or ())
        symbol = symbol_override or next(
            (s for s in self.config.data.broker_symbol_patterns if s in self.symbols), ""
        )
        try:
            assert_gold_symbol(symbol)
        except EngineError as exc:
            return ConnectResult(
                error=ConnectError(
                    code=exc.fault.code,
                    message=exc.fault.message,
                    detail=exc.fault.detail,
                    field="symbol",
                    actions=["choose-symbol"],
                )
            )
        if symbol and symbol not in self.config.data.broker_symbol_patterns:
            return ConnectResult(
                error=ConnectError(
                    code="SYMBOL_UNRESOLVED",
                    message="Select a configured preferred spot gold symbol.",
                    detail={
                        "symbol": symbol,
                        "candidates": list(self.config.data.broker_symbol_patterns),
                    },
                    field="symbol",
                    actions=["choose-symbol"],
                )
            )
        if not symbol or symbol not in self.symbols or not self.api.symbol_select(symbol, True):
            self._check(
                "symbol",
                "halt",
                "Connected, but no gold symbol on this account. Choose a symbol offered by the server.",
                "resolving_symbol",
            )
            return self._report(
                SymbolReport(broker="", digits=0, point=0, contractSize=0, spreadPoints=0),
                ClockReport(offsetS=0, proven=False, clockVersion=0),
            )
        self.feed.broker_symbol = symbol
        self._check("symbol", "pass", "Gold symbol resolved", "resolving_symbol")
        info = self.api.symbol_info(symbol)
        try:
            instrument = Instrument.from_mt5(info)
        except (ValueError, AttributeError):
            self._check(
                "instrument",
                "halt",
                "HALTED: digits must be 2 or 3 and contract_size must be 100. Choose the correct gold symbol.",
                "resolving_symbol",
            )
            return self._report(
                SymbolReport(
                    broker=symbol,
                    digits=getattr(info, "digits", 0),
                    point=getattr(info, "point", 0),
                    contractSize=getattr(info, "trade_contract_size", 0),
                    spreadPoints=0,
                ),
                ClockReport(offsetS=0, proven=False, clockVersion=0),
            )
        self.feed.instrument = instrument
        self._check("instrument", "pass", "Instrument constants verified", "resolving_symbol")
        self._stage("measuring_clock", "Measuring server clock")
        tick = self.api.symbol_info_tick(symbol)
        measured = round((int(tick.time) - time.time()) / 900) * 900 if tick else 0
        sr = SymbolReport(
            broker=symbol,
            digits=instrument.digits,
            point=instrument.point,
            contractSize=instrument.contract_size,
            spreadPoints=max(0, (float(tick.ask) - float(tick.bid)) / instrument.point)
            if tick
            else 0,
        )
        try:
            from oracle.data.broker_clock import BrokerClock

            clock_path = Path(self.feed.config.broker_clock_path)
            if self.feed.clock is None and clock_path.exists():
                self.feed.clock = BrokerClock.load(clock_path)
                self.feed.clock.assert_expected(
                    self.config.data.canonical_broker, self.config.data.expected_offset_s
                )
            self.feed.vendor = None
            self.feed.refresh_offset(startup=True)
        except (ValueError, RuntimeError):
            self._check(
                "clock",
                "halt",
                f"HALTED: measured offset {measured}s; expected 0s or 3600s. Check the terminal tick and server clock.",
                "measuring_clock",
            )
            return self._report(sr, ClockReport(offsetS=measured, proven=False, clockVersion=0))
        assert self.feed.clock is not None
        measured = self.feed.clock.offset_ms_at(int(tick.time) * 1000) // 1000 if tick else measured
        self._check("clock", "pass", f"Broker clock retained/verified: {measured}s", "measuring_clock")
        vendor = self.vendor
        key = os.environ.get("TWELVE_DATA_API_KEY")
        if vendor is None and key:
            vendor = TwelveDataFeed(key)
        proven = False
        proof_detail = "Unproven — TWELVE_DATA_API_KEY is not configured."
        if vendor is None:
            self._check("clock_proof", "warn", proof_detail, "measuring_clock")
        else:
            try:
                self.feed.vendor = vendor
                self.feed.refresh_offset(startup=True)
                proven = self.feed.vendor_verified
                proof_detail = "Independent UTC correlation verified"
                self._check("clock_proof", "pass", proof_detail, "measuring_clock")
            except Exception:
                proof_detail = "UTC correlation failed or disagrees with measurement. Rederive the clock before continuing."
                self._check("clock_proof", "halt", proof_detail, "measuring_clock")
        self._stage("loading_history", "Loading history")
        history: dict[Timeframe, HistoryDepth] = {}
        for name in TF_MS:
            tf = cast(Timeframe, name)
            depth = self.config.data.history_depth.get(name)
            required = required_bars(depth, name)
            rows: Any = None
            if depth is not None:
                timeframe = getattr(self.api, f"TIMEFRAME_{name}")
                warm_history(
                    self.api, symbol, name, required, time.time_ns() // 1000000 + measured * 1000
                )
                if download:
                    now = time.time_ns() // 1000000 + measured * 1000
                    earliest = 0 if depth == "max" else now - required * cast(int, TF_MS[name])
                    self.feed.raw_history(tf, max(0, earliest), now)
                rows = self.api.copy_rates_from_pos(symbol, timeframe, 0, required or 100000)
            count = len(rows) if rows is not None else 0
            ok = depth is None or count >= required and count > 0
            history[tf] = HistoryDepth(bars=count, required=required, ok=ok)
        short = [f"{tf}: {h.bars:,} / {h.required:,}" for tf, h in history.items() if not h.ok]
        self._check(
            "history",
            "warn" if short else "pass",
            "History short: "
            + "; ".join(short)
            + ". Download history; set Max bars in chart to Unlimited."
            if short
            else "Configured history depth available",
            "loading_history",
        )
        wide = sr.spread_points > self.config.data.max_spread_points
        self._check(
            "spread",
            "warn" if wide else "pass",
            f"Spread {sr.spread_points:.0f} points"
            + (
                " exceeds configured maximum; market may be closed or account may be wrong."
                if wide
                else " within configured maximum"
            ),
            "loading_history",
        )
        assert self.feed.clock is not None
        return self._report(
            sr,
            ClockReport(
                offsetS=measured,
                proven=proven,
                proofDetail=proof_detail,
                clockVersion=self.feed.clock.version,
            ),
            history,
        )

    def _report(
        self,
        symbol: SymbolReport,
        clock: ClockReport,
        history: dict[Timeframe, HistoryDepth] | None = None,
    ) -> ConnectResult:
        assert self.authorized is not None
        self.report = PreflightReport(
            account=self.authorized,
            symbol=symbol,
            clock=clock,
            history=history or {},
            checks=list(self.checks),
            symbols=self.symbols,
        )
        return ConnectResult(report=self.report)

    def status(self) -> SessionStatus:
        if self.report is None or any(c.state == "halt" for c in self.report.checks):
            raise RuntimeError("Authentication and non-halting preflight required before Studio")
        return SessionStatus(
            tradeMode=self.report.account.trade_mode,
            clockProven=self.report.clock.proven,
            tradingCapable=not self.report.account.read_only,
        )

    def diagnostics(self) -> str:
        if self.report is None:
            return "No authenticated preflight report."
        r = self.report
        lines = [
            "ORACLE STUDIO diagnostics",
            f"Login: {r.account.login}",
            f"Server: {r.account.server}",
            f"Account mode: {r.account.trade_mode}",
            f"Read-only: {r.account.read_only}",
            f"Symbol: {r.symbol.broker} -> {r.symbol.canonical}",
            f"Clock: {r.clock.offset_s}s; version {r.clock.clock_version}; proven {r.clock.proven}",
        ]
        lines += [f"{c.id}: {c.state.upper()} — {c.message}" for c in r.checks]
        lines += [f"{tf}: {h.bars} bars / {h.required} required" for tf, h in r.history.items()]
        return "\n".join(lines)
