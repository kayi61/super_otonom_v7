"""Ortak mum üreticileri (scaling testleri)."""
from __future__ import annotations

from typing import List


def mk_candle(
    i: int,
    close: float,
    *,
    o: float | None = None,
    h: float | None = None,
    low: float | None = None,
    vol: float = 1000.0,
) -> dict:
    c = float(close)
    o = c - 0.01 if o is None else o
    hi = c + 0.02 if h is None else h
    lo = c - 0.02 if low is None else low
    return {
        "open": o,
        "high": hi,
        "low": lo,
        "close": c,
        "volume": vol,
        "timestamp": float(i * 60_000),
    }


def mk_series_uptrend(n: int) -> List[dict]:
    base = 10_000.0
    return [mk_candle(i, base + i * 3.0) for i in range(n)]
