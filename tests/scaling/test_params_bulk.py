"""
Regime sınır testleri.

Eskiden: 100-case parametrik tarama (0.00–0.99 arası _tüm_ değerler).
Şimdi: her dalı (branch) tam olarak bir kez çalıştıran 7 kesin test.
"""
from __future__ import annotations

import pytest
from super_otonom.analyzer import detect_market_regime


@pytest.mark.parametrize(
    "h,expected",
    [
        (1.0,   "TRENDING"),          # üst uç
        (0.56,  "TRENDING"),          # eşiğin hemen üstü
        (0.55,  "NOISY"),             # tam üst sınır (> 0.55 değil)
        (0.50,  "NOISY"),             # orta bölge
        (0.45,  "NOISY"),             # tam alt sınır (< 0.45 değil)
        (0.449, "MEAN_REVERTING"),    # sınırın hemen altı
        (0.0,   "MEAN_REVERTING"),    # alt uç
    ],
)
def test_regime_boundary(h: float, expected: str) -> None:
    """Her parametrize case farklı bir kod dalını (branch) tetikler."""
    assert detect_market_regime(h) == expected
