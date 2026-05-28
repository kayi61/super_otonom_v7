"""Regime detection, MarketAnalyzer, MTF (Faz 1)."""

from __future__ import annotations

from typing import List

import pytest
from super_otonom.analysis.analyzer import MarketAnalyzer, detect_market_regime


def _candle(
    i: int,
    close: float,
    *,
    o: float | None = None,
    h: float | None = None,
    low: float | None = None,
) -> dict:
    c = float(close)
    o = c - 0.01 if o is None else o
    h = c + 0.02 if h is None else h
    lo = c - 0.02 if low is None else low
    return {
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": 1000.0,
        "timestamp": float(i * 60_000),
    }


def _series_closes_1h_uptrend(n: int = 50) -> List[dict]:
    """Monotonic rising closes for 1H (enough for MIN_CLOSES=30)."""
    out: List[dict] = []
    base = 10_000.0
    for i in range(n):
        c = base + i * 5.0
        out.append(_candle(i, c))
    return out


def _series_closes_4h_downtrend(n: int = 25) -> List[dict]:
    base = 20_000.0
    out: List[dict] = []
    for i in range(n):
        c = base - i * 20.0
        out.append(_candle(1000 + i, c))
    return out


def test_detect_market_regime_default_thresholds() -> None:
    assert detect_market_regime(0.60) == "TRENDING"
    assert detect_market_regime(0.40) == "MEAN_REVERTING"
    assert detect_market_regime(0.50) == "NOISY"
    # Boundaries per implementation: 0.45 and 0.55 fall in NOISY
    assert detect_market_regime(0.45) == "NOISY"
    assert detect_market_regime(0.55) == "NOISY"


def test_analyze_empty_candles() -> None:
    a = MarketAnalyzer()
    r = a.analyze("BTC/USDT", [])
    assert r["signal"] == "HOLD"
    assert r["regime"] == "NOISY"
    assert "Yetersiz" in (r.get("regime_reason") or "")


def test_analyze_too_few_closes() -> None:
    a = MarketAnalyzer()
    few = [_candle(i, 100.0 + i) for i in range(5)]
    r = a.analyze("ETH/USDT", few)
    assert r["signal"] == "HOLD"
    assert r["regime"] == "NOISY"


def test_analyze_v5_1_insufficient_4h_skips_mtf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4H < 22 bars → high_tf_trend UNKNOWN, no MTF override."""
    monkeypatch.setattr("super_otonom.analysis.analyzer._calculate_hurst", lambda ts: 0.5)
    a = MarketAnalyzer()
    c1h = _series_closes_1h_uptrend(40)
    c4h = [_candle(i, 100.0) for i in range(10)]
    r = a.analyze_v5_1("BTC/USDT", c1h, c4h)
    assert r["high_tf_trend"] == "UNKNOWN"
    assert r["mtf_filtered"] is False
    assert "4H veri yetersiz" in (r.get("mtf_reason") or "")


def test_analyze_v5_1_mtf_downgrades_buy_when_4h_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    1H would be BUY in TRENDING; 4H EMA trend DOWN → HOLD + mtf_filtered.
    Hurst/RSI patched to meet trend regime + buy band.
    """
    monkeypatch.setattr("super_otonom.analysis.analyzer._calculate_hurst", lambda ts: 0.58)
    monkeypatch.setattr("super_otonom.analysis.analyzer._rsi", lambda closes, period=14: 55.0)

    candles_1h = _series_closes_1h_uptrend(50)
    candles_4h = _series_closes_4h_downtrend(25)

    a = MarketAnalyzer()
    r = a.analyze_v5_1("BTC/USDT", candles_1h, candles_4h)

    assert r["regime"] == "TRENDING"
    assert r["high_tf_trend"] == "DOWN"
    assert r["mtf_filtered"] is True
    assert r["signal"] == "HOLD"
    assert r.get("futures_side") == "FLAT"
    assert "4H" in (r.get("mtf_reason") or "") or "MTF" in (r.get("regime_reason") or "")
