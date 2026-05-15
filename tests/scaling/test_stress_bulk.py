"""
Stres testleri: MarketAnalyzer farklı mum sayıları için.

Eskiden: 6×10=60 test (aynı boyut 10 kez tekrarlanıyor, anlamsız `rep` indeksi).
Şimdi: 6 distinct boyut + 1 determinizm testi — her test farklı bir davranışı doğrular.
"""
from __future__ import annotations

import pytest
from super_otonom.analyzer import MarketAnalyzer

from tests.scaling.helpers import mk_series_uptrend

_SIZES = [80, 120, 200, 350, 500, 750]


@pytest.mark.parametrize("n", _SIZES)
def test_analyze_returns_valid_result(n: int) -> None:
    """Analyzer her desteklenen mum sayısı için yapısal olarak eksiksiz sonuç döndürmeli."""
    candles = mk_series_uptrend(n)
    result = MarketAnalyzer().analyze("BTC/USDT", candles)

    assert result["hurst"] >= 0.0
    assert result["signal"] in ("BUY", "SELL", "HOLD")
    assert isinstance(result.get("regime"), str)
    assert len(result.get("regime", "")) > 0


def test_analyze_is_deterministic() -> None:
    """Aynı girdi → aynı çıktı (gizli rastgelelik yok)."""
    candles = mk_series_uptrend(200)
    r1 = MarketAnalyzer().analyze("BTC/USDT", candles)
    r2 = MarketAnalyzer().analyze("BTC/USDT", candles)

    assert r1["signal"] == r2["signal"]
    assert r1["hurst"] == r2["hurst"]
    assert r1["regime"] == r2["regime"]
