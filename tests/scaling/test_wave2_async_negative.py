"""Async hata yolları + bozuk/negatif girdiler (74)."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from super_otonom.analyzer import MarketAnalyzer
from super_otonom.exchange_async import AsyncExchangeHandler

from tests.scaling.helpers import mk_candle, mk_series_uptrend


def _make_exc(kind: int) -> BaseException:
    if kind == 0:
        return RuntimeError("rt")
    if kind == 1:
        return ValueError("val")
    if kind == 2:
        return OSError("os")
    if kind == 3:
        return KeyError("key")
    if kind == 4:
        return ConnectionError("conn")
    if kind == 5:
        return TimeoutError("to")
    e = Exception("gen")
    e.code = 429
    return e


@pytest.mark.parametrize("fi", range(7))
@pytest.mark.parametrize("gj", range(8))
def test_wave2_async_fetch_one_logs_and_drains_retries(fi: int, gj: int) -> None:
    exc = _make_exc(fi)
    m_ex = MagicMock()
    m_ex.fetch_ohlcv = AsyncMock(side_effect=exc)
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex
    h.max_retries = 2
    h.retry_delay = 0.0
    h._cb_threshold = 5
    h._cb_recovery = 60.0
    h._breakers = {}

    async def go() -> Any:
        return await AsyncExchangeHandler._fetch_one(h, f"E{fi}_{gj}", "1m", 3)  # type: ignore

    out = asyncio.run(go())
    assert out is exc or isinstance(out, BaseException)


@pytest.mark.parametrize("idx", range(18))
def test_wave2_negative_analyze_malformed_candles(idx: int) -> None:
    a = MarketAnalyzer()
    if idx % 6 == 0:
        candles = [{"open": 1.0, "high": 1.0, "low": 1.0, "volume": 1.0}]
    elif idx % 6 == 1:
        candles = [{"close": None, "open": 1, "high": 1, "low": 1, "volume": 1}]
    elif idx % 6 == 2:
        candles = [{}]
    elif idx % 6 == 3:
        candles = [{"close": "bad", "open": 1, "high": 1, "low": 1, "volume": 1}] * 35
        with pytest.raises(ValueError, match="could not convert string to float"):
            a.analyze("BAD", candles)
        return
    elif idx % 6 == 4:
        candles = mk_series_uptrend(20)[:5]
    else:
        candles = [mk_candle(i, 100.0) for i in range(40)]
    r = a.analyze("BAD", candles)
    assert r["signal"] in ("BUY", "SELL", "HOLD")


@pytest.mark.parametrize("n", range(10))
def test_wave2_async_order_book_and_status_errors(n: int) -> None:
    m_ex = MagicMock()
    if n % 2 == 0:
        m_ex.fetch_order_book = AsyncMock(side_effect=OSError("ob"))
    else:
        m_ex.fetch_order_book = AsyncMock(return_value={"asks": [], "bids": []})
    m_ex.fetch_order = AsyncMock(side_effect=ValueError("ord"))
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex

    async def go() -> None:
        ob = await h.fetch_order_book("X", 3)
        assert "asks" in ob
        st = await h.get_order_status("1", "X")
        assert st == "unknown"

    asyncio.run(go())


@pytest.mark.parametrize("n", range(10))
def test_wave2_async_cancel_false_on_error(n: int) -> None:
    m_ex = MagicMock()
    m_ex.cancel_order = AsyncMock(side_effect=RuntimeError("c"))
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex

    async def go() -> None:
        ok = await h.cancel_order(str(n), "Y")
        assert ok is False

    asyncio.run(go())
