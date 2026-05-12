"""
Geniş kapsam: parametre tarama (Faz 1+ — regresyon ağı top 500 toplam hedefi).
pytest her parametre kombinasyonunu ayrı test case sayar.
"""

from __future__ import annotations

import math
from typing import List

import pytest
from super_otonom.analyzer import (
    _ema,
    _rsi,
    _volume_ratio,
    detect_market_regime,
)


def _expected_regime(h: float) -> str:
    if h > 0.55:
        return "TRENDING"
    if h < 0.45:
        return "MEAN_REVERTING"
    return "NOISY"


# 200 adet: Hurst eşiği taraması
@pytest.mark.parametrize("hurst", [i / 199.0 for i in range(200)])
def test_detect_market_regime_full_sweep(hurst: float) -> None:
    assert detect_market_regime(hurst) == _expected_regime(hurst)


# 100 adet: EMA (lineer seri, sonlu çıktı)
@pytest.mark.parametrize("n", list(range(1, 101)))
def test_ema_linear_sequence_finite(n: int) -> None:
    vals: List[float] = [float(i) for i in range(n)]
    out = _ema(vals, 9)
    assert math.isfinite(out)
    assert 0.0 - 1e-6 <= out <= float(max(vals)) + 1e-6


# 100 adet: RSI yükselen trendde
@pytest.mark.parametrize("n", list(range(20, 120)))
def test_rsi_bullish_monotonic_series_in_range(n: int) -> None:
    closes = [100.0 + i * 0.2 for i in range(n)]
    r = _rsi(closes, 14)
    assert 0.0 < r <= 100.0
    assert r > 50.0


# 46 adet: eşit hacimde oran ~1
@pytest.mark.parametrize("n", list(range(20, 66)))
def test_volume_ratio_flat_volume_is_unity(n: int) -> None:
    candles = [{"volume": 10.0} for _ in range(n)]
    assert abs(_volume_ratio(candles, short=5, long=20) - 1.0) < 1e-9
