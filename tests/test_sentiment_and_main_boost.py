"""SentimentLayer + main_loop kısa tur (kapsam)."""
from __future__ import annotations

import asyncio

import pytest
from super_otonom.sentiment_layer import SentimentLayer, _dynamic_fallback_score


def test_sentiment_mock_and_validate_branches() -> None:
    s = SentimentLayer(mock_score=0.35)
    st = s.get_market_sentiment()
    assert st["source"] == "mock"
    sig, r = s.validate_with_sentiment(
        "BUY", {"status": "BEARISH_PANIC", "score": 0.1, "source": "x"}
    )
    assert sig == "HOLD"
    sig2, _ = s.validate_with_sentiment("SELL", {"status": "BULLISH_EUPHORIA", "score": 0.9})
    assert sig2 == "HOLD"
    s.set_mock_score(0.5)
    assert s._mock_score == 0.5
    s.clear_mock()
    repr(s)


def test_dynamic_fallback_score() -> None:
    assert 0.4 <= _dynamic_fallback_score() <= 0.6


def test_main_loop_runs_until_shutdown(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import super_otonom.bot_engine as be
    import super_otonom.main_loop as ml

    root = tmp_path
    monkeypatch.setattr(be, "_STATE_FILE", str(root / "st.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(root / "tr.log"))
    ml._shutdown.clear()
    monkeypatch.setattr(ml, "_POLL_INTERVAL", 0.05)
    monkeypatch.setattr(ml, "PAIRS", ["BTC/USDT"])
    mtf = dict(ml.MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)

    class H:
        async def fetch_all_ohlcv(self, **kw):
            row = [1.0, 100.0, 101.0, 99.0, 100.0, 1000.0]
            return {"BTC/USDT": [row for _ in range(40)]}

        async def fetch_order_book(self, *a, **k):
            return {"asks": [[100.0, 10.0]], "bids": [[99.0, 10.0]]}

        def circuit_breaker_status(self):
            return {}

    class CM:
        def __init__(self, **kw):
            self.h = H()

        async def __aenter__(self):
            return self.h

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)

    class MA:
        def analyze(self, sym, c):
            return {
                "signal": "HOLD",
                "regime": "TRENDING",
                "hurst": 0.6,
                "volatility": 0.02,
                "rsi": 50.0,
            }

        def analyze_v5_1(self, *a, **k):
            return self.analyze("", [])

        def apply_liquidity_context(self, *a, **k):
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def runner():
        task = asyncio.create_task(ml.main())
        await asyncio.sleep(0.2)
        ml._shutdown.set()
        await asyncio.wait_for(task, timeout=30.0)

    asyncio.run(runner())
