"""Sınır değerleri ve ince edge — regime, OMEGA, merge, blend, gate (72)."""

from __future__ import annotations

import pytest
from super_otonom.ai_confidence_bridge import blend_omega_confidence
from super_otonom.analyzer import detect_market_regime
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.pre_trade_gate import gate_buy_signal_and_slots, merge_entry_notional

_HURST_FINE = [round(0.42 + i * 0.007, 4) for i in range(24)]

_VOL_CRASH_EDGE = [round(0.075 + (i - 6) * 0.002, 4) for i in range(12)]

_MERGE_EDGE = [
    (0.0, 1.0),
    (1e-12, 1e-12),
    (1e9, 1e9),
    (100.0, 0.0001),
    (0.0, None),
    (50.0, 50.0),
    (50.0, 49.999),
    (10.0, float("inf")),
    (0.0, 0.0),
    (1.0, -1.0),
    (2.5, 2.5),
    (999.0, 0.001),
]

_BLEND_EDGE = [
    (0.0, {}),
    (0.0, {"ml_score": 0.0}),
    (1.0, {"ml_score": 1.0}),
    (0.01, {"omega_ml_score": 0.99}),
    (0.99, {"ml_confidence": 0.01}),
    (0.5, {"ml_score": 0.5}),
    (0.45, {"ml_score": 0.55}),
    (0.55, {"ml_score": 0.45}),
    (0.25, {"omega_ml_confidence": 0.75}),
    (0.75, {"omega_ml_confidence": 0.25}),
    (0.33, {"ml_score": 0.66}),
    (0.66, {"ml_score": 0.33}),
]

_CONF_EDGE = [0.0, 0.01, 0.449, 0.45, 0.50001, 0.54, 0.55, 0.56, 0.9, 1.0, 1.1, -0.1]


@pytest.mark.parametrize("h", _HURST_FINE)
def test_wave2_boundary_hurst_regime_bucket(h: float) -> None:
    r = detect_market_regime(h)
    assert r in ("TRENDING", "MEAN_REVERTING", "NOISY")


@pytest.mark.parametrize("v", _VOL_CRASH_EDGE)
def test_wave2_boundary_omega_crash_vol_edge(v: float) -> None:
    oreg, _qm, _sf, adj, _ln = compute_omega_regime(
        {"regime": "TRENDING", "hurst": 0.58, "volatility": v, "flash_crash": False},
        55,
    )
    assert oreg in ("CRASH_RISK", "TRENDING", "RANGING")
    assert 0 <= adj <= 100


@pytest.mark.parametrize("tech,ob", _MERGE_EDGE)
def test_wave2_boundary_merge_notional_edges(tech: float, ob: object) -> None:
    n, src, blk = merge_entry_notional(tech, ob)
    assert n >= 0.0
    assert isinstance(src, str)


@pytest.mark.parametrize("base,payload", _BLEND_EDGE)
def test_wave2_boundary_blend_extremes(base: float, payload: dict) -> None:
    c, note = blend_omega_confidence(base, payload)
    assert 0.0 <= c <= 1.0
    assert note


@pytest.mark.parametrize("conf", _CONF_EDGE)
def test_wave2_boundary_gate_buy_confidence_sweep(conf: float) -> None:
    ok, code = gate_buy_signal_and_slots("BUY", 0, conf)
    assert isinstance(ok, bool)
    assert isinstance(code, str)
