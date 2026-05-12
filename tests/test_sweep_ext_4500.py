"""
Ek geniş tarama: +4500 parametreli case (toplam 5000 test hedefi).
"""

from __future__ import annotations

import math
from typing import List

import pytest
from super_otonom.analyzer import _ema, _rsi, detect_market_regime


def _exp_regime(h: float) -> str:
    if h > 0.55:
        return "TRENDING"
    if h < 0.45:
        return "MEAN_REVERTING"
    return "NOISY"


# 1500: rejim, [0,1] aralığında ek örnekleme
@pytest.mark.parametrize("hurst", [i / 1499.0 for i in range(1500)])
def test_regime_dense_grid_1500(hurst: float) -> None:
    assert detect_market_regime(hurst) == _exp_regime(hurst)


# 1500: EMA, uzun seri 101…1600
@pytest.mark.parametrize("n", list(range(101, 1601)))
def test_ema_long_linear_1500(n: int) -> None:
    vals: List[float] = [float(i) for i in range(n)]
    out = _ema(vals, 9)
    assert math.isfinite(out)
    m = max(vals) if vals else 0.0
    assert 0.0 - 1e-6 <= out <= m + 1e-6


# 1500: RSI, uzun monoton seri 120…1619
@pytest.mark.parametrize("n", list(range(120, 1620)))
def test_rsi_long_bull_1500(n: int) -> None:
    closes = [10_000.0 + i * 0.15 for i in range(n)]
    r = _rsi(closes, 14)
    assert 0.0 < r <= 100.0
    assert r > 50.0
