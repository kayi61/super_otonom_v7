"""
+45.000 parametreli case: toplam 50.000 test hedefi (mevcut 5k + 45k).
"""
from __future__ import annotations

import math
from typing import List

import pytest
from super_otonom.analyzer import _ema, _rsi, detect_market_regime


def _reg(h: float) -> str:
    if h > 0.55:
        return "TRENDING"
    if h < 0.45:
        return "MEAN_REVERTING"
    return "NOISY"


# 15.000: rejim, daha sık ızgara
@pytest.mark.parametrize("h", [i / 14_999.0 for i in range(15_000)])
def test_regime_grid_15k(h: float) -> None:
    assert detect_market_regime(h) == _reg(h)


# 15.000: EMA, seri uzunluk 1601…16600 (end exclusive 16601)
@pytest.mark.parametrize("n", list(range(1601, 16_601)))
def test_ema_block_15k(n: int) -> None:
    vals: List[float] = [float(i) for i in range(n)]
    out = _ema(vals, 9)
    assert math.isfinite(out)
    assert out <= max(vals) + 1e-6


# 15.000: RSI, uzun monoton seri (uzunluk 1620…3159 — 15000 değer)
@pytest.mark.parametrize("n", list(range(1620, 16_620)))
def test_rsi_block_15k(n: int) -> None:
    c = [10_000.0 + j * 0.12 for j in range(n)]
    r = _rsi(c, 14)
    assert 0.0 < r <= 100.0
    assert r > 50.0
