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
