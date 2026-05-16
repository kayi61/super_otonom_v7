"""Audit 4 — survivorship bias: disclosure, çok sembol, point-in-time takvim."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest
from super_otonom.backtest_universe import (
    SymbolScheduleEntry,
    filter_candles_by_schedule,
    parse_symbol_list,
    run_universe_backtest,
    survivorship_disclosure,
)
from super_otonom.edge_evidence import main as edge_main
from super_otonom.survivorship_audit import audit_survivorship_claims
from super_otonom.survivorship_audit import main as surv_audit_main

pytestmark = pytest.mark.fastrun


def _candles(n: int, ts0: float = 1_700_000_000_000.0, step_ms: float = 300_000.0) -> list[dict]:
    out: list[dict] = []
    p = 100.0
    for i in range(n):
        c = p * 1.0001
        out.append(
            {
                "timestamp": ts0 + i * step_ms,
                "open": p,
                "high": c * 1.001,
                "low": c * 0.999,
                "close": c,
                "volume": 1000.0,
            }
        )
        p = c
    return out


def test_parse_symbols() -> None:
    assert parse_symbol_list("BTC/USDT, ETH/USDT") == ["BTC/USDT", "ETH/USDT"]


def test_disclosure_single_not_institutional() -> None:
    d = survivorship_disclosure(
        symbols=["BTC/USDT"],
        has_point_in_time_schedule=False,
        data_source="synthetic",
    )
    assert d["institutional_universe_claim_allowed"] is False
    assert "single_symbol_chain" in d["limitations"]


def test_disclosure_with_schedule_two_symbols() -> None:
    d = survivorship_disclosure(
        symbols=["BTC/USDT", "ETH/USDT"],
        has_point_in_time_schedule=True,
        data_source="ccxt",
    )
    assert d["survivorship_bias_controlled"] is True
    assert d["institutional_universe_claim_allowed"] is True


def test_filter_candles_by_schedule() -> None:
    candles = _candles(10, ts0=1000.0, step_ms=100.0)
    entry = SymbolScheduleEntry("BTC/USDT", active_from_ms=1200.0, active_until_ms=1500.0)
    trimmed = filter_candles_by_schedule(candles, entry)
    assert 2 <= len(trimmed) <= 4


def test_run_universe_two_symbols(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.bot_engine as bemod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bemod, "_STATE_FILE", str(tmp_path / "st.json"))
    monkeypatch.setattr(bemod, "_TRADE_LOG_FILE", str(tmp_path / "tr.log"))

    cmap = {
        "BTC/USDT": _candles(50),
        "ETH/USDT": _candles(50),
    }
    uni = run_universe_backtest(
        cmap,
        data_source="synthetic",
        capital_per_symbol=5_000.0,
        min_bars=35,
        timeframe="5m",
        exec_seed=1,
    )
    assert len(uni.per_symbol) == 2
    assert uni.disclosure["symbol_count"] == 2


def test_survivorship_audit_repo_clean() -> None:
    assert audit_survivorship_claims() == []


def test_survivorship_audit_cli() -> None:
    assert surv_audit_main([]) == 0


def test_synthetic_aligns_to_delist_schedule_window() -> None:
    from super_otonom.backtest_universe import SymbolScheduleEntry
    from super_otonom.edge_evidence import _synthetic_ohlcv_rows
    from super_otonom.exchange_async import ohlcv_to_candles

    entry = SymbolScheduleEntry("OCEAN/USDT", active_from_ms=1_600_000_000_000.0, active_until_ms=1_700_000_000_000.0)
    raw = _synthetic_ohlcv_rows("OCEAN/USDT", 120, 7, bar_ms=300_000, schedule_entry=entry)
    candles = ohlcv_to_candles(raw)
    assert len(candles) >= 80
    assert float(candles[-1]["timestamp"]) <= 1_700_000_000_000.0


def test_edge_evidence_multi_symbol_json(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.bot_engine as bemod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bemod, "_STATE_FILE", str(tmp_path / "s2.json"))
    monkeypatch.setattr(bemod, "_TRADE_LOG_FILE", str(tmp_path / "t2.log"))

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = edge_main(
            [
                "--source",
                "synthetic",
                "--symbols",
                "BTC/USDT,ETH/USDT",
                "--timeframe",
                "5m",
                "--limit",
                "120",
                "--no-wfa",
                "--json",
            ]
        )
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["survivorship_disclosure"]["institutional_universe_claim_allowed"] is False
    assert payload["universe"] is not None
    assert len(payload["universe"]["per_symbol"]) == 2
