"""
Kill-Switch (sert sınırlar) — borsa CircuitBreaker'ından ayrı: işlem ve acil durdurma.

- exchange_async.CircuitBreaker: sadece OHLCV/HTTP hata izolasyonu + retry
- burada: fiyat sapması, emir frekansı, (isteğe bağlı) global env ile trading dondurma
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

from super_otonom.config import GENERAL


def _f(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return int(default)


def default_hard_limit_config() -> dict:
    """
    KILL_MAX_ORDERS_PER_SEC: pencere içinde (saniye) izin verilen max emir (BUY+SELL sayımı)
    KILL_ORDER_WINDOW_SEC: pencere genişliği
    KILL_MAX_PRICE_JUMP_PCT: ardışık tick'lerde kapanışa göre max sapma; aşım → price_spike
    """
    mpm = max(1, int(GENERAL.get("max_orders_per_min", 2)))
    default_mps = max(1, mpm // 2 + 1)  # makul tavan; env ile override
    return {
        "max_orders": _i("KILL_MAX_ORDERS_PER_SEC", default_mps),
        "window_sec": _f("KILL_ORDER_WINDOW_SEC", "1.0"),
        "max_price_jump_pct": _f("KILL_MAX_PRICE_JUMP_PCT", "0.05"),
    }


class HardLimitTracker:
    """
    Anomali: çok hızlı emir ve ardışık fiyat sıçraması. Tetikte çağıran `RiskManager.trigger_emergency` çağırır.
    """

    def __init__(
        self,
        max_orders: int = 5,
        window_sec: float = 1.0,
        max_price_jump_pct: float = 0.05,
    ) -> None:
        self._max_orders = max(1, int(max_orders))
        self._window = max(0.05, float(window_sec))
        self._max_jump = max(0.001, float(max_price_jump_pct))
        self._order_times: Deque[float] = deque()
        self._last_close: Dict[str, float] = {}

    @classmethod
    def from_config(cls) -> "HardLimitTracker":
        c = default_hard_limit_config()
        return cls(
            max_orders=c["max_orders"],
            window_sec=c["window_sec"],
            max_price_jump_pct=c["max_price_jump_pct"],
        )

    def _prune_orders(self) -> None:
        now = time.time()
        while self._order_times and now - self._order_times[0] > self._window:
            self._order_times.popleft()

    def can_submit_order(self) -> Optional[str]:
        """
        Yeni emir eklemeden önce. None → serbest, aksi halde neden kodu.
        """
        self._prune_orders()
        if len(self._order_times) >= self._max_orders:
            return "order_rate_exceeded"
        return None

    def record_order(self) -> None:
        self._prune_orders()
        self._order_times.append(time.time())

    def check_price_tick(self, symbol: str, price: float) -> Optional[str]:
        """
        Ardışık fiyat: önceki kapanışa göre aşırı sapma.
        """
        p = float(price)
        if p <= 0:
            return None
        prev = self._last_close.get(symbol)
        self._last_close[symbol] = p
        if prev is None or prev <= 0:
            return None
        rel = abs(p - prev) / prev
        if rel > self._max_jump:
            return "price_spike"
        return None

    def status_line(self) -> dict:
        self._prune_orders()
        return {
            "orders_in_window": len(self._order_times),
            "order_limit": self._max_orders,
            "window_sec": self._window,
            "max_price_jump_pct": self._max_jump,
        }


# ══ Rate-Limit fırtınası (429) — üst üste gelince Kill-Switch ══


def is_ratelimit_error(exc: BaseException) -> bool:
    """
    Borsa / HTTP 429, 418, ccxt DDoSProtection vb.
    """
    c = getattr(exc, "code", None)
    if c in (429, 418):
        return True
    name = type(exc).__name__
    if "DDoS" in name or "RateLimit" in name:
        return True
    s = str(exc).lower()
    if "too many requests" in s or "banned" in s:
        return True
    if "429" in s and ("error" in s or "code" in s or "http" in s):
        return True
    if " 429" in s or s.startswith("429"):
        return True
    return False


class RateLimitStormTracker:
    """
    Peş peşe rate-limit (OK olmayan) cevabı: main_loop `poll_trip` ile rate_limit_storm.
    Başarılı HTTP, sayacı sıfırlar.
    """

    def __init__(self, max_consecutive: int = 5) -> None:
        self._max = max(2, int(max_consecutive))
        self._streak = 0

    @classmethod
    def from_config(cls) -> "RateLimitStormTracker":
        n = _i("RATE_LIMIT_STORM_CONSEC", 5)
        return cls(max_consecutive=n)

    def on_success(self) -> None:
        self._streak = 0

    def on_ratelimit(self) -> None:
        self._streak += 1

    def poll_trip(self) -> Optional[str]:
        if self._streak >= self._max:
            return "rate_limit_storm"
        return None

    def status_dict(self) -> dict:
        return {
            "rl_streak": self._streak,
            "rl_trip": self._max,
        }


_rl_storm: Optional[RateLimitStormTracker] = None


def get_rate_limit_storm_tracker() -> RateLimitStormTracker:
    global _rl_storm
    if _rl_storm is None:
        _rl_storm = RateLimitStormTracker.from_config()
    return _rl_storm


def apply_storm_trip_to_risk(risk: Any) -> bool:
    """
    429 fırtınası eşiği aşıldıysa `risk.trigger_emergency('rate_limit_storm')`.
    Dönüş: yeni (önceden yok) acil uygulandıysa True (ana döngü log için).
    """
    trip = get_rate_limit_storm_tracker().poll_trip()
    if trip is None:
        return False
    was = bool(getattr(risk, "emergency_stop", False))
    if hasattr(risk, "trigger_emergency"):
        risk.trigger_emergency(trip, silent=True)
    return not was
