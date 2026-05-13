"""exchange_async: fake OHLCV, _fetch_one dalları, emir, dönüştürücü."""

from __future__ import annotations

import asyncio
import builtins
import importlib
import os
import sys
import types
from types import MethodType
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
    m_ex.fetch_ohlcv = AsyncMock(return_value=[[0, 1, 1, 1, 1, 1], [0, 1, 1, 1, 1, 1]])
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
    with (
        mock.patch.object(ex, "_CCXT_AVAILABLE", True),
        mock.patch.object(ex, "ccxt_async", types.SimpleNamespace()),
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


def test_ccxt_import_error_disables_exchange() -> None:
    """25-28: ImportError → simule mod."""
    saved = sys.modules.get("super_otonom.exchange_async")
    orig_imp = builtins.__import__

    def _imp(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ccxt.async_support":
            raise ImportError("simulated")
        return orig_imp(name, globals, locals, fromlist, level)

    builtins.__import__ = _imp
    try:
        sys.modules.pop("super_otonom.exchange_async", None)
        mod = importlib.import_module("super_otonom.exchange_async")
        assert mod._CCXT_AVAILABLE is False
        assert mod.ccxt_async is None
    finally:
        builtins.__import__ = orig_imp
        sys.modules.pop("super_otonom.exchange_async", None)
        if saved is not None:
            sys.modules["super_otonom.exchange_async"] = saved
            # import_module yalnızca sys.modules'u düzeltir; paket altı önbellek hâlâ bozuk modülü tutabilir.
            import super_otonom as _so

            _so.exchange_async = saved
        importlib.import_module("super_otonom.exchange_async")


def test_async_handler_early_return_when_ccxt_missing() -> None:
    """144-145: _CCXT_AVAILABLE False iken _ex None."""
    with mock.patch.object(ex, "_CCXT_AVAILABLE", False):
        h = AsyncExchangeHandler("binance")
        assert h._ex is None


def test_circuit_breaker_logs_once_when_threshold_crossed(caplog: pytest.LogCaptureFixture) -> None:
    """60-66: ilk açılışta uyarı."""
    cb = CircuitBreaker(2, 60.0)
    caplog.set_level("WARNING", logger="super_otonom.exchange_async")
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open
    assert any("devre AÇILDI" in r.message for r in caplog.records)


def test_circuit_breaker_no_extra_log_when_already_open(caplog: pytest.LogCaptureFixture) -> None:
    cb = CircuitBreaker(1, 60.0)
    caplog.set_level("WARNING", logger="super_otonom.exchange_async")
    cb.record_failure()
    n = len(caplog.records)
    cb.record_failure()
    assert len(caplog.records) == n


def test_circuit_breaker_success_logs_when_was_open(caplog: pytest.LogCaptureFixture) -> None:
    """71: is_open True iken record_success."""
    cb = CircuitBreaker(1, 60.0)
    caplog.set_level("INFO", logger="super_otonom.exchange_async")
    cb.record_failure()
    cb.record_success()
    assert any("KAPATILDI" in r.message for r in caplog.records)


def test_handler_extra_config_and_sandbox_mode() -> None:
    """Binance testnet: set_sandbox yerine enable_demo_trading (demo-api host)."""

    class FakeEx:
        def __init__(self, config: dict) -> None:
            self.config = config
            self.sandbox = False
            self.urls = {
                "demo": {
                    "public": "https://demo-api.binance.com/api/v3",
                    "private": "https://demo-api.binance.com/api/v3",
                },
            }

        def enable_demo_trading(self, v: bool) -> None:
            if v:
                self.urls["api"] = dict(self.urls["demo"])

    ns = types.SimpleNamespace(binance=FakeEx)
    with (
        mock.patch.object(ex, "_CCXT_AVAILABLE", True),
        mock.patch.object(ex, "ccxt_async", ns),
        mock.patch.dict(os.environ, {"BINANCE_TESTNET": "true"}, clear=False),
    ):
        h = AsyncExchangeHandler("binance", testnet=True, extra_config={"opt": 7})
        assert h._ex.config.get("opt") == 7
        assert h._ex.urls["api"]["public"] == "https://demo-api.binance.com/api/v3"


def test_circuit_breaker_status_reports_symbols() -> None:
    """246."""
    h = object.__new__(AsyncExchangeHandler)
    h._breakers = {}
    h._cb_threshold = 5
    h._cb_recovery = 60.0
    AsyncExchangeHandler._get_breaker(h, "SYM")
    st = h.circuit_breaker_status()
    assert "SYM" in st and "CLOSED" in st["SYM"]


def test_fetch_one_ratelimit_marks_storm() -> None:
    """201-203."""

    class RL(Exception):
        code = 429

    m_ex = MagicMock()
    m_ex.fetch_ohlcv = AsyncMock(side_effect=RL())
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex
    h.max_retries = 1
    h.retry_delay = 0.0
    h._cb_threshold = 5
    h._cb_recovery = 60.0
    h._breakers = {}

    async def go():
        res = await AsyncExchangeHandler._fetch_one(h, "R", "1m", 2)  # type: ignore
        assert isinstance(res, RL)

    asyncio.run(go())


def test_fetch_all_logs_task_exception(caplog: pytest.LogCaptureFixture) -> None:
    """234-236."""
    caplog.set_level("ERROR", logger="super_otonom.exchange_async")
    h = object.__new__(AsyncExchangeHandler)

    async def boom(self, *_a, **_k):
        raise OSError("gather_fail")

    h._fetch_one = MethodType(boom, h)  # type: ignore[method-assign]

    async def go():
        out = await h.fetch_all_ohlcv(["U"], "1m", 1)
        assert out["U"] == []

    asyncio.run(go())
    assert any("U" in r.message for r in caplog.records)


def test_fetch_order_book_ratelimit_branch() -> None:
    """265-267."""

    class RL(Exception):
        code = 429

    m_ex = MagicMock()
    m_ex.fetch_order_book = AsyncMock(side_effect=RL())
    h = object.__new__(AsyncExchangeHandler)
    h._ex = m_ex

    async def go():
        ob = await h.fetch_order_book("Z", 3)
        assert ob == {"asks": [], "bids": []}

    asyncio.run(go())


def test_aenter_returns_handler() -> None:
    """319-320."""
    h = object.__new__(AsyncExchangeHandler)

    async def go():
        assert await h.__aenter__() is h

    asyncio.run(go())
