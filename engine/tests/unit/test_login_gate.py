import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from oracle.auth.contracts import ConnectRequest, OperatorAccount
from oracle.auth.discovery import discover_servers, extract_servers
from oracle.auth.profiles import SERVICE, ProfileStore
from oracle.config import DataConfig, OracleConfig
from oracle.data.auth_session import LoginGate, ReadTerminal, account_directory
from oracle.data.broker_bar import RawBrokerBar
from oracle.ops.dashboard import create_dashboard
from oracle.ops.telemetry import configure_logging
from oracle.transport.protocol import export_schema

SECRET = "fixture-investor-secret-NOT-A-REAL-PASSWORD"
NOW = 1789660800


class Vault:
    def __init__(self):
        self.items = {}

    def get_password(self, service, account):
        return self.items.get((service, account))

    def set_password(self, service, account, password):
        self.items[(service, account)] = password

    def delete_password(self, service, account):
        self.items.pop((service, account), None)


class Terminal:
    def __init__(self):
        self.login = 81740106
        self.server = "ExnessKE-MT5Trial10"
        self.allowed = False
        self.attached = True
        self.error = -6
        self.offset = 0
        self.digits = 2
        self.contract = 100
        self.symbols = ["XAUUSDm"]
        self.initializations = []
        self.closed = 0

    def initialize(self, path, **kwargs):
        self.initializations.append((path, kwargs))
        return self.attached

    def shutdown(self):
        self.closed += 1

    def last_error(self):
        return self.error, "password=" + SECRET

    def account_info(self):
        return SimpleNamespace(
            login=self.login,
            server=self.server,
            trade_mode=0,
            name="Fixture Operator",
            currency="USD",
            trade_allowed=self.allowed,
            balance=91234.56,
            equity=99999.99,
        )

    def symbols_get(self):
        return [SimpleNamespace(name=s) for s in self.symbols]

    def symbol_select(self, symbol, selected):
        return True

    def symbol_info(self, symbol):
        return SimpleNamespace(
            digits=self.digits, point=0.01, trade_tick_size=0.01, trade_contract_size=self.contract
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=NOW + self.offset, bid=2000, ask=2000.14)

    def copy_rates_from_pos(self, symbol, tf, start, count):
        return [0] * 10

    def terminal_info(self):
        return SimpleNamespace(maxbars=2147483647)

    def __getattr__(self, name):
        if name.startswith("TIMEFRAME_"):
            return name
        raise AttributeError(name)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr("oracle.data.auth_session.time.time", lambda: NOW)
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    config_root = tmp_path / "config"
    config_root.mkdir()
    vault, terminal = Vault(), Terminal()
    config = OracleConfig(data=DataConfig(store_path=str(tmp_path / "runtime/candles.duckdb")))
    gate = LoginGate(
        config,
        config_root,
        ProfileStore(config_root / "profiles.json", vault),
        api=terminal,
        locator=lambda preferred: tmp_path / "terminal64.exe",
    )
    yield gate, terminal, vault, config_root
    gate.close()


def request(**changes):
    return ConnectRequest.model_validate(
        {
            "login": 81740106,
            "server": "ExnessKE-MT5Trial10",
            "password": SECRET,
            "passwordType": "investor",
            "remember": True,
        }
        | changes
    )


def test_wrong_password_writes_nothing_and_focuses_password(setup):
    gate, terminal, vault, root = setup
    terminal.attached = False
    result = gate.connect(request(), lambda e: None)
    assert result.error.code == "AUTH_FAILED"
    assert result.error.field == "password"
    assert "ExnessKE-MT5Trial10" in result.error.message
    assert SECRET not in result.model_dump_json()
    assert not gate.profiles.path.exists() and not vault.items
    with pytest.raises(RuntimeError):
        gate.status()


def test_wrong_server_highlights_server_never_saves(setup):
    gate, terminal, vault, root = setup
    terminal.server = "ExnessKE-MT5Real10"
    result = gate.connect(request(), lambda e: None)
    assert result.error.code == "WRONG_SERVER"
    assert result.error.field == "server"
    assert "ExnessKE-MT5Trial10" in result.error.message
    assert not vault.items and not gate.profiles.path.exists()


def test_missing_terminal_is_not_bad_credentials(setup):
    gate, terminal, vault, root = setup
    gate.locator = lambda preferred: None
    result = gate.connect(request(), lambda e: None)
    assert result.error.code == "TERMINAL_NOT_FOUND"
    assert result.error.field == "terminalPath"
    assert not terminal.initializations and not vault.items


def test_remember_password_only_keychain_and_no_config_or_log_hits(setup):
    gate, terminal, vault, root = setup
    log_path = root.parent / "runtime/events.jsonl"
    configure_logging(log_path)
    result = gate.connect(request(), lambda e: None)
    assert result.report.account.read_only
    assert vault.items[(SERVICE, "ExnessKE-MT5Trial10:81740106:investor")] == SECRET
    profiles = json.loads(gate.profiles.path.read_text())
    assert "password" not in profiles["profiles"][0]
    assert profiles["profiles"][0]["passwordType"] == "investor"
    logging.getLogger("oracle.test").error('password="%s"', SECRET)
    for handler in logging.getLogger("oracle").handlers:
        handler.flush()
    for path in [*root.rglob("*"), *root.parent.rglob("*.jsonl")]:
        if path.is_file():
            assert SECRET not in path.read_text(errors="ignore")
    assert SECRET not in gate.diagnostics()
    assert SECRET not in result.model_dump_json()
    assert len(terminal.initializations) == 1


def test_password_defaults_investor_and_account_verified_readonly(setup):
    gate, terminal, vault, root = setup
    assert (
        ConnectRequest(login=81740106, password=SECRET, server="Any-New-Server").password_type
        == "investor"
    )
    result = gate.connect(request(), lambda e: None)
    assert result.report.account.read_only is True
    assert gate.status().trading_capable is False
    assert not any("Trading-capable" in c.message for c in result.report.checks)


def test_investor_selection_rejects_a_master_password(setup):
    gate, terminal, vault, root = setup
    terminal.allowed = True
    result = gate.connect(request(), lambda e: None)
    assert result.error.code == "PASSWORD_TYPE"
    assert result.error.field == "password"
    assert not vault.items


def test_master_session_flag_without_order_placement_path(setup):
    gate, terminal, vault, root = setup
    terminal.allowed = True
    result = gate.connect(request(passwordType="master"), lambda e: None)
    assert not result.report.account.read_only
    assert gate.status().trading_capable is True
    adapter = ReadTerminal(terminal)
    forbidden = {"order_send", "OrderSend", "order_check", "OrderSendAsync"}
    for name in forbidden:
        with pytest.raises(AttributeError):
            getattr(adapter, name)
    source = Path(__file__).resolve().parents[2] / "oracle"
    for file in source.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        assert not any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in forbidden
            for n in ast.walk(tree)
        ), file


def test_account_switch_closes_reader_and_segregates_broker_store(setup):
    gate, terminal, vault, root = setup
    gate.connect(request(), lambda e: None)
    old = gate.feed
    directory = account_directory(gate.config, 81740106, terminal.server)
    raw = RawBrokerBar(
        tf="M1",
        t_broker_ms=NOW * 1000,
        o=2000,
        h=2001,
        l=1999,
        c=2000,
        tick_volume=1,
        digits=2,
        complete=True,
    )
    old.store.put_broker(raw.normalize(old.clock))
    terminal.login = 81728915
    second = gate.connect(request(login=81728915, remember=False), lambda e: None)
    assert len(terminal.initializations) == 2 and terminal.closed >= 2
    assert account_directory(gate.config, terminal.login, terminal.server) != directory
    assert gate.feed.store.read("M1", 0, NOW * 1000 + 60000) == []
    with pytest.raises(Exception):
        old.store.read("M1", 0, NOW * 1000 + 60000)
    assert second.report.account.login == 81728915


def test_missing_vendor_key_is_amber_but_studio_allowed(setup):
    gate, terminal, vault, root = setup
    result = gate.connect(request(remember=False), lambda e: None)
    proof = next(c for c in result.report.checks if c.id == "clock_proof")
    assert proof.state == "warn" and "Unproven" in proof.message
    assert not result.report.clock.proven
    assert gate.status().trade_mode == "DEMO"
    assert not gate.status().clock_proven
    assert gate.feed._require_projection()[0] is gate.feed.clock


def test_bad_instrument_and_clock_halt_studio(setup):
    gate, terminal, vault, root = setup
    terminal.contract = 10
    result = gate.connect(request(remember=False), lambda e: None)
    assert any(c.id == "instrument" and c.state == "halt" for c in result.report.checks)
    with pytest.raises(RuntimeError):
        gate.status()
    terminal.contract = 100
    terminal.offset = 7200
    result = gate.connect(request(remember=False), lambda e: None)
    assert any(
        c.id == "clock" and c.state == "halt" and "7200" in c.message for c in result.report.checks
    )
    with pytest.raises(RuntimeError):
        gate.status()


def test_money_absent_from_private_contract_and_broadcast_schema(setup, tmp_path):
    gate, terminal, vault, root = setup
    result = gate.connect(request(remember=False), lambda e: None)
    assert "balance" not in result.report.model_dump_json()
    with pytest.raises(ValidationError):
        OperatorAccount.model_validate(result.report.account.model_dump() | {"balance": 91234.56})
    schema = tmp_path / "wire.json"
    export_schema(schema)
    for term in ("OperatorAccount", "AccountInfo", "balance", "equity", "free_margin", "password"):
        assert term not in schema.read_text()
    studio = gate.status().model_dump(mode="json", by_alias=True)
    assert set(studio) == {"tradeMode", "clockProven", "tradingCapable", "state"}


def test_credentials_filter_drops_message_structured_args_and_exception(tmp_path):
    path = tmp_path / "events.jsonl"
    configure_logging(path)
    logger = logging.getLogger("oracle.redaction")
    logger.info("ordinary safe event")
    logger.info("password=%s", SECRET)
    logger.info("credentials %s", {"password": SECRET})
    logger.info("credentials %s", {"passwd": SECRET})
    try:
        raise ValueError("pwd=" + SECRET)
    except ValueError:
        logger.exception("unexpected error")
    for handler in logging.getLogger("oracle").handlers:
        handler.flush()
    text = path.read_text()
    assert SECRET not in text and "ordinary safe event" in text


def test_binary_server_discovery_even_odd_offsets_best_effort(tmp_path):
    raw = "garbage\0ExnessKE-MT5Trial10\0Exness-MT5Real8\0NotAServer\0".encode("utf-16-le")
    assert extract_servers(raw) == ["Exness-MT5Real8", "ExnessKE-MT5Trial10"]
    assert extract_servers(b"x" + raw) == extract_servers(raw)
    folder = tmp_path / "MetaQuotes/Terminal/hash/config"
    folder.mkdir(parents=True)
    (folder / "accounts.dat").write_bytes(raw)
    assert discover_servers(tmp_path) == extract_servers(raw)


def test_dashboard_account_is_offstream_and_requires_auth(setup):
    gate, terminal, vault, root = setup
    strings = Path(__file__).resolve().parents[3] / "config/strings"
    app = create_dashboard(gate.config, strings, account_provider=lambda: gate.authorized)
    with TestClient(app) as client:
        assert client.get("/account").status_code == 401
        gate.connect(request(remember=False), lambda e: None)
        response = client.get("/account")
        assert response.json()["login"] == 81740106
        assert "balance" not in response.text and SECRET not in response.text


def test_saved_profile_password_does_not_return_to_renderer(setup):
    gate, terminal, vault, root = setup
    gate.connect(request(), lambda e: None)
    result = gate.connect_profile(81740106, terminal.server, "investor", lambda e: None)
    assert result.report.account.read_only
    assert SECRET not in gate.settings().model_dump_json()
    assert SECRET not in result.model_dump_json()
