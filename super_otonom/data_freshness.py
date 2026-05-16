"""Mum yaş eşikleri — STALE_DATA, ZAMAN_KAYMASI ve Redis kline yaşı (aynı TF tabanı).

Ana strateji: eşikleri **burada** topla; ``TIMEFRAME`` / ``EXCHANGE_TIMEFRAME`` değişince
yalnız bu modülü ve (Redis için) ``REDIS_KLINE_TIMEFRAME`` / ``REDIS_KLINE_MAX_AGE_MS`` ortamını güncelle.
"""

from __future__ import annotations

import math
import os
import statistics
from typing import Any, Dict, List, Optional

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


# Eski backtester varsayılanı: 252 işlem günü × 24 saat × 12 adet 5m/saat (hisse saatleri).
LEGACY_PERIODS_PER_YEAR_STOCK_5M: float = 252.0 * 24.0 * 12.0


def periods_per_year_from_timeframe(tf: str | None = None) -> float:
    """Kripto 7/24: yıllık bar sayısı = 365.25 gün × 24 saat / bar süresi (Sharpe annualize)."""
    key = (tf or _primary_timeframe()).strip().lower()
    sec = float(_TIMEFRAME_SEC.get(key, 3600))
    if sec <= 0:
        sec = 3600.0
    return 365.25 * 24.0 * 3600.0 / sec


def infer_timeframe_from_candles(
    candles: List[Dict[str, Any]],
    *,
    min_pairs: int = 3,
) -> Optional[str]:
    """Mum ``timestamp`` aralığından en yakın bilinen timeframe (ör. ``5m``)."""
    ts: List[float] = []
    for c in candles:
        raw = c.get("timestamp")
        if raw is None:
            continue
        try:
            ts.append(float(raw))
        except (TypeError, ValueError):
            continue
    if len(ts) < min_pairs + 1:
        return None
    ts_sorted = sorted(ts)
    deltas = [ts_sorted[i + 1] - ts_sorted[i] for i in range(len(ts_sorted) - 1)]
    deltas = [d for d in deltas if d > 0]
    if len(deltas) < min_pairs:
        return None
    med = float(statistics.median(deltas))
    med_sec = med / 1000.0 if med > 60_000.0 else med
    best_tf: Optional[str] = None
    best_err = float("inf")
    for tf, sec in _TIMEFRAME_SEC.items():
        err = abs(med_sec - float(sec)) / float(sec)
        if err < best_err:
            best_err = err
            best_tf = tf
    if best_tf is None or best_err > 0.12:
        return None
    return best_tf


def resolve_periods_per_year(
    *,
    periods_per_year: Optional[float] = None,
    timeframe: Optional[str] = None,
    candles: Optional[List[Dict[str, Any]]] = None,
) -> float:
    """Sharpe annualize için yıllık bar sayısı — açık TF > mum çıkarımı > ortam varsayılanı."""
    if periods_per_year is not None:
        return float(periods_per_year)
    if timeframe:
        return periods_per_year_from_timeframe(timeframe)
    if candles:
        inferred = infer_timeframe_from_candles(candles)
        if inferred:
            return periods_per_year_from_timeframe(inferred)
    return periods_per_year_from_timeframe()


def sharpe_annualize_factor_vs_legacy(tf: str) -> float:
    """Eski ``LEGACY_PERIODS_PER_YEAR_STOCK_5M`` ile doğru TF arasındaki Sharpe çarpanı (√ppy oranı)."""
    ppy_new = periods_per_year_from_timeframe(tf)
    if ppy_new <= 0 or LEGACY_PERIODS_PER_YEAR_STOCK_5M <= 0:
        return 1.0
    return math.sqrt(ppy_new / LEGACY_PERIODS_PER_YEAR_STOCK_5M)


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
