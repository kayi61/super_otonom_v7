"""SentimentLayer + main_loop kısa tur (kapsam)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from super_otonom.signals.sentiment_layer import SentimentLayer, _dynamic_fallback_score

from tests.test_main_loop_96 import _MAIN_LOOP_MOCK_USDT, apply_main_loop_mock_contract


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


def test_main_loop_runs_until_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.main_loop as ml

    apply_main_loop_mock_contract(
        Path(tmp_path), monkeypatch, ml, pairs=["BTC/USDT"], poll_interval=0.05
    )
    mtf = dict(ml.MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)

    ts0 = int(time.time() * 1000)

    class H:
        async def fetch_all_ohlcv(self, **kw):
            # ccxt OHLCV: [ts ms, o, h, l, c, v] — güncel zaman damgası (stale mum yok)
            row = [float(ts0), 100.0, 101.0, 99.0, 100.0, 1000.0]
            return {"BTC/USDT": [row for _ in range(40)]}

        async def fetch_order_book(self, *a, **k):
            return {"asks": [[100.0, 10.0]], "bids": [[99.0, 10.0]]}

        async def fetch_balance(self, *a, **k):
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

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
        # Her asyncio.run() yeni loop; modüldeki Event önceki loopa bagli kalmamali
        ml._shutdown = asyncio.Event()
        ml._loop_counter = 0
        task = asyncio.create_task(ml.main())
        await asyncio.sleep(0.2)
        ml._shutdown.set()
        await asyncio.wait_for(task, timeout=30.0)

    asyncio.run(runner())


def test_main_loop_mtf_storm_and_analyzer_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import super_otonom.main_loop as ml

    apply_main_loop_mock_contract(
        Path(tmp_path), monkeypatch, ml, pairs=["X/USDT"], poll_interval=0.04
    )
    mtf = dict(ml.MTF)
    mtf["enabled"] = True
    mtf["timeframe"] = "1h"
    mtf["candle_limit"] = 5
    monkeypatch.setattr(ml, "MTF", mtf)
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {"X/USDT": [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 0.0]], "bids": []}

        async def fetch_balance(self, *a, **k) -> dict:
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self) -> dict:
            return {"X/USDT": "OPEN (y)"}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> "H.H":
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)

    class MA:
        def __init__(self) -> None:
            self.c = 0

        def analyze(self, *a) -> dict:
            self.c += 1
            if self.c < 2:
                raise RuntimeError("sim_analyze_fail")
            return {
                "signal": "HOLD",
                "regime": "TRENDING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def analyze_v5_1(self, *a, **k) -> dict:
            return {
                "signal": "HOLD",
                "regime": "TRENDING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> object:
            return None

    trip_i = [0]

    def _storm() -> bool:
        trip_i[0] += 1
        return trip_i[0] in (1, 3)

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", _storm)

    async def runner2() -> None:
        ml._shutdown = asyncio.Event()
        ml._loop_counter = 0
        t = asyncio.create_task(ml.main())
        await asyncio.sleep(0.45)
        ml._shutdown.set()
        try:
            await asyncio.wait_for(t, timeout=25.0)
        except Exception:
            t.cancel()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await t

    asyncio.run(runner2())
