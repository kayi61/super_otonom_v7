"""Analyzer yardımcı fonksiyonları — veri/gösterge kenar durumları."""

from __future__ import annotations

from unittest import mock

import numpy as np
import pytest
from super_otonom.analyzer import (
    MarketAnalyzer,
    _atr,
    _bollinger,
    _calculate_hurst,
    _ema,
    _falling_last_two_closes,
    _rising_last_two_closes,
    _rsi,
    _volume_ratio,
)


def test_ema_empty_and_simple() -> None:
    assert _ema([], 9) == 0.0
    assert _ema([10.0], 9) == 10.0
    seq = [float(i) for i in range(1, 30)]
    assert _ema(seq, 9) > seq[0]


def test_rsi_short_series_returns_neutral() -> None:
    assert _rsi([100.0, 101.0], 14) == 50.0


def test_rsi_trending_up_high() -> None:
    closes = [100.0 + i * 0.5 for i in range(20)]
    r = _rsi(closes, 14)
    assert r > 50.0


def test_bollinger_short_window() -> None:
    mid, up, lo, pb = _bollinger([1.0, 2.0], period=20)
    assert mid == 2.0
    assert pb == 0.5


def test_atr_minimal_candles() -> None:
    c = [{"high": 110, "low": 90, "close": 100}]
    assert _atr(c, 14) == 0.01


def test_volume_ratio_insufficient_length() -> None:
    candles = [{"volume": 1.0}] * 10
    assert _volume_ratio(candles, short=5, long=20) == 1.0


def test_hurst_short_series_returns_half() -> None:
    assert _calculate_hurst([1.0] * 10) == 0.5


def test_rising_falling_last_two() -> None:
    assert _rising_last_two_closes([1, 2, 3]) is True
    assert _falling_last_two_closes([3, 2, 1]) is True
    assert _rising_last_two_closes([3, 2]) is False


def test_hurst_reasonable_range_on_synthetic() -> None:
    rng = np.random.default_rng(42)
    ts = (np.cumsum(rng.normal(0, 1, 50)) + 100).tolist()
    h = _calculate_hurst(ts)
    assert 0.0 <= h <= 1.0


def test_rsi_initial_window_all_down_moves_accumulates_losses() -> None:
    """59: ilk pencerede negatif kapanışlar."""
    closes = [100.0 - i * 0.3 for i in range(20)]
    r = _rsi(closes, 14)
    assert r < 50.0


def test_rsi_avg_loss_zero_returns_100() -> None:
    """70-73: düz yükseliş → RS çok büyük."""
    closes = [100.0 + i * 0.1 for i in range(20)]
    r = _rsi(closes, 14)
    assert r == 100.0


@pytest.mark.filterwarnings("ignore:divide by zero encountered in log:RuntimeWarning")
def test_calculate_hurst_exception_returns_half() -> None:
    """Hurst min uzunluk sonrası polyfit hatası → nötr."""
    ts = [float(i) for i in range(55)]
    with mock.patch("super_otonom.analyzer.np.polyfit", side_effect=RuntimeError("x")):
        assert _calculate_hurst(ts) == 0.5


def test_apply_liquidity_context_bad_ob_safe() -> None:
    """218-221."""
    a: dict = {}
    MarketAnalyzer.apply_liquidity_context(a, object(), 100.0)
    assert a["liquidity_ratio"] is None
    assert a["entry_scale"] == "unknown"


def test_analyze_v5_1_mtf_filters_sell_when_4h_up() -> None:
    """297-303: 1H SELL + 4H UP → HOLD."""
    c4h = [{"close": float(5_000 + i * 12)} for i in range(25)]
    c1h = [{"close": float(100 + i)} for i in range(50)]
    a = MarketAnalyzer()
    stub = {
        "signal": "SELL",
        "futures_side": "SHORT",
        "reason": "r",
        "regime_reason": "",
    }
    with mock.patch.object(a, "analyze", return_value=stub):
        r = a.analyze_v5_1("X", c1h, c4h)
    assert r["high_tf_trend"] == "UP"
    assert r["mtf_filtered"] is True
    assert r["signal"] == "HOLD"


def test_analyze_v5_1_mtf_ok_debug_branch(caplog) -> None:
    """311-320: filtre yok → log.debug."""
    c4h = [{"close": float(200 + i * 3)} for i in range(25)]
    c1h = [{"close": float(80 + i)} for i in range(50)]
    a = MarketAnalyzer()
    stub = {
        "signal": "HOLD",
        "futures_side": "FLAT",
        "reason": "",
        "regime_reason": "",
    }
    caplog.set_level("DEBUG", logger="super_otonom.analyzer")
    with mock.patch.object(a, "analyze", return_value=stub):
        r = a.analyze_v5_1("Z", c1h, c4h)
    assert r["mtf_filtered"] is False
    assert any("MTF OK" in r.message for r in caplog.records)


def test_analyze_market_state_mean_reverting_and_sideways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """358-362: MEAN_REVERTING / SIDEWAYS / NEUTRAL."""
    flat = [
        {"open": 100.0, "high": 100.02, "low": 99.98, "close": 100.0, "volume": 1.0}
        for _ in range(50)
    ]

    monkeypatch.setattr("super_otonom.analyzer._calculate_hurst", lambda ts: 0.40)
    monkeypatch.setattr("super_otonom.analyzer._rsi", lambda c, p=14: 50.0)
    r1 = MarketAnalyzer().analyze("S", flat)
    assert r1["market_state"] == "MEAN_REVERTING"

    monkeypatch.setattr("super_otonom.analyzer._calculate_hurst", lambda ts: 0.50)
    monkeypatch.setattr("super_otonom.analyzer._atr", lambda c, p=14: 0.00001)
    r2 = MarketAnalyzer().analyze("S", flat)
    assert r2["market_state"] == "SIDEWAYS"

    monkeypatch.setattr("super_otonom.analyzer._rsi", lambda c, p=14: 75.0)
    r3 = MarketAnalyzer().analyze("S", flat)
    assert r3["market_state"] == "NEUTRAL"


def test_analyze_regime_mean_reverting_hold_copy() -> None:
    """377-380."""
    flat = [
        {"open": 100.0, "high": 100.02, "low": 99.98, "close": 100.0, "volume": 1.0}
        for _ in range(50)
    ]

    with mock.patch("super_otonom.analyzer._calculate_hurst", return_value=0.40):
        r = MarketAnalyzer().analyze("S", flat)
    assert r["regime"] == "MEAN_REVERTING"
    assert r["signal"] == "HOLD"
    assert "MEAN_REVERTING" in (r.get("regime_reason") or "")


def test_score_signal_quality_and_summary() -> None:
    """424-438."""
    a = MarketAnalyzer()
    assert "v5.1" in a.summary()
    analysis = {
        "signal": "BUY",
        "hurst": 0.62,
        "regime": "TRENDING",
        "volatility": 0.025,
        "liquidity_ratio": 0.8,
        "mtf_filtered": False,
        "high_tf_trend": "UP",
    }
    out = MarketAnalyzer.score_signal_quality(analysis)
    assert isinstance(out, tuple) and len(out) == 4
