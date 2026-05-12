"""Parametre taraması — detect_market_regime 0.00–0.99 (100 test)."""

from __future__ import annotations

import pytest
from super_otonom.analyzer import detect_market_regime

_H_VALUES = [round(i * 0.01, 2) for i in range(100)]


@pytest.mark.parametrize("h", _H_VALUES)
def test_param_detect_market_regime_sweep(h: float) -> None:
    r = detect_market_regime(h)
    assert r in ("TRENDING", "MEAN_REVERTING", "NOISY")
