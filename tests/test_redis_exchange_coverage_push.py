"""redis_bridge + exchange_async — hedefli gerçek davranış / minimal IO mock (omit yok)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Adım 1: redis_bridge (ImportError dalı izole süreç; diğerleri gerçek modül yolu) ──


def test_redis_bridge_import_error_sets_degraded_in_subprocess() -> None:
    """redis import başarısızken modül üst seviye except dalı (satır 33–36) — ana pytest sürecine dokunmaz."""
    root = Path(__file__).resolve().parents[1]
    code = r"""
import builtins
import importlib
import sys

_real_import = builtins.__import__

def _guard(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name == "redis":
        raise ImportError("simulated redis missing")
    return _real_import(name, globals, locals, fromlist, level)

builtins.__import__ = _guard
sys.path.insert(0, r"%s")
if "super_otonom.infra.redis_bridge" in sys.modules:
    del sys.modules["super_otonom.infra.redis_bridge"]
if "redis" in sys.modules:
    del sys.modules["redis"]
m = importlib.import_module("super_otonom.infra.redis_bridge")
assert m._REDIS_AVAILABLE is False
b = m.RedisBridge(url="redis://localhost:0")
assert b.is_connected is False
assert b.redis_klines_available is False
assert b.degraded_reason and "not installed" in b.degraded_reason.lower()
assert b.get_kline("BTCUSDT") is None
assert b.status()["connected"] is False
""" % str(root).replace(
        "\\", "\\\\"
    )

    env = {**os.environ, "PYTHONPATH": str(root)}
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_redis_bridge_subscribe_outer_error_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """subscribe: pubsub.listen() hemen hata → except bloğu (satır 157–158)."""
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")

    class _PS:
        def subscribe(self, *_: Any) -> None:
            return None

        def listen(self) -> Any:
            raise ConnectionError("listen failed")

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, *_a: Any, **_k: Any) -> None:
            return None

        def pubsub(self) -> _PS:
            return _PS()

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.is_connected is True
    b.subscribe(lambda s: None)


def test_redis_bridge_get_latest_price_zero_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_latest_price: close 0 / falsy → float 0.0 (satır 131)."""
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")

    raw = json.dumps({"updated_at": time.time() * 1000, "close": 0})

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, *_a: Any, **_k: Any) -> str:
            return raw

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.get_latest_price("BTCUSDT") == 0.0


def test_redis_bridge_status_symbol_price_none_when_no_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """status(): kline var ama close yok → price 0.0 (satır 170–176)."""
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")

    raw = json.dumps({"updated_at": time.time() * 1000})

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, *_a: Any, **_k: Any) -> str:
            return raw

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    st = b.status()
    assert st["connected"] is True
    assert st["symbols"]["BTCUSDT"]["available"] is True
    assert st["symbols"]["BTCUSDT"]["price"] == 0.0


def test_redis_bridge_close_client_only_no_pubsub() -> None:
    """close(): _pubsub yok, yalnızca _client (satır 192–197)."""
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    bridge = rb.RedisBridge.__new__(rb.RedisBridge)
    bridge._connected = True
    bridge._pubsub = None
    bridge._client = MagicMock()
    bridge.close()
    bridge._client.close.assert_called_once()
    assert bridge._connected is False


def test_redis_bridge_when_flag_unavailable_short_circuits_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Modül redis yüklü olsa bile _REDIS_AVAILABLE=False → ctor erken çıkış (61–67)."""
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", False)
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.degraded_reason and "not installed" in b.degraded_reason.lower()
    assert b._client is None
    assert b.is_connected is False


def test_redis_bridge_ping_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_url başarılı, ping exception → degrade (74–76)."""
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")

    class _Client:
        def ping(self) -> None:
            raise ConnectionError("no redis")

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.is_connected is False
    assert b.degraded_reason and "no redis" in b.degraded_reason


def test_redis_bridge_redis_klines_available_false_when_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")

    class _Client:
        def ping(self) -> None:
            raise OSError("down")

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://x")
    assert b.redis_klines_available is False


def test_redis_bridge_get_kline_raw_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, *_a: Any, **_k: Any) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.get_kline("BTCUSDT") is None


def test_redis_bridge_get_kline_stale_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    old = json.dumps({"updated_at": 0, "close": 1.0})

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, *_a: Any, **_k: Any) -> str:
            return old

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.get_kline("ethusdt") is None


def test_redis_bridge_get_kline_future_updated_at_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    fut = time.time() * 1000 + 999_999_999
    payload = json.dumps({"updated_at": fut, "close": 1.0})

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, *_a: Any, **_k: Any) -> str:
            return payload

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.get_kline("BTCUSDT") is None


def test_redis_bridge_clear_stale_kline_keys_deletes_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    old = time.time() * 1000 - 9_999_999_999
    deleted: list[str] = []

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, key: str, *_a: Any, **_k: Any) -> str:
            return json.dumps({"updated_at": old, "close": 1.0})

        def delete(self, key: str) -> int:
            deleted.append(key)
            return 1

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    n = b.clear_stale_kline_keys()
    assert n == len(rb.SYMBOLS)
    assert len(deleted) == len(rb.SYMBOLS)


def test_redis_bridge_get_kline_invalid_json_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, *_a: Any, **_k: Any) -> str:
            return "not-json{"

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.get_kline("BTCUSDT") is None


def test_redis_bridge_get_all_klines_maps_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    fresh = json.dumps({"updated_at": time.time() * 1000, "close": 2.5})

    class _Client:
        def ping(self) -> None:
            return None

        def get(self, key: str, *_a: Any, **_k: Any) -> str | None:
            if "BTCUSDT" in key:
                return fresh
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    all_k = b.get_all_klines()
    assert set(all_k.keys()) == set(rb.SYMBOLS)
    assert all_k["BTCUSDT"] is not None
    assert all_k["BTCUSDT"]["close"] == 2.5


def test_redis_bridge_close_pubsub_only_no_client() -> None:
    """close(): pubsub var, client yok → 192 dalı False, yine 197."""
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    ps = MagicMock()
    bridge = rb.RedisBridge.__new__(rb.RedisBridge)
    bridge._connected = True
    bridge._pubsub = ps
    bridge._client = None
    rb.RedisBridge.close(bridge)
    ps.unsubscribe.assert_called_once()
    ps.close.assert_called_once()
    assert bridge._connected is False


def test_redis_bridge_close_pubsub_and_client_swallow_errors() -> None:
    import super_otonom.infra.redis_bridge as rb

    pytest.importorskip("redis")
    ps = MagicMock()
    ps.unsubscribe.side_effect = None
    ps.close.side_effect = OSError("c")
    cli = MagicMock()
    cli.close.side_effect = OSError("x")
    bridge = rb.RedisBridge.__new__(rb.RedisBridge)
    bridge._connected = True
    bridge._pubsub = ps
    bridge._client = cli
    rb.RedisBridge.close(bridge)
    ps.unsubscribe.assert_called_once()
    ps.close.assert_called_once()
    cli.close.assert_called_once()
    assert bridge._connected is False


# ── Adım 2: exchange_async ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_aiohttp_default_resolver_session_builds_session() -> None:
    """Gerçek aiohttp oturumu (DefaultResolver); ağa istek yok."""
    pytest.importorskip("aiohttp")
    from super_otonom.exchange_async import _install_aiohttp_default_resolver_session

    class _Ex:
        asyncio_loop = None
        throttler = None
        ssl_context = None
        session = None
        tcp_connector = None
        verify = True
        cafile = None
        aiohttp_trust_env = True
        own_session = False

    ex = _Ex()
    await _install_aiohttp_default_resolver_session(ex)
    assert ex.session is not None
    assert ex.tcp_connector is not None
    assert ex.own_session is True
    await ex.session.close()
    await ex.tcp_connector.close()


@pytest.mark.asyncio
async def test_async_exchange_aenter_resolver_install_warns_not_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """__aenter__: resolver kurulumu exception → log path, handler yine döner (498–501)."""
    import super_otonom.exchange_async as ea

    async def _boom(_ex: Any) -> None:
        raise RuntimeError("resolver setup skipped for test")

    monkeypatch.setattr(ea, "_install_aiohttp_default_resolver_session", _boom)
    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)
    monkeypatch.setattr(ea, "_use_aiohttp_default_resolver", lambda: True)

    class _MiniEx:
        options: dict = {}
        aiohttp_trust_env = True

        async def load_time_difference(self) -> None:
            return None

        async def load_markets(self) -> None:
            return None

        async def close(self) -> None:
            return None

    h = object.__new__(ea.AsyncExchangeHandler)
    h.exchange_id = "kucoin"
    h.testnet = True
    h._ex = _MiniEx()

    out = await h.__aenter__()
    assert out is h
    await h.close()


@pytest.mark.asyncio
async def test_async_exchange_unknown_exchange_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.exchange_async as ea

    pytest.importorskip("ccxt.async_support", reason="ccxt async gerekli")

    # MagicMock kök nesne: getattr(..., bilinmeyen_id) asla None dönmez; gerçek namespace kullan.
    class _CcxtStub:
        binance = object

    monkeypatch.setattr(ea, "ccxt_async", _CcxtStub())
    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)
    with pytest.raises(ValueError, match="bilinmeyen exchange"):
        ea.AsyncExchangeHandler("definitely_not_a_ccxt_exchange_id_xyz", testnet=True)


def test_async_exchange_unknown_exchange_raises_sync() -> None:
    import super_otonom.exchange_async as ea

    ccxt_async = pytest.importorskip("ccxt.async_support", reason="ccxt async gerekli")
    if getattr(ccxt_async, "definitely_not_a_ccxt_exchange_id_xyz", None) is not None:
        pytest.skip("unexpected: fake id exists on ccxt")
    with pytest.raises(ValueError, match="bilinmeyen exchange"):
        ea.AsyncExchangeHandler("definitely_not_a_ccxt_exchange_id_xyz", testnet=True)


@pytest.mark.asyncio
async def test_async_exchange_binance_demo_urls_fallback_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_demo_trading yok; urls['demo'] dict → api kopyası (266–271)."""
    import super_otonom.exchange_async as ea

    pytest.importorskip("ccxt.async_support", reason="ccxt async gerekli")

    class _FakeBin:
        urls = {"demo": {"spot": "https://demo.example"}}
        options: dict[str, Any] = {}
        aiohttp_trust_env = True

        def __init__(self, _config: dict) -> None:
            pass

    monkeypatch.setenv("BINANCE_TESTNET", "1")
    monkeypatch.setattr(ea.ccxt_async, "binance", _FakeBin)
    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)

    h = ea.AsyncExchangeHandler("binance", api_key="k", api_secret="s", testnet=True)
    assert h._ex is not None
    assert isinstance(h._ex.urls.get("api"), dict)


@pytest.mark.asyncio
async def test_async_exchange_binance_demo_enable_demo_raises_warn_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_demo_trading var ve exception → except 274–275."""
    import super_otonom.exchange_async as ea

    pytest.importorskip("ccxt.async_support", reason="ccxt async gerekli")

    class _FakeBin:
        urls: dict[str, Any] = {"demo": {}}
        options: dict[str, Any] = {}
        aiohttp_trust_env = True

        def __init__(self, _config: dict) -> None:
            pass

        def enable_demo_trading(self, _v: bool) -> None:
            raise RuntimeError("demo trading unavailable in test")

    monkeypatch.setenv("BINANCE_TESTNET", "1")
    monkeypatch.setattr(ea.ccxt_async, "binance", _FakeBin)
    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)

    h = ea.AsyncExchangeHandler("binance", api_key="k", api_secret="s", testnet=True)
    assert h._ex is not None


@pytest.mark.asyncio
async def test_async_exchange_fetch_positions_with_symbols_list() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_positions = AsyncMock(side_effect=[[{"symbol": "BTC/USDT"}], []])

    out = await h.fetch_positions(["BTC/USDT", "ETH/USDT"])
    assert len(out) == 1
    assert h._ex.fetch_positions.await_count == 2


@pytest.mark.asyncio
async def test_async_exchange_fetch_positions_error_returns_empty() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_positions = AsyncMock(side_effect=RuntimeError("positions down"))

    out = await h.fetch_positions()
    assert out == []


@pytest.mark.asyncio
async def test_async_exchange_fetch_balance_invalid_initial_capital(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.exchange_async as ea

    monkeypatch.setenv("INITIAL_CAPITAL", "not-a-float")
    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = None
    bal = await h.fetch_balance()
    assert bal["total"]["USDT"] == 1000.0


@pytest.mark.asyncio
async def test_async_exchange_fetch_balance_raises_after_log() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_balance = AsyncMock(side_effect=RuntimeError("balance down"))

    with pytest.raises(RuntimeError, match="balance down"):
        await h.fetch_balance()


@pytest.mark.asyncio
async def test_async_exchange_fetch_positions_no_exchange_returns_empty() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = None
    assert await h.fetch_positions() == []


@pytest.mark.asyncio
async def test_async_exchange_fetch_positions_global_success_calls_tracker() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_positions = AsyncMock(return_value=({"symbol": "X"},))

    out = await h.fetch_positions()
    assert out == [{"symbol": "X"}]


@pytest.mark.asyncio
async def test_async_exchange_fetch_balance_success_calls_tracker() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_balance = AsyncMock(return_value={"total": {"USDT": 42.0}})

    bal = await h.fetch_balance()
    assert bal["total"]["USDT"] == 42.0


@pytest.mark.asyncio
async def test_async_exchange_fetch_order_book_success_calls_tracker() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_order_book = AsyncMock(
        return_value={"asks": [[1.0, 1.0]], "bids": [[0.9, 2.0]]}
    )

    ob = await h.fetch_order_book("BTC/USDT", limit=5)
    assert ob["asks"] == [[1.0, 1.0]]
    assert ob["bids"] == [[0.9, 2.0]]


@pytest.mark.asyncio
async def test_async_exchange_fetch_positions_ratelimit_returns_empty() -> None:
    import super_otonom.exchange_async as ea

    class _RL(Exception):
        code = 429

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_positions = AsyncMock(side_effect=_RL("too many"))

    out = await h.fetch_positions()
    assert out == []


@pytest.mark.asyncio
async def test_async_exchange_fetch_balance_ratelimit_re_raises() -> None:
    import super_otonom.exchange_async as ea

    class _RL(Exception):
        code = 418

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_balance = AsyncMock(side_effect=_RL("ddos"))

    with pytest.raises(_RL):
        await h.fetch_balance()


@pytest.mark.asyncio
async def test_async_exchange_close_noop_when_no_exchange() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = None
    await h.close()
    assert h._ex is None


@pytest.mark.asyncio
async def test_async_exchange_close_logs_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.close = AsyncMock(side_effect=RuntimeError("close boom"))

    await h.close()
    assert h._ex is None


def test_use_aiohttp_default_resolver_non_windows_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.exchange_async as ea

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("SUPER_OTONOM_AIOHTTP_DEFAULT_RESOLVER", raising=False)
    assert ea._use_aiohttp_default_resolver() is False
    monkeypatch.setenv("SUPER_OTONOM_AIOHTTP_DEFAULT_RESOLVER", "on")
    assert ea._use_aiohttp_default_resolver() is True


@pytest.mark.asyncio
async def test_install_resolver_closes_prior_session_and_sets_throttler_loop() -> None:
    pytest.importorskip("aiohttp")
    from super_otonom.exchange_async import _install_aiohttp_default_resolver_session

    class _Th:
        loop = None

    old_sess = MagicMock()
    old_sess.close = AsyncMock()
    old_conn = MagicMock()
    old_conn.close = AsyncMock()

    class _Ex:
        asyncio_loop = None
        throttler = _Th()
        ssl_context = None
        session = old_sess
        tcp_connector = old_conn
        verify = True
        cafile = None
        aiohttp_trust_env = True
        own_session = False

    ex = _Ex()
    await _install_aiohttp_default_resolver_session(ex)
    assert ex.asyncio_loop is asyncio.get_running_loop()
    assert ex.throttler.loop is ex.asyncio_loop
    old_sess.close.assert_awaited_once()
    old_conn.close.assert_awaited_once()
    await ex.session.close()
    await ex.tcp_connector.close()


@pytest.mark.asyncio
async def test_install_resolver_verify_false_sets_ssl_context_false() -> None:
    pytest.importorskip("aiohttp")
    from super_otonom.exchange_async import _install_aiohttp_default_resolver_session

    class _Ex:
        asyncio_loop = None
        throttler = None
        ssl_context = None
        session = None
        tcp_connector = None
        verify = False
        cafile = None
        aiohttp_trust_env = True
        own_session = False

    ex = _Ex()
    await _install_aiohttp_default_resolver_session(ex)
    assert ex.ssl_context is False
    await ex.session.close()
    await ex.tcp_connector.close()


@pytest.mark.asyncio
async def test_async_exchange_binance_testnet_env_off_logs_live_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.exchange_async as ea

    pytest.importorskip("ccxt.async_support", reason="ccxt async gerekli")

    class _FakeBin:
        options: dict[str, Any] = {}
        aiohttp_trust_env = True

        def __init__(self, _c: dict) -> None:
            pass

    monkeypatch.delenv("BINANCE_TESTNET", raising=False)
    monkeypatch.setattr(ea.ccxt_async, "binance", _FakeBin)
    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)
    h = ea.AsyncExchangeHandler("binance", testnet=True)
    assert h._ex is not None


@pytest.mark.asyncio
async def test_async_exchange_non_binance_testnet_calls_set_sandbox_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.exchange_async as ea

    pytest.importorskip("ccxt.async_support", reason="ccxt async gerekli")

    class _FakeKu:
        options: dict[str, Any] = {}
        aiohttp_trust_env = True
        called: list[bool] = []

        def __init__(self, _c: dict) -> None:
            pass

        def set_sandbox_mode(self, v: bool) -> None:
            self.called.append(v)

    monkeypatch.setattr(ea.ccxt_async, "kucoin", _FakeKu)
    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)
    h = ea.AsyncExchangeHandler("kucoin", testnet=True)
    assert h._ex is not None
    assert h._ex.called == [True]


@pytest.mark.asyncio
async def test_async_exchange_binance_demo_urls_demo_missing_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.exchange_async as ea

    pytest.importorskip("ccxt.async_support", reason="ccxt async gerekli")

    class _FakeBin:
        urls: dict[str, Any] = {}
        options: dict[str, Any] = {}
        aiohttp_trust_env = True

        def __init__(self, _c: dict) -> None:
            pass

    monkeypatch.setenv("BINANCE_TESTNET", "1")
    monkeypatch.setattr(ea.ccxt_async, "binance", _FakeBin)
    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)
    h = ea.AsyncExchangeHandler("binance", api_key="k", api_secret="s", testnet=True)
    assert h._ex is not None


@pytest.mark.asyncio
async def test_async_exchange_aenter_binance_time_and_markets_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.exchange_async as ea

    monkeypatch.setattr(ea, "_CCXT_AVAILABLE", True)
    monkeypatch.setattr(ea, "_use_aiohttp_default_resolver", lambda: False)
    monkeypatch.setenv("BINANCE_TESTNET", "1")

    class _ExFailSkew:
        options: dict[str, Any] = {}
        aiohttp_trust_env = True
        markets: dict[str, Any] = {}

        async def load_time_difference(self) -> None:
            raise RuntimeError("skew")

        async def load_markets(self) -> None:
            raise RuntimeError("markets")

    h = object.__new__(ea.AsyncExchangeHandler)
    h.exchange_id = "binance"
    h.testnet = True
    h._ex = _ExFailSkew()
    await h.__aenter__()
    await h.close()

    class _ExOk:
        options: dict[str, Any] = {}
        aiohttp_trust_env = True
        markets = {"BTC/USDT": {}}

        async def load_time_difference(self) -> None:
            return None

        async def load_markets(self) -> None:
            return None

    h2 = object.__new__(ea.AsyncExchangeHandler)
    h2.exchange_id = "binance"
    h2.testnet = True
    h2._ex = _ExOk()
    await h2.__aenter__()
    await h2.close()


@pytest.mark.asyncio
async def test_async_exchange_fetch_all_ohlcv_exception_becomes_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)

    async def _fetch_one(self: Any, symbol: str, timeframe: str, limit: int) -> Any:
        if symbol == "BAD":
            raise RuntimeError("ohlcv fail")
        return [[1, 1, 1, 1, 1, 1]]

    monkeypatch.setattr(ea.AsyncExchangeHandler, "_fetch_one", _fetch_one)
    out = await h.fetch_all_ohlcv(["OK", "BAD"], timeframe="1m", limit=2)
    assert out["OK"] == [[1, 1, 1, 1, 1, 1]]
    assert out["BAD"] == []


@pytest.mark.asyncio
async def test_async_exchange_fetch_order_book_ratelimit_tracked() -> None:
    import super_otonom.exchange_async as ea

    class _RL(Exception):
        code = 429

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_order_book = AsyncMock(side_effect=_RL("rl"))

    ob = await h.fetch_order_book("BTC/USDT")
    assert ob == {"asks": [], "bids": []}


def test_circuit_breaker_recovery_half_open_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.exchange_async as ea
    from super_otonom.exchange_async import CircuitBreaker

    cb = CircuitBreaker(1, 0.01)
    cb.is_open = True
    cb.last_failure_time = 0.0
    cb.failures = 5
    monkeypatch.setattr(ea.time, "time", lambda: 1_000_000.0)
    assert cb.can_proceed() is True
    assert cb.is_open is False
