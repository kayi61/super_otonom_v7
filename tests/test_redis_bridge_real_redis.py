"""redis_bridge — gerçek Redis (redis-py); unittest.mock / monkeypatch yok.

REDIS_TEST_URL yoksa varsayılan redis://127.0.0.1:6379/15 (yalnız bu DB temizlenir).
Redis yoksa veya ping başarısızsa tüm testler skip.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import pytest
from super_otonom.redis_bridge import SYMBOLS, RedisBridge


def _redis_url() -> str:
    return os.getenv("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture(scope="module")
def live_redis_url() -> str:
    redis = pytest.importorskip("redis", reason="redis-py gerekli")
    url = _redis_url()
    client = redis.from_url(url, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 — bağlantı hatası skip
        pytest.skip(f"Redis erisilemiyor ({url}): {exc}")
    yield url
    try:
        client.flushdb()
    except Exception:
        pass
    finally:
        client.close()


def _set_kline(client: Any, symbol: str, payload: dict[str, Any]) -> None:
    key = f"market:{symbol.upper()}:kline_5m"
    client.set(key, json.dumps(payload))


def test_redis_bridge_real_connection_and_get_kline(live_redis_url: str) -> None:
    b = RedisBridge(url=live_redis_url)
    if not b.is_connected:
        pytest.skip(f"RedisBridge baglanamadi: {b.degraded_reason}")
    raw_client = pytest.importorskip("redis").from_url(live_redis_url, decode_responses=True)
    now_ms = time.time() * 1000
    _set_kline(raw_client, "BTCUSDT", {"updated_at": now_ms, "close": 42_000.5, "open": 1})
    try:
        data = b.get_kline("btcusdt")
        assert data is not None
        assert data["close"] == 42_000.5
        assert b.get_latest_price("BTCUSDT") == 42_000.5
    finally:
        raw_client.delete("market:BTCUSDT:kline_5m")
        raw_client.close()
        b.close()


def test_redis_bridge_real_get_kline_none_when_key_missing(live_redis_url: str) -> None:
    b = RedisBridge(url=live_redis_url)
    if not b.is_connected:
        pytest.skip(f"RedisBridge baglanamadi: {b.degraded_reason}")
    try:
        assert b.get_kline("BTCUSDT") is None
    finally:
        b.close()


def test_redis_bridge_real_stale_kline_returns_none(live_redis_url: str) -> None:
    b = RedisBridge(url=live_redis_url)
    if not b.is_connected:
        pytest.skip(f"RedisBridge baglanamadi: {b.degraded_reason}")
    raw_client = pytest.importorskip("redis").from_url(live_redis_url, decode_responses=True)
    old_ms = time.time() * 1000 - 120_000
    _set_kline(raw_client, "ETHUSDT", {"updated_at": old_ms, "close": 1.0})
    try:
        assert b.get_kline("ETHUSDT") is None
    finally:
        raw_client.delete("market:ETHUSDT:kline_5m")
        raw_client.close()
        b.close()


def test_redis_bridge_real_get_all_klines_and_status(live_redis_url: str) -> None:
    b = RedisBridge(url=live_redis_url)
    if not b.is_connected:
        pytest.skip(f"RedisBridge baglanamadi: {b.degraded_reason}")
    raw_client = pytest.importorskip("redis").from_url(live_redis_url, decode_responses=True)
    now_ms = time.time() * 1000
    try:
        for sym in SYMBOLS:
            _set_kline(raw_client, sym, {"updated_at": now_ms, "close": 1.0})
        all_k = b.get_all_klines()
        assert set(all_k.keys()) == set(SYMBOLS)
        assert all(v is not None for v in all_k.values())
        st = b.status()
        assert st["connected"] is True
        assert st["redis_klines_available"] is True
        for sym in SYMBOLS:
            assert st["symbols"][sym]["available"] is True
            assert st["symbols"][sym]["price"] == 1.0
    finally:
        for sym in SYMBOLS:
            raw_client.delete(f"market:{sym}:kline_5m")
        raw_client.close()
        b.close()


def test_redis_bridge_real_subscribe_receives_publish(live_redis_url: str) -> None:
    b = RedisBridge(url=live_redis_url)
    if not b.is_connected:
        pytest.skip(f"RedisBridge baglanamadi: {b.degraded_reason}")
    raw_client = pytest.importorskip("redis").from_url(live_redis_url, decode_responses=True)
    received: list[str] = []

    def cb(sym: str) -> None:
        received.append(sym)

    t = threading.Thread(target=b.subscribe, args=(cb,), daemon=True)
    t.start()
    time.sleep(0.35)
    try:
        raw_client.publish("market:kline_update", "SOLUSDT")
        deadline = time.time() + 5.0
        while time.time() < deadline and not received:
            time.sleep(0.05)
        assert "SOLUSDT" in received
    finally:
        b.close()
        time.sleep(0.15)
        raw_client.close()
