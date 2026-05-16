"""
Boundary and behavioral tests for analyzer core functions.

Replaces test_sweep_45k_to_50k.py / test_sweep_ext_4500.py / test_sweep_matrix_500.py
(~50K parametrik tarama → 15 anlamlı sınır testi).
"""
from __future__ import annotations

import math

import pytest

from super_otonom.analyzer import _ema, _rsi, detect_market_regime

# ─── detect_market_regime ────────────────────────────────────────────────────
# Sınırlar: TRENDING > 0.55, MEAN_REVERTING < 0.45, aradaki alan NOISY


@pytest.mark.parametrize(
    "h,expected",
    [
        (1.0, "TRENDING"),          # uç üst değer
        (0.56, "TRENDING"),         # eşiğin hemen üstü
        (0.55, "NOISY"),            # tam sınır (> değil, ≤ → NOISY)
        (0.50, "NOISY"),            # orta nokta
        (0.45, "NOISY"),            # tam alt sınır (< değil, ≥ → NOISY)
        (0.449, "MEAN_REVERTING"),  # sınırın hemen altı
        (0.0, "MEAN_REVERTING"),    # uç alt değer
    ],
)
def test_regime_boundary(h: float, expected: str) -> None:
    """Her case farklı bir dal (branch) tetikler."""
    assert detect_market_regime(h) == expected


# ─── _ema ─────────────────────────────────────────────────────────────────────


def test_ema_empty_returns_zero() -> None:
    assert _ema([], 9) == 0.0


def test_ema_single_value_returns_itself() -> None:
    assert _ema([42.0], 9) == 42.0


def test_ema_constant_series_equals_constant() -> None:
    result = _ema([7.5] * 40, 9)
    assert abs(result - 7.5) < 1e-9


def test_ema_period_one_returns_last_value() -> None:
    # k = 2/(1+1) = 1.0 → her adımda önceki silinir → sonuç son değerdir
    assert _ema([1.0, 2.0, 3.0, 99.0], 1) == pytest.approx(99.0)


def test_ema_lags_on_rising_series() -> None:
    vals = [float(i) for i in range(50)]
    ema = _ema(vals, 9)
    assert ema < vals[-1], "EMA yükselen seride son değerin gerisinde kalmalı"
    assert ema > vals[0],  "EMA ilk değeri aşmış olmalı"


def test_ema_bounded_by_series_range() -> None:
    vals = [100.0 + i * 0.5 for i in range(40)]
    ema = _ema(vals, 14)
    assert min(vals) - 1e-9 <= ema <= max(vals) + 1e-9


# ─── _rsi ─────────────────────────────────────────────────────────────────────


def test_rsi_too_short_returns_50() -> None:
    # period+1 = 15 değer gerekir; 3 değerle → 50.0
    assert _rsi([1.0, 2.0, 3.0], period=14) == 50.0


def test_rsi_all_gains_returns_100() -> None:
    closes = [float(i) for i in range(1, 50)]  # monoton yükseliş
    assert _rsi(closes, period=14) == pytest.approx(100.0)


def test_rsi_all_losses_returns_zero() -> None:
    closes = [float(100 - i) for i in range(50)]  # monoton düşüş
    assert _rsi(closes, period=14) == pytest.approx(0.0)


def test_rsi_mixed_in_valid_range() -> None:
    closes = [50.0 + 5.0 * math.sin(i * 0.3) for i in range(50)]
    rsi = _rsi(closes, period=14)
    assert 0.0 <= rsi <= 100.0


def test_rsi_exactly_period_plus_one() -> None:
    # Tam olarak period+1 değer → sadece ilk hesaplama dönemi
    closes = [1.0] * 14 + [2.0]  # son fark = +1 (kazanç)
    rsi = _rsi(closes, period=14)
    assert 0.0 < rsi <= 100.0
