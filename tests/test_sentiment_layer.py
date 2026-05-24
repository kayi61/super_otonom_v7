"""SentimentLayer — mock ve durum sınıfları."""

from __future__ import annotations

from super_otonom.signals.sentiment_layer import SentimentLayer, _dynamic_fallback_score


def test_mock_bearish_status() -> None:
    s = SentimentLayer(mock_score=0.2)
    r = s.get_market_sentiment()
    assert r["source"] == "mock"
    assert r["status"] == "BEARISH_PANIC"
    assert r["score"] < 0.3


def test_mock_bullish_status() -> None:
    s = SentimentLayer(mock_score=0.85)
    r = s.get_market_sentiment()
    assert r["status"] == "BULLISH_EUPHORIA"


def test_mock_neutral_band() -> None:
    s = SentimentLayer(mock_score=0.5)
    r = s.get_market_sentiment()
    assert r["status"] == "NEUTRAL"


def test_dynamic_fallback_in_range() -> None:
    v = _dynamic_fallback_score()
    assert 0.45 <= v <= 0.55
