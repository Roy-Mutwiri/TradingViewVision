"""Private login IPC contracts. Intentionally separate from models.py/WS."""

from typing import Literal

from pydantic import Field, JsonValue, SecretStr

from oracle.models import Contract, Millis, Timeframe

PasswordType = Literal["investor", "master"]
TradeMode = Literal["DEMO", "REAL", "CONTEST"]
ConnectStage = Literal[
    "locating_terminal",
    "attaching",
    "authorizing",
    "resolving_symbol",
    "measuring_clock",
    "loading_history",
]


class ConnectRequest(Contract):
    login: int = Field(ge=100000, lt=10000000000, strict=True)
    password: SecretStr = Field(min_length=1)
    password_type: PasswordType = Field(default="investor", alias="passwordType")
    server: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_. -]+$")
    remember: bool = False
    terminal_path: str | None = Field(default=None, alias="terminalPath")


class Check(Contract):
    id: str
    state: Literal["pass", "warn", "halt"]
    message: str


class ConnectProgress(Contract):
    stage: ConnectStage
    ok: bool
    detail: str | None = None
    check: Check | None = None


class OperatorAccount(Contract):
    login: int
    server: str
    name: str
    trade_mode: TradeMode = Field(alias="tradeMode")
    currency: str
    read_only: bool = Field(alias="readOnly")


class SymbolReport(Contract):
    broker: str
    canonical: Literal["XAUUSD"] = "XAUUSD"
    digits: int
    point: float
    contract_size: float = Field(alias="contractSize")
    spread_points: float = Field(alias="spreadPoints")


class ClockReport(Contract):
    offset_s: int = Field(alias="offsetS")
    source: Literal["measured"] = "measured"
    proven: bool
    proof_detail: str | None = Field(default=None, alias="proofDetail")
    clock_version: int = Field(alias="clockVersion")


class HistoryDepth(Contract):
    bars: int
    required: int
    ok: bool


class PreflightReport(Contract):
    account: OperatorAccount
    symbol: SymbolReport
    clock: ClockReport
    history: dict[Timeframe, HistoryDepth]
    checks: list[Check]
    symbols: list[str] = Field(default_factory=list)


class ConnectError(Contract):
    detail: dict[str, JsonValue] = {}
    recoverable: bool = True
    code: str
    message: str
    field: Literal["password", "server", "terminalPath", "login", "symbol"]
    actions: list[str]


class ConnectResult(Contract):
    report: PreflightReport | None = None
    error: ConnectError | None = None


class Profile(Contract):
    login: int
    server: str
    password_type: PasswordType = Field(default="investor", alias="passwordType")
    name: str
    trade_mode: TradeMode = Field(alias="tradeMode")
    last_used_ms: Millis = Field(alias="lastUsedMs")
    terminal_path: str | None = Field(default=None, alias="terminalPath")


class GateSettings(Contract):
    profiles: list[Profile]
    servers: list[str]
    last_server: str = Field(alias="lastServer")
    terminal_path: str | None = Field(alias="terminalPath")
    idle_lock_min: int | None = Field(alias="idleLockMin")
    signup_url: str = Field(alias="signupUrl")
    download_url: str = Field(alias="downloadUrl")


class SessionStatus(Contract):
    trade_mode: TradeMode = Field(alias="tradeMode")
    clock_proven: bool = Field(alias="clockProven")
    trading_capable: bool = Field(alias="tradingCapable")
    state: Literal["connected", "reconnecting", "locked"] = "connected"
