"""Entegrasyon: analyzer → OMEGA → blend; gate + merge + DecisionContext (100)."""

from __future__ import annotations

import pytest
from super_otonom.ai_confidence_bridge import blend_omega_confidence
from super_otonom.analyzer import MarketAnalyzer
from super_otonom.decision_context import DecisionContext
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.pre_trade_gate import gate_buy_signal_and_slots, merge_entry_notional

from tests.scaling.helpers import mk_series_uptrend

_HURST = (0.40, 0.52, 0.58, 0.62, 0.68)
_VOL = (0.01, 0.04, 0.09)
_BQ = (38, 48, 58, 72)


@pytest.mark.parametrize("mi", range(4))
@pytest.mark.parametrize("nj", range(5))
@pytest.mark.parametrize("pk", range(3))
def test_integration_analyze_omega_ml_blend_chain(mi: int, nj: int, pk: int) -> None:
    candles = mk_series_uptrend(48)
    r = MarketAnalyzer().analyze("INT/BULK", candles)
    r2 = {
        **r,
        "hurst": _HURST[nj],
        "volatility": _VOL[pk],
    }
    _oreg, _qm, _sf, adj, log_line = compute_omega_regime(r2, _BQ[mi])
    assert isinstance(adj, int)
    assert "[OMEGA-AI]" in log_line
    conf, note = blend_omega_confidence(0.48 + 0.01 * mi, {**r2, "ml_score": 0.35 + 0.1 * pk})
    assert 0.0 <= conf <= 1.0
    assert note


@pytest.mark.parametrize("si", range(10))
@pytest.mark.parametrize("sj", range(4))
def test_integration_gate_merge_decision_context(si: int, sj: int) -> None:
    sig = ("HOLD", "BUY", "SELL", "BUY")[sj]
    analysis = {
        "signal": sig,
        "regime": "TRENDING",
        "liquidity_ratio": 0.45 + si * 0.02,
        "entry_scale": "full",
    }
    dc = DecisionContext.start("BTC/USDT", si * 10 + sj, analysis)
    d = dc.to_dict()
    assert d["symbol"] == "BTC/USDT"
    assert d["analysis_signal"] == sig
    n, src, blk = merge_entry_notional(120.0 + si, 80.0 if sj % 2 == 0 else None)
    assert n >= 0.0
    assert isinstance(src, str)
    ok, code = gate_buy_signal_and_slots(sig, si % 3, 0.42 + si * 0.02)
    assert isinstance(ok, bool)
    assert isinstance(code, str)
