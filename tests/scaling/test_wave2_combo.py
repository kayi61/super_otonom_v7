"""Çok modüllü kombinasyonlar + health formatları (74)."""
from __future__ import annotations

import pytest
from super_otonom.analyzer import MarketAnalyzer
from super_otonom.decision_context import DecisionContext
from super_otonom.health_summary import format_durum_line, format_tick_health
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.position_sizer import PositionSizer
from super_otonom.risk_manager import RiskManager

from tests.scaling.helpers import mk_series_uptrend


@pytest.mark.parametrize("i", range(5))
@pytest.mark.parametrize("j", range(5))
def test_wave2_combo_risk_omega_feedback_then_regime(i: int, j: int) -> None:
    rm = RiskManager(20_000.0)
    rm.record_omega_trade_outcome(-80.0 + i * 15.0)
    rm.record_omega_trade_outcome(25.0 - j * 5.0)
    q = rm.get_omega_effective_qmin(35 + j)
    assert 0 <= q <= 90
    candles = mk_series_uptrend(42)
    ar = MarketAnalyzer().analyze("C/X", candles)
    oreg, _qm, sf, adj, lg = compute_omega_regime({**ar, "hurst": 0.52 + i * 0.01}, 48 + j)
    assert oreg
    assert isinstance(sf, float)
    assert isinstance(adj, int)
    assert "[OMEGA-AI]" in lg


@pytest.mark.parametrize("ob", (None, 0.0, 0.001, 0.8, 1.0, 10_000.0))
@pytest.mark.parametrize("tn", (0.0, 0.001, 1.0, 99.0, 5000.0))
def test_wave2_combo_liquidity_context_matrix(ob: float | None, tn: float) -> None:
    analysis: dict = {"symbol": "X"}
    MarketAnalyzer.apply_liquidity_context(analysis, ob, tn)
    assert "entry_scale" in analysis
    assert "liquidity_ratio" in analysis


@pytest.mark.parametrize("k", range(25))
def test_wave2_combo_health_format_variants(k: int) -> None:
    st = {
        "equity": 1000.0 + k,
        "total_pnl": -10.0 * (k % 5),
        "pnl_pct": 0.05 * (k % 20),
        "peak_drawdown_pct": float(k % 15),
        "exposure_pct": float(k % 40),
        "total_trades": k * 3,
        "emergency_stop": bool(k % 11 == 0),
        "emergency_reason": "" if k % 3 else "test",
        "emergency_code_line": f"CODE{k}" if k % 4 == 0 else "—",
        "hard_limits": {
            "orders_in_window": k % 5,
            "order_limit": 4 + k % 3,
            "window_sec": 1.0 + 0.1 * (k % 7),
        },
        "rate_limit": {"rl_streak": k % 4, "rl_trip": 5},
    }
    line = format_durum_line(st)
    assert "eq=" in line and "Fuses" in line

    dctx = {
        "symbol": f"S{k}",
        "tick_id": k,
        "entry_scale": "full" if k % 2 == 0 else "scaled",
        "liquidity_ratio": None if k % 5 == 0 else 0.25 + (k % 10) * 0.05,
        "final_signal": ("BUY", "HOLD", "SELL")[k % 3],
        "signal_quality": 40 + k % 50,
        "adj_signal_quality": 35 + k % 55,
        "effective_quality_min": 45,
        "omega_ai_log": "[OMEGA-AI] X" * (1 + k % 2),
        "emergency_code": "EMERGENCY_STOP:x" if k % 13 == 0 else None,
    }
    th = format_tick_health(st, dctx)
    assert "[OK]" in th or "[HALT]" in th


@pytest.mark.parametrize("eq", (100.0, 1000.0, 50_000.0))
@pytest.mark.parametrize("vol", (0.0001, 0.02, 0.15))
def test_wave2_combo_position_sizer_calculate(eq: float, vol: float) -> None:
    s = PositionSizer(max_position_pct=0.1, min_notional=5.0)
    sz = s.calculate("ETH/USDT", eq, volatility=vol, ai_conf=0.55 + vol)
    assert isinstance(sz, float)
    assert sz >= 0.0


@pytest.mark.parametrize("n", range(4))
def test_wave2_combo_decision_context_trace_serialization(n: int) -> None:
    dc = DecisionContext(symbol="Z", tick_id=n)
    dc.add_trace("risk", f"ok_{n}")
    dc.add_trace("entry", "probe")
    d = dc.to_dict()
    assert len(d["trace"]) == 2
    assert d["symbol"] == "Z"
