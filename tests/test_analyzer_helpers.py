"""Analyzer yardımcı fonksiyonları — veri/gösterge kenar durumları."""
from __future__ import annotations

import numpy as np
from super_otonom.analyzer import (
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
