"""Signal quality scorer — 0-100 ağırlık."""
from __future__ import annotations

from super_otonom.signal_quality_scorer import compute_signal_quality


def _base_analysis(**kw):
    a = {
        "signal": "BUY",
        "hurst": 0.62,
        "regime": "TRENDING",
        "volatility": 0.025,
        "liquidity_ratio": 0.8,
        "mtf_filtered": False,
        "high_tf_trend": "UP",
    }
    a.update(kw)
    return a


def test_quality_respects_trending_hurst() -> None:
    sc, pr, comp, _ = compute_signal_quality(_base_analysis())
    assert 0 <= sc <= 100
    assert "hurst" in comp


def test_mtf_filtered_hurts_score() -> None:
    a = _base_analysis(mtf_filtered=True)
    s_hi, _, _, _ = compute_signal_quality(_base_analysis(mtf_filtered=False))
    s_lo, _, _, _ = compute_signal_quality(a)
    assert s_lo < s_hi


def test_low_liquidity_penalty() -> None:
    sc1, _, _, _ = compute_signal_quality(_base_analysis(liquidity_ratio=0.9))
    sc2, p2, _, _ = compute_signal_quality(_base_analysis(liquidity_ratio=0.05))
    assert sc2 < sc1
    assert any("liquidity" in p for p in p2)
