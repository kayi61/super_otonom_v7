"""Mum yaş eşikleri — STALE_DATA, ZAMAN_KAYMASI ve Redis kline yaşı (aynı TF tabanı).

Ana strateji: eşikleri **burada** topla; ``TIMEFRAME`` / ``EXCHANGE_TIMEFRAME`` değişince
yalnız bu modülü ve (Redis için) ``REDIS_KLINE_TIMEFRAME`` / ``REDIS_KLINE_MAX_AGE_MS`` ortamını güncelle.
"""

from __future__ import annotations

import os

_TIMEFRAME_SEC: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


def _primary_timeframe() -> str:
    return os.getenv("EXCHANGE_TIMEFRAME", os.getenv("TIMEFRAME", "1h")).strip().lower()


def stale_threshold_sec() -> int:
    """Son mum zamanı ile şimdi arasındaki üst yaş (sn). ``STALE_DATA`` ile uyumlu."""
    base = int(os.getenv("STALE_DATA_THRESHOLD_SEC", "300"))
    buf = int(os.getenv("STALE_DATA_TIMEFRAME_BUFFER_SEC", "120"))
    return max(base, _TIMEFRAME_SEC.get(_primary_timeframe(), 3600) + buf)


def max_candle_age_ms() -> float:
    """``position_sizer`` ZAMAN_KAYMASI üst sınırı (ms) — ``stale_threshold_sec`` ile aynı cap."""
    raw = os.getenv("POSITION_SIZER_MAX_DATA_AGE_MS", "").strip()
    if raw:
        return float(raw)
    return float(stale_threshold_sec() * 1000)


def _redis_kline_timeframe() -> str:
    return os.getenv("REDIS_KLINE_TIMEFRAME", "5m").strip().lower()


def redis_kline_max_age_ms() -> float:
    """Redis ``market:*:kline_*`` JSON ``updated_at`` için üst yaş (ms).

    Go köprüsü 5m mum yazıyorsa varsayılan ``REDIS_KLINE_TIMEFRAME=5m`` + buffer; sabit 15 sn
    kullanmak suni ``None`` / OHLCV düşüşü üretirdi. İnce ayar: ``REDIS_KLINE_MAX_AGE_MS``.
    """
    raw = os.getenv("REDIS_KLINE_MAX_AGE_MS", "").strip()
    if raw:
        return float(raw)
    buf = int(os.getenv("REDIS_KLINE_TIMEFRAME_BUFFER_SEC", "90"))
    sec = _TIMEFRAME_SEC.get(_redis_kline_timeframe(), 300) + buf
    return float(sec * 1000)
