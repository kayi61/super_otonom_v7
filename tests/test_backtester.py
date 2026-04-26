"""backtester — rapor ve kısa koşum."""
from __future__ import annotations

import numpy as np
import super_otonom.bot_engine as bemod
from super_otonom.backtester import (
    BacktestReport,
    _compute_max_drawdown_pct,
    build_backtest_report,
    candles_from_ccxt_ohlcv,
    run_backtest,
    run_backtest_async,
)
from super_otonom.bot_engine import BotEngine


def _synthetic_candles(n: int, start: float = 100.0) -> list[dict]:
    out = []
    ts = 1_700_000_000_000
    p = start
    for i in range(n):
        o = p
        c = p * (1.0 + 0.001 * (1 if i % 5 != 0 else -1))
        h = max(o, c) * 1.002
        lo = min(o, c) * 0.998
        out.append(
            {
                "timestamp": float(ts + i * 300_000),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": 1000.0 + float(i),
            }
        )
        p = c
    return out


def test_build_backtest_report_short_curve() -> None:
    e = BotEngine(1000.0, paper=True)
    r = build_backtest_report(e, [1000.0, 1005.0], 1000.0, bars_simulated=2)
    assert isinstance(r, BacktestReport)
    assert r.bars_simulated == 2
    assert r.n_trades == 0


def test_build_backtest_report_sharpe_and_dd() -> None:
    e = BotEngine(10_000.0, paper=True)
    eq = list(10_000.0 + np.cumsum(np.random.default_rng(42).normal(0, 50, 80)))
    r = build_backtest_report(e, eq, 10_000.0, bars_simulated=len(eq), periods_per_year=252.0)
    assert r.max_drawdown_pct >= 0.0
    assert isinstance(r.sharpe_ratio, float)


def test_run_backtest_minimal(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bemod, "_STATE_FILE", str(tmp_path / "st.json"))
    monkeypatch.setattr(bemod, "_TRADE_LOG_FILE", str(tmp_path / "tr.log"))
    candles = _synthetic_candles(50)
    r = run_backtest(candles, symbol="BTC/USDT", initial_capital=50_000.0, min_bars=35)
    assert r.bars_simulated == 15
    assert r.final_equity > 0


def test_run_backtest_async_too_few_bars(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bemod, "_STATE_FILE", str(tmp_path / "s2.json"))
    monkeypatch.setattr(bemod, "_TRADE_LOG_FILE", str(tmp_path / "t2.log"))
    import asyncio

    r = asyncio.run(
        run_backtest_async(
            _synthetic_candles(10), initial_capital=1000.0, min_bars=35
        )
    )
    assert r.bars_simulated == 0


def test_max_drawdown_single_point() -> None:
    assert _compute_max_drawdown_pct(np.array([100.0])) == 0.0


def test_candles_from_ccxt_ohlcv() -> None:
    raw = [[1.0, 10.0, 11.0, 9.0, 10.5, 100.0]]
    c = candles_from_ccxt_ohlcv(raw)
    assert len(c) == 1
    assert c[0]["close"] == 10.5
