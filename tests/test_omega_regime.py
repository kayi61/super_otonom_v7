from __future__ import annotations

from super_otonom.ai_confidence_bridge import blend_omega_confidence
from super_otonom.decision_context import DecisionContext
from super_otonom.omega_regime import compute_omega_regime


def test_blend_no_ml_unchanged() -> None:
    c, n = blend_omega_confidence(0.6, {})
    assert abs(c - 0.6) < 0.01
    assert n == "no_external_ml"


def test_blend_with_ml() -> None:
    c, n = blend_omega_confidence(0.5, {"ml_score": 0.9})
    assert c > 0.5
    assert "ml" in n


def test_blend_invalid_ml_score() -> None:
    c, n = blend_omega_confidence(0.4, {"ml_score": object()})
    assert n == "ml_score_invalid"
    assert 0.0 <= c <= 1.0


def test_decision_context_liquidity_ratio_invalid() -> None:
    d = DecisionContext.start("S", 0, {"liquidity_ratio": "notnum"})
    assert d.liquidity_ratio is None


def test_crash_regime_squash() -> None:
    a = {"regime": "TRENDING", "hurst": 0.6, "volatility": 0.2, "flash_crash": True}
    r, m, s, adj, _ = compute_omega_regime(a, 80)
    assert r == "CRASH_RISK"
    assert adj < 80


def test_omega_trending_high_q_sf_boost() -> None:
    a = {"regime": "TRENDING", "hurst": 0.6, "volatility": 0.02, "flash_crash": False}
    r, m, s, _adj, _ = compute_omega_regime(a, 95)
    assert r in ("TRENDING", "RANGING", "CRASH_RISK")


def test_omega_else_branch() -> None:
    # vol yüksekse CRASH_RISK dalar; else dalı için vol < OMEGA_CRASH_VOL olmalı
    a = {"regime": "RANDOM", "hurst": 0.7, "volatility": 0.02, "flash_crash": False}
    r, m, s, _adj, _ = compute_omega_regime(a, 50)
    assert r == "RANGING"


def test_omega_base_quality_45_caps_sf() -> None:
    a = {"regime": "MEAN_REVERTING", "hurst": 0.5, "volatility": 0.01, "flash_crash": False}
    _r, _m, s, _a, _ = compute_omega_regime(a, 45)
    assert 0.2 <= s <= 1.2
