"""
redis_bridge.py — Go WebSocket → Redis → Python köprüsü

Go servisi Binance'den aldığı kline verisini Redis'e yazar.
Bu modül Python botunun o veriyi okumasını sağlar.

Ortam (özet): ``REDIS_URL``, ``REDIS_KLINE_TIMEFRAME``, ``REDIS_KLINE_MAX_AGE_MS``,
``REDIS_KLINE_TIMEFRAME_BUFFER_SEC``, ``REDIS_KLINE_KEY_SUFFIX``, ``REDIS_KLINE_FUTURE_SKEW_MS``.
Yaş eşikleri: ``super_otonom.data_freshness``.

Kullanım:
    bridge = RedisBridge()

    # Tek sembol oku
    kline = bridge.get_kline("BTCUSDT")

    # Tüm sembolleri oku
    all_klines = bridge.get_all_klines()

    # Pub/Sub ile anlık bildirim dinle
    bridge.subscribe(callback)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("super_otonom.infra.redis_bridge")

try:
    import redis

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    log.warning("redis-py kurulu değil — pip install redis")


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
# kline_5m anahtarı Go köprüsü ile uyumlu; başka sonek: REDIS_KLINE_KEY_SUFFIX
_KLINE_KEY_SUFFIX = os.getenv("REDIS_KLINE_KEY_SUFFIX", "kline_5m")
_REDIS_UPDATED_AT_FUTURE_SKEW_MS = int(os.getenv("REDIS_KLINE_FUTURE_SKEW_MS", "120000"))


class RedisBridge:
    """
    Go → Redis → Python köprüsü.

    Redis'te veri yoksa veya Redis bağlantısı yoksa
    None döner — bot REST API'ye düşer, sistem durmuyor.

    Bağlantı yoksa ``redis_klines_available=False`` — Redis üzerinden gelen
    kline hızlandırması devre dışı; OHLCV ana kaynak olarak kalır (sessiz başarısızlık yok).
    """

    def __init__(self, url: str = REDIS_URL):
        self._client: Any = None
        self._pubsub: Any = None
        self._connected = False
        self.degraded_reason: Optional[str] = None

        if not _REDIS_AVAILABLE:
            self.degraded_reason = "redis-py not installed"
            log.error(
                "RedisBridge: redis-py kurulu degil — Redis kline ozelligi devre disi "
                "(pip install redis). OHLCV kullanilacak."
            )
            return

        try:
            self._client = redis.from_url(url, decode_responses=True)
            self._client.ping()
            self._connected = True
            log.info("RedisBridge: Redis baglantisi kuruldu | %s", url)
        except Exception as exc:
            self.degraded_reason = str(exc)
            log.error(
                "RedisBridge: Redis baglanamadi — DEGRADE MOD | redis_kline kapali | "
                "url=%s | hata=%s | Ana veri yolu: REST OHLCV (Go koprusu verisi yok).",
                url,
                exc,
            )

    @property
    def redis_klines_available(self) -> bool:
        """Redis'ten kline okumaya uygun mu (bagli ve kutuphane var mi)."""
        return self._connected and _REDIS_AVAILABLE

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_kline(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Redis'ten son kline verisini çeker.

        Dönüş: kline dict veya None (veri yok / stale / bağlantı yok)
        """
        if not self._connected:
            return None

        key = f"market:{symbol.upper()}:{_KLINE_KEY_SUFFIX}"
        try:
            from super_otonom.data_freshness import redis_kline_max_age_ms

            raw = self._client.get(key)
            if raw is None:
                return None

            data = json.loads(raw)

            # Stale / bozuk updated_at — eşik: data_freshness.redis_kline_max_age_ms (TF ile uyumlu)
            now_ms = time.time() * 1000
            updated_at = float(data.get("updated_at", 0) or 0)
            max_age = float(redis_kline_max_age_ms())
            if updated_at > now_ms + _REDIS_UPDATED_AT_FUTURE_SKEW_MS:
                log.debug(
                    "RedisBridge: updated_at gelecekte | %s | upd=%.0f now=%.0f",
                    symbol,
                    updated_at,
                    now_ms,
                )
                return None
            age_ms = now_ms - updated_at
            if age_ms > max_age:
                log.debug(
                    "RedisBridge: stale veri | %s | age=%.0fms limit=%.0fms",
                    symbol,
                    age_ms,
                    max_age,
                )
                return None

            return data

        except Exception as exc:
            log.warning("RedisBridge.get_kline hata | %s: %s", symbol, exc)
            return None

    def get_all_klines(self) -> Dict[str, Optional[Dict[str, Any]]]:
        """Tüm sembollerin son kline verisini döndürür."""
        return {sym: self.get_kline(sym) for sym in SYMBOLS}

    def clear_stale_kline_keys(self, max_age_ms: Optional[float] = None) -> int:
        """Ops: ``updated_at`` çok eski, sıfır veya saat kaymalı (gelecek) kline anahtarlarını siler.

        TTL yerine tek seferlik temizlik; cron veya deploy öncesi çalıştırılabilir.
        Dönüş: silinen anahtar sayısı.
        """
        if not self._connected:
            return 0
        from super_otonom.data_freshness import redis_kline_max_age_ms

        limit = float(max_age_ms if max_age_ms is not None else redis_kline_max_age_ms())
        now_ms = time.time() * 1000
        deleted = 0
        for sym in SYMBOLS:
            key = f"market:{sym.upper()}:{_KLINE_KEY_SUFFIX}"
            try:
                raw = self._client.get(key)
                if raw is None:
                    continue
                data = json.loads(raw)
                updated_at = float(data.get("updated_at", 0) or 0)
                if updated_at <= 0:
                    self._client.delete(key)
                    deleted += 1
                    continue
                if updated_at > now_ms + _REDIS_UPDATED_AT_FUTURE_SKEW_MS:
                    self._client.delete(key)
                    deleted += 1
                    continue
                if now_ms - updated_at > limit:
                    self._client.delete(key)
                    deleted += 1
            except Exception as exc:
                log.warning("RedisBridge.clear_stale_kline_keys | %s: %s", key, exc)
        if deleted:
            log.info("RedisBridge: clear_stale_kline_keys silinen=%d", deleted)
        return deleted

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Sembolün son kapanış fiyatını döndürür."""
        kline = self.get_kline(symbol)
        if kline is None:
            return None
        return float(kline.get("close", 0) or 0)

    def subscribe(self, callback: Callable[[str], None]) -> None:
        """
        Pub/Sub ile Go servisinden anlık bildirim dinler.
        callback(symbol) → yeni kline geldiğinde çağrılır.

        Not: Ayrı thread'de çalıştır.
        """
        if not self._connected:
            log.warning("RedisBridge.subscribe: bağlantı yok")
            return

        try:
            self._pubsub = self._client.pubsub()
            self._pubsub.subscribe("market:kline_update")
            log.info("RedisBridge: pub/sub dinleniyor...")

            for message in self._pubsub.listen():
                if message["type"] == "message":
                    symbol = message["data"]
                    try:
                        callback(symbol)
                    except Exception as exc:
                        log.warning("RedisBridge callback hata: %s", exc)

        except Exception as exc:
            log.error("RedisBridge.subscribe hata: %s", exc)

    def status(self) -> Dict[str, Any]:
        """Köprü durumu — monitoring için."""
        if not self._connected:
            return {
                "connected": False,
                "redis_klines_available": False,
                "degraded_reason": self.degraded_reason,
                "symbols": {},
            }

        symbol_status = {}
        for sym in SYMBOLS:
            kline = self.get_kline(sym)
            symbol_status[sym] = {
                "available": kline is not None,
                "price": float(kline.get("close", 0)) if kline else None,
            }

        return {
            "connected": True,
            "redis_klines_available": True,
            "redis_url": REDIS_URL,
            "symbols": symbol_status,
        }

    def close(self) -> None:
        if self._pubsub:
            try:
                self._pubsub.unsubscribe()
                self._pubsub.close()
            except OSError as exc:
                log.debug("Redis pubsub close hatasi: %s", exc)
        if self._client:
            try:
                self._client.close()
            except OSError as exc:
                log.debug("Redis client close hatasi: %s", exc)
        self._connected = False
