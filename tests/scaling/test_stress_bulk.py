"""Hafif stres — tekrarlı analyze, büyük mum setleri (6×10 = 60)."""
from __future__ import annotations

import pytest
from super_otonom.analyzer import MarketAnalyzer

from tests.scaling.helpers import mk_series_uptrend

_SIZES = (80, 120, 200, 350, 500, 750)


@pytest.mark.parametrize("n", _SIZES)
@pytest.mark.parametrize("rep", range(10))
def test_stress_analyze_repeated(n: int, rep: int) -> None:
    candles = mk_series_uptrend(n)
    r = MarketAnalyzer().analyze(f"STR{rep}", candles)
    assert len(candles) == n
    assert r["hurst"] >= 0.0
