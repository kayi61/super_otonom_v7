"""PROMPT-3.1 — Funding Rate Alpha + derivatives_intel (Faz 18) entegrasyonu."""

from __future__ import annotations

import pytest
from super_otonom.derivatives_intel import analyze_derivatives_intel
from super_otonom.signals.funding_rate_alpha import (
    EXTREME_LONG,
    EXTREME_NEUTRAL,
    EXTREME_SHORT,
    Z_BLOCK_THRESHOLD,
    analyze_funding,
    classify_extremity,
    cross_exchange_analysis,
    cumulative_funding,
    funding_stats,
    predict_next_funding,
)

# ── funding_stats ─────────────────────────────────────────────────────────────


def test_funding_stats_basic() -> None:
    hist = [0.0001] * 89 + [0.0010]
    st = funding_stats(hist)
    assert st.n_samples == 90
    assert st.mean_30d == pytest.approx(sum(hist) / 90)
    assert st.std_30d > 0
    assert st.z_score > Z_BLOCK_THRESHOLD
    assert st.is_extreme is True


def test_funding_stats_uses_explicit_current() -> None:
    st = funding_stats([0.0001, 0.0002, 0.0003], current=0.0009)
    assert st.current == 0.0009
    assert st.z_score > 0  # current mean'in (0.0002) çok üstünde


def test_funding_stats_insufficient() -> None:
    st = funding_stats([])
    assert st.n_samples == 0 and st.z_score == 0.0
    st1 = funding_stats([0.0006])
    assert st1.z_score == 0.0 and st1.extremity == EXTREME_LONG


def test_funding_stats_zero_std() -> None:
    st = funding_stats([0.0001] * 10)
    assert st.std_30d == pytest.approx(0.0, abs=1e-12) and st.z_score == 0.0


def test_funding_stats_ignores_nan() -> None:
    st = funding_stats([0.0001, None, "bad", 0.0003])
    assert st.n_samples == 2


# ── classify_extremity ────────────────────────────────────────────────────────


def test_classify_extremity() -> None:
    assert classify_extremity(0.0006) == EXTREME_LONG   # > +0.05%
    assert classify_extremity(-0.0004) == EXTREME_SHORT  # < -0.03%
    assert classify_extremity(0.0001) == EXTREME_NEUTRAL


def test_classify_extremity_boundaries() -> None:
    assert classify_extremity(0.0005) == EXTREME_NEUTRAL   # tam eşik = nötr
    assert classify_extremity(0.00051) == EXTREME_LONG
    assert classify_extremity(-0.0003) == EXTREME_NEUTRAL
    assert classify_extremity(-0.00031) == EXTREME_SHORT


# ── cross_exchange_analysis ──────────────────────────────────────────────────


def test_cross_exchange_spread_arb() -> None:
    ce = cross_exchange_analysis({"binance": 0.0001, "bybit": 0.0008, "okx": 0.0002})
    assert ce.high_exchange == "bybit" and ce.low_exchange == "binance"
    assert ce.max_spread == pytest.approx(0.0007)
    assert ce.arb_opportunity is True


def test_cross_exchange_no_arb() -> None:
    ce = cross_exchange_analysis({"binance": 0.0001, "bybit": 0.0002}, arb_threshold=0.0003)
    assert ce.arb_opportunity is False


def test_cross_exchange_convergence_trend() -> None:
    converging = cross_exchange_analysis({"a": 0.0001, "b": 0.0003}, prev_spread=0.0005)
    assert converging.convergence_trend == "converging"
    diverging = cross_exchange_analysis({"a": 0.0001, "b": 0.0009}, prev_spread=0.0003)
    assert diverging.convergence_trend == "diverging"
    flat = cross_exchange_analysis({"a": 0.0001, "b": 0.0003}, prev_spread=0.0002)
    assert flat.convergence_trend == "flat"


def test_cross_exchange_insufficient() -> None:
    ce = cross_exchange_analysis({"binance": 0.0001})
    assert ce.arb_opportunity is False and ce.convergence_trend == "unknown"


# ── predict_next_funding ──────────────────────────────────────────────────────


def test_predict_imbalance() -> None:
    assert predict_next_funding(0.0001, order_book_imbalance=0.5) == pytest.approx(0.0003)
    assert predict_next_funding(0.0001, order_book_imbalance=-0.5) == pytest.approx(-0.0001)


def test_predict_imbalance_clamped() -> None:
    # imbalance > 1 → 1'e clamp
    assert predict_next_funding(0.0, order_book_imbalance=5.0) == pytest.approx(0.0004)


def test_predict_with_premium() -> None:
    p = predict_next_funding(0.0002, order_book_imbalance=0.0, premium_pct=0.001)
    # 0.6*0.0002 + 0.4*0.001
    assert p == pytest.approx(0.6 * 0.0002 + 0.4 * 0.001)


# ── cumulative_funding ────────────────────────────────────────────────────────


def test_cumulative_funding() -> None:
    hist = [0.0001] * 90  # 30 gün
    cum = cumulative_funding(hist, notional=1_000_000)
    assert cum.cum_7d == pytest.approx(0.0001 * 21)   # 3/gün * 7
    assert cum.cum_30d == pytest.approx(0.0001 * 90)
    assert cum.long_carry_cost_7d == pytest.approx(0.0001 * 21 * 1_000_000)
    assert cum.short_carry_cost_7d == pytest.approx(-cum.long_carry_cost_7d)


def test_cumulative_negative_funding_long_benefit() -> None:
    cum = cumulative_funding([-0.0002] * 21, notional=1_000_000)
    assert cum.long_carry_cost_7d < 0   # negatif funding → long kazanır
    assert cum.short_carry_cost_7d > 0


# ── analyze_funding ───────────────────────────────────────────────────────────


def test_analyze_overcrowded_long_short_opportunity() -> None:
    hist = [0.0001] * 89 + [0.0009]
    fa = analyze_funding(hist)
    assert fa.stats.extremity == EXTREME_LONG
    assert fa.alpha_bias < 0  # short fırsatı
    assert fa.block is True
    assert any("short fırsatı" in r for r in fa.reasons)


def test_analyze_overcrowded_short_long_squeeze() -> None:
    hist = [0.0001] * 89 + [-0.0008]
    fa = analyze_funding(hist)
    assert fa.stats.extremity == EXTREME_SHORT
    assert fa.alpha_bias > 0  # long squeeze (bullish)
    assert any("long squeeze" in r for r in fa.reasons)


def test_analyze_neutral_no_block() -> None:
    hist = [0.0001] * 90
    fa = analyze_funding(hist)
    assert fa.block is False
    assert fa.alpha_bias == 0.0


def test_analyze_arb_reason() -> None:
    hist = [0.0001] * 90
    fa = analyze_funding(hist, per_exchange={"binance": 0.0001, "bybit": 0.0008})
    assert any("arb" in r for r in fa.reasons)


def test_analyze_to_dict() -> None:
    hist = [0.0001] * 89 + [0.0009]
    fa = analyze_funding(hist, per_exchange={"a": 0.0001, "b": 0.0006},
                         order_book_imbalance=0.2, notional=1e6)
    d = fa.to_dict()
    assert "funding_z_score" in d and "funding_predicted_next" in d
    assert "funding_cross_exchange" in d and "funding_cum_7d" in d


# ── derivatives_intel (Faz 18) entegrasyonu ──────────────────────────────────


def test_faz18_funding_block_on_extreme_zscore() -> None:
    hist = [0.0001] * 89 + [0.0010]
    data = {"funding_rate": 0.0010, "funding_history": hist}
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    assert out["trade_permission"] == "BLOCK"
    fa = out["derivatives"]["funding_analysis"]
    assert fa["funding_block"] is True
    assert fa["funding_z_score"] > Z_BLOCK_THRESHOLD


def test_faz18_funding_analysis_fields() -> None:
    hist = [0.0001] * 90
    data = {
        "funding_rate": 0.0001,
        "funding_history": hist,
        "cross_exchange_funding": {"binance": 0.0002, "bybit": 0.0008, "okx": 0.0003},
        "order_book_imbalance": 0.4,
        "position_notional": 1_000_000,
    }
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    fa = out["derivatives"]["funding_analysis"]
    assert "funding_predicted_next" in fa
    assert fa["funding_cross_exchange"]["arb_opportunity"] is True
    assert fa["funding_long_carry_7d"] == pytest.approx(0.0001 * 21 * 1_000_000)


def test_faz18_backward_compat_no_history() -> None:
    out = analyze_derivatives_intel("BTCUSDT", {"funding_rate": 0.0001}, {"signal": "BUY"})
    assert "funding_analysis" not in out["derivatives"]


def test_faz18_cross_exchange_only() -> None:
    # funding_history yok ama cross_exchange var → analiz çalışır
    data = {"funding_rate": 0.0003, "cross_exchange_funding": {"binance": 0.0001, "bybit": 0.0008}}
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    assert "funding_analysis" in out["derivatives"]


def test_faz18_funding_graceful_bad_history() -> None:
    data = {"funding_rate": 0.0001, "funding_history": "not-a-list"}
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    # bozuk history → funding_analysis eklenmez, çıktı sözleşmesi korunur
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
    assert "funding_analysis" not in out["derivatives"]
