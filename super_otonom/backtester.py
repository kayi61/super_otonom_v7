"""
Geçmiş OHLCV ile strateji geri testi (paper BotEngine + MarketAnalyzer).

Çıktı: Sharpe oranı, maksimum drawdown %, kazanma oranı, toplam getiri.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from super_otonom.analyzer import MarketAnalyzer
from super_otonom.bot_engine import BotEngine

log = logging.getLogger("super_otonom.backtester")


@dataclass
class BacktestReport:
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_return_pct: float
    n_trades: int
    final_equity: float
    bars_simulated: int


def _compute_sharpe(returns: np.ndarray, periods_per_year: float) -> float:
    if returns.size < 2:
        return 0.0
    std = float(np.std(returns))
    if std < 1e-12:
        return 0.0
    return float(np.mean(returns) / std * np.sqrt(periods_per_year))


def _compute_max_drawdown_pct(equity: np.ndarray) -> float:
    if equity.size < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / (peak + 1e-9) * 100.0
    return float(np.max(dd))


def build_backtest_report(
    engine: BotEngine,
    equity_curve: List[float],
    initial_capital: float,
    *,
    bars_simulated: int,
    periods_per_year: float = 252.0 * 24.0 * 12.0,
) -> BacktestReport:
    """Equity serisinden ve engine.trade_log üzerinden rapor üret."""
    if len(equity_curve) < 2:
        fe = float(engine.equity)
        tr = (fe - initial_capital) / (initial_capital + 1e-9) * 100.0
        return BacktestReport(
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate=0.0,
            total_return_pct=round(tr, 2),
            n_trades=len(getattr(engine, "trade_log", []) or []),
            final_equity=round(fe, 2),
            bars_simulated=bars_simulated,
        )

    eq = np.asarray(equity_curve, dtype=float)
    ret = np.diff(eq) / (eq[:-1] + 1e-9)
    sharpe = _compute_sharpe(ret, periods_per_year)
    max_dd = _compute_max_drawdown_pct(eq)

    trades = getattr(engine, "trade_log", []) or []
    wins = [t for t in trades if float(t.get("pnl", 0.0)) > 0.0]
    win_rate = (len(wins) / len(trades)) if trades else 0.0
    total_ret = (float(eq[-1]) - initial_capital) / (initial_capital + 1e-9) * 100.0

    return BacktestReport(
        sharpe_ratio=round(sharpe, 4),
        max_drawdown_pct=round(max_dd, 2),
        win_rate=round(win_rate, 4),
        total_return_pct=round(total_ret, 2),
        n_trades=len(trades),
        final_equity=round(float(eq[-1]), 2),
        bars_simulated=bars_simulated,
    )


async def run_backtest_async(
    candles: List[Dict[str, Any]],
    *,
    symbol: str = "BTC/USDT",
    initial_capital: float = 10_000.0,
    min_bars: int = 35,
    max_window: int = 150,
    periods_per_year: float = 252.0 * 24.0 * 12.0,
    final_signal_histo: Optional[Dict[str, int]] = None,
) -> BacktestReport:
    """
    Mum listesi üzerinde sırayla analyze + engine.tick çalıştırır (paper).

    `candles`: analyzer/tick ile uyumlu dict listesi (open, high, low, close, volume, timestamp).

    ``final_signal_histo``: verilirse her adımda ``out["final_signal"]`` sayımı bu dict’e eklenir
    (gözlem; davranışı değiştirmez). Varsayılan ``None``.
    """
    if len(candles) <= min_bars:
        log.warning("backtest: yetersiz mum (need > min_bars=%s)", min_bars)
        eng = BotEngine(initial_capital, paper=True)
        return build_backtest_report(
            eng, [], initial_capital, bars_simulated=0, periods_per_year=periods_per_year
        )

    engine = BotEngine(initial_capital, paper=True)
    analyzer = MarketAnalyzer()
    equity_curve: List[float] = []
    n_steps = 0

    for i in range(min_bars, len(candles)):
        start = max(0, i - max_window + 1)
        window = candles[start : i + 1]
        analysis = analyzer.analyze(symbol, window)
        analysis.setdefault("strategist", "trend")
        out = await engine.tick(symbol, analysis, window)
        if final_signal_histo is not None:
            fs = str(out.get("final_signal", "HOLD"))
            final_signal_histo[fs] = final_signal_histo.get(fs, 0) + 1
        equity_curve.append(float(engine.equity))
        n_steps += 1

    return build_backtest_report(
        engine,
        equity_curve,
        initial_capital,
        bars_simulated=n_steps,
        periods_per_year=periods_per_year,
    )


def run_backtest(
    candles: List[Dict[str, Any]],
    **kwargs: Any,
) -> BacktestReport:
    """Senkron sarmalayıcı."""
    return asyncio.run(run_backtest_async(candles, **kwargs))


def candles_from_ccxt_ohlcv(raw: List[List[float]]) -> List[Dict[str, Any]]:
    """[[ts,o,h,l,c,v], ...] → analyzer mum dict listesi."""
    from super_otonom.exchange_async import ohlcv_to_candles

    return ohlcv_to_candles(raw)
