"""exchange_async: fake OHLCV, _fetch_one dalları, emir, dönüştürücü."""
from __future__ import annotations

import asyncio
import types
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
import super_otonom.exchange_async as ex
from super_otonom.exchange_async import (
    AsyncExchangeHandler,
    CircuitBreaker,
    _fake_ohlcv,
    ohlcv_to_candles,
)
from super_otonom.kill_switch import is_ratelimit_error


def test_ohlcv_to_candles_skips_short_rows() -> None:
    out = ohlcv_to_candles([[1, 2, 3], [1, 1, 1, 1, 1, 1]])
    assert len(out) == 1


def test_fake_ohlcv_produces_data() -> None:
    d = _fake_ohlcv("BTC/USDT", 3)
    assert len(d) == 3
    assert len(d[0]) == 6


def test_circuit_breaker_state_strings() -> None:
    cb = CircuitBreaker(3, 10.0)
    for _ in range(3):
        cb.record_failure()
    assert "OPEN" in cb.state and cb.is_open


def test_circuit_open_blocks_until_recovery() -> None:
    cb = CircuitBreaker(1, 1_000_000.0)
    t0 = 1_000_000.0
    with mock.patch("super_otonom.exchange_async.time.time", return_value=t0):
        cb.record_failure()
    with mock.patch("super_otonom.exchange_async.time.time", return_value=t0 + 1.0):
        assert not cb.can_proceed()


def test_fetch_one_without_exchange_uses_fake() -> None:
    h = object.__new__(AsyncExchangeHandler)
    h._ex = None
    h.max_retries = 1
    h.retry_delay = 0.0
    h._cb_threshold = 5
    h._cb_recovery = 60.0
    h._breakers = {}

    async def go():
        d = await AsyncExchangeHandler._fetch_one(h, "ETH/USDT", "1h", 5)  # type: ignore
        assert len(d) == 5

    asyncio.run(go())


def test_fetch_one_circuit_open_returns_empty() -> None:
    h = object.__new__(AsyncExchangeHandler)
    h._ex = None
    h._breakers = {}
    h._cb_threshold = 1
    h._cb_recovery = 60.0
    b = AsyncExchangeHandler._get_breaker(h, "X")
    b.failures = 99
    b.is_open = True
    b.last_failure_time = __import__("time").time()
    h.max_retries = 1
    h.retry_delay = 0.0

    async def go():
        d = await AsyncExchangeHandler._fetch_one(h, "X", "1h", 3)  # type: ignore
        assert d == []

    asyncio.run(go())


def test_fetch_one_success_mock_exchange() -> None:
    m_ex = MagicMock()
    m_ex.fetch_ohlcv = AsyncMock(
        return_value=[[0, 1, 1, 1, 1, 1], [0, 1, 1, 1, 1, 1]]
    )
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex
    h.max_retries = 1
    h.retry_delay = 0.0
    h._cb_threshold = 5
    h._cb_recovery = 60.0
    h._breakers = {}

    async def go():
        d = await AsyncExchangeHandler._fetch_one(h, "Z", "1m", 2)  # type: ignore
        assert m_ex.fetch_ohlcv.await_count >= 1
        assert len(d) == 2

    asyncio.run(go())


def test_fetch_one_retries_then_error_object() -> None:
    m_ex = MagicMock()
    m_ex.fetch_ohlcv = AsyncMock(side_effect=RuntimeError("x"))
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex
    h.max_retries = 2
    h.retry_delay = 0.0
    h._cb_threshold = 5
    h._cb_recovery = 60.0
    h._breakers = {}

    async def go():
        with mock.patch("super_otonom.exchange_async.asyncio.sleep", new_callable=AsyncMock):
            res = await AsyncExchangeHandler._fetch_one(h, "Z2", "1m", 2)  # type: ignore
        assert isinstance(res, RuntimeError)

    asyncio.run(go())


def test_fetch_all_ohlcv_gathers_exception() -> None:
    m_ex = MagicMock()
    m_ex.fetch_ohlcv = AsyncMock(side_effect=ValueError("e"))
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex
    h.max_retries = 1
    h.retry_delay = 0.0
    h._cb_threshold = 5
    h._cb_recovery = 60.0
    h._breakers = {}

    async def go():
        with mock.patch("super_otonom.exchange_async.asyncio.sleep", new_callable=AsyncMock):
            out = await h.fetch_all_ohlcv(["A", "B"], "1h", 2)
        assert out["A"] == [] and out["B"] == []

    asyncio.run(go())


def test_order_book_get_status_cancel_and_close() -> None:
    m_ex = MagicMock()
    m_ex.fetch_order_book = AsyncMock(return_value={"asks": [[1, 1]], "bids": []})
    m_ex.fetch_order = AsyncMock(return_value={"status": "closed"})
    m_ex.cancel_order = AsyncMock()
    m_ex.close = AsyncMock()
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex

    async def go():
        ob = await h.fetch_order_book("X", 2)
        assert "asks" in ob
        st = await h.get_order_status("1", "X")
        assert st == "filled"
        m_ex.fetch_order = AsyncMock(return_value={"status": "open"})
        st2 = await h.get_order_status("1", "X")
        assert st2 == "open"
        m_ex.fetch_order = AsyncMock(side_effect=OSError("z"))
        st3 = await h.get_order_status("1", "X")
        assert st3 == "unknown"
        ok = await h.cancel_order("1", "X")
        assert ok is True
        m_ex.cancel_order = AsyncMock(side_effect=ValueError("c"))
        ok2 = await h.cancel_order("1", "X")
        assert ok2 is False
        m_ex.close.side_effect = OSError("n")
        await h.close()
        m_ex.close.side_effect = None
        m_ex.close = AsyncMock()
        h._ex = m_ex
        await h.close()

    asyncio.run(go())


def test_ratelimit_helper() -> None:
    e = type("E", (), {"code": 429})()
    assert is_ratelimit_error(e) is True


def test_unknown_exchange_raises() -> None:
    with mock.patch.object(ex, "_CCXT_AVAILABLE", True), mock.patch.object(
        ex, "ccxt_async", types.SimpleNamespace()
    ):
        with pytest.raises(ValueError, match="bilinmeyen"):
            AsyncExchangeHandler("nosuchexchange")


def test_ex_none_order_book_get_cancel() -> None:
    h = object.__new__(AsyncExchangeHandler)
    h._ex = None

    async def go():
        ob = await h.fetch_order_book("X", 1)
        assert ob == {"asks": [], "bids": []}
        st = await h.get_order_status("1", "X")
        assert st == "unknown"
        assert await h.cancel_order("1", "X") is False

    asyncio.run(go())


def test_aexit_calls_close() -> None:
    m_ex = MagicMock()
    m_ex.close = AsyncMock()
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex

    async def go():
        await h.__aexit__(None, None, None)
        m_ex.close.assert_awaited()

    asyncio.run(go())
