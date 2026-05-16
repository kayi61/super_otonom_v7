from __future__ import annotations

"""
PositionSizer v5.1
─────────────────────────────────────────────────────────────────────────────
v5   → Slippage + Order Book entegrasyonu (calculate_with_slippage)
v5.1 → 3 Katmanlı Güvenlik Filtresi (validate_and_calculate):
         1. Zaman Senkronizasyonu  : son mum çok eskiyse işlem yok (``data_freshness.max_candle_age_ms``; isteğe ``POSITION_SIZER_MAX_DATA_AGE_MS``)
         2. Order Book Imbalance   : bid/ask < 0.3 → flash crash riski = işlem yok
         3. Fractional Kelly       : ham boyutun %70'i kullan (overfitting koruması)
"""

import logging
import math
import os
import time
from typing import Dict, List, Optional

log = logging.getLogger("super_otonom.position_sizer")

_KELLY_MIN_TRADES = 5
_KELLY_FRACTION = 0.5
_KELLY_MAX = 0.30
_KELLY_FALLBACK = 0.15

# v5.1 — ZAMAN_KAYMASI: son mum yasi (ms); 1h icin data_freshness ile hizali (~3720s).
def _max_data_age_ms() -> float:
    from super_otonom.data_freshness import max_candle_age_ms

    return max_candle_age_ms()
_MIN_BID_IMBALANCE = 0.3  # bid/ask hacim oranı eşiği
_KELLY_SAFETY_MULT = 0.70  # Fractional Kelly çarpanı
_IMBALANCE_DEPTH = 5  # Kaç order book katmanı değerlendirilsin


class PositionSizer:
    """
    v5.1 — Zaman Senkronizasyonu + Imbalance Koruması + Fractional Kelly

    Ana kullanım (v5.1):
        size = sizer.validate_and_calculate(
            symbol, equity, order_book, last_candle_ts,
            volatility=0.01, ai_conf=0.60
        )

    Eski kullanım (geriye uyumlu):
        size = sizer.calculate(symbol, equity, volatility=0.01, ai_conf=0.60)
        size = sizer.calculate_with_slippage(symbol, equity, order_book, ...)
    """

    def __init__(
        self,
        max_position_pct: float = 0.05,
        min_notional: float = 10.0,
        max_leverage: float = 1.0,
        target_vol: float = 0.015,
    ):
        self.max_position_pct = max_position_pct
        self.min_notional = min_notional
        self.max_leverage = max_leverage
        self.target_vol = target_vol
        self._portfolio_weights: Dict[str, float] = {}
        self._trade_log: list = []

    def set_portfolio_weights(self, weights: Dict[str, float]) -> None:
        self._portfolio_weights = weights

    def set_trade_log(self, trade_log: list) -> None:
        self._trade_log = trade_log

    # ── Kelly hesabı ─────────────────────────────────────────────────────────

    def _kelly_fraction(self) -> float:
        """
        Half-Kelly hesabı.
        5'ten az trade: fallback (0.15)
        5+ trade: gerçek kelly [0, KELLY_MAX] aralığında
        """
        recent = self._trade_log[-50:] if self._trade_log else []
        if len(recent) < _KELLY_MIN_TRADES:
            log.debug(
                "Kelly: yetersiz ornek (%d < %d), fallback=%.2f",
                len(recent),
                _KELLY_MIN_TRADES,
                _KELLY_FALLBACK,
            )
            return _KELLY_FALLBACK

        wins = [t.get("pnl", 0) for t in recent if t.get("pnl", 0) > 0]
        losses = [abs(t.get("pnl", 0)) for t in recent if t.get("pnl", 0) <= 0]

        if not wins or not losses:
            return _KELLY_FALLBACK

        win_rate = len(wins) / len(recent)
        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)

        if avg_loss <= 0:
            return _KELLY_FALLBACK

        r = avg_win / avg_loss
        kelly = win_rate - (1 - win_rate) / r
        result = max(0.0, min(kelly * _KELLY_FRACTION, _KELLY_MAX))
        log.debug("Kelly: wr=%.2f r=%.2f raw=%.3f half=%.3f", win_rate, r, kelly, result)
        return result

    # ── Temel boyut hesabı ────────────────────────────────────────────────────

    def calculate(
        self,
        symbol: str,
        equity: float,
        volatility: float = 0.01,
        ai_conf: float = 0.5,
        override_weight: Optional[float] = None,
        step_size: Optional[float] = None,
    ) -> float:
        if equity <= 0:
            return 0.0

        weight = override_weight
        if weight is None:
            n = max(len(self._portfolio_weights), 1)
            weight = self._portfolio_weights.get(symbol, 1.0 / n)
        weight = max(0.01, min(weight, 0.60))

        kelly = self._kelly_fraction()
        conf_scalar = 0.5 + ai_conf * 0.5
        raw = equity * weight * kelly * conf_scalar

        vol = max(volatility, 0.0001)
        vol_scalar = min(1.0, self.target_vol / vol)
        sized = raw * vol_scalar

        n = max(len(self._portfolio_weights), 1)
        weight_ratio = weight / (1.0 / n)
        cap = equity * self.max_position_pct * self.max_leverage * weight_ratio
        final = min(sized, cap)

        if final < self.min_notional:
            log.debug(
                "PositionSizer: size=%.2f < min_notional=%.2f, 0 donuyor",
                final,
                self.min_notional,
            )
            return 0.0

        if step_size and step_size > 0:
            precision = int(abs(math.log10(step_size)))
            return round(math.floor(final / step_size) * step_size, precision)

        return round(final, 4)

    # ── v5.1 YENİLİK: 3 Katmanlı Güvenlik Filtresi ───────────────────────────

    def validate_and_calculate(
        self,
        symbol: str,
        equity: float,
        order_book: Dict[str, List],
        last_candle_ts: float,
        max_candle_age_ms: float | None = None,
        min_bid_imbalance: float = _MIN_BID_IMBALANCE,
        kelly_safety: float = _KELLY_SAFETY_MULT,
        **kwargs,
    ) -> float:
        """
        Ana giriş noktası — 3 katmanlı güvenlik filtresi.

        Katman 1 — Zaman Senkronizasyonu:
          Son mum timestamp'i max_candle_age_ms ms'den eskiyse işlem yok.
          Eski veriyle açılan pozisyon büyük fiyat kayması riski taşır.

        Katman 2 — Order Book Imbalance (Flash Crash Koruması):
          İlk 5 bid/ask katmanının hacim oranı min_bid_imbalance altındaysa
          alıcı derinliği yetersiz → çöküş riski → işlem engellenir.

        Katman 3 — Fractional Kelly (Overfitting Koruması):
          Ham boyutun %70'i (kelly_safety) kullanılır. Gerçek piyasada
          Kelly formülü her zaman aşırı iyimserdir — kırpma zorunludur.

        Args:
            last_candle_ts    : Son mumun ms cinsinden Unix timestamp'i
            max_candle_age_ms : Maksimum izin verilen gecikme (varsayılan: ``data_freshness.max_candle_age_ms``)
            min_bid_imbalance : Minimum bid/ask hacim oranı (varsayılan: 0.30)
            kelly_safety      : Fractional Kelly çarpanı (varsayılan: 0.70)
            **kwargs          : calculate() 'e iletilir (volatility, ai_conf vb.)

        Dönüş: Güvenli pozisyon boyutu (USDT) veya 0.0
        """

        # ── KATMAN 1: Zaman Senkronizasyonu Kontrolü ─────────────────────────
        if max_candle_age_ms is None:
            max_candle_age_ms = _max_data_age_ms()
        current_ts = time.time() * 1000
        ts = float(last_candle_ts)
        if ts < 1e12:
            ts = ts * 1000
        candle_age = current_ts - ts

        if candle_age > max_candle_age_ms:
            log.error(
                "ZAMAN_KAYMASI: symbol=%s | veri=%.0fms gecikmeli (limit=%.0fms) "
                "— islem engellendi.",
                symbol,
                candle_age,
                max_candle_age_ms,
            )
            return 0.0

        # ── KATMAN 2: Emir Defteri Imbalance (Flash Crash Koruması) ──────────
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])

        if not bids or not asks:
            log.warning(
                "ORDER_BOOK_EKSIK: symbol=%s bid veya ask listesi bos — islem engellendi.",
                symbol,
            )
            return 0.0

        bids_vol = sum(float(b[1]) for b in bids[:_IMBALANCE_DEPTH])
        asks_vol = sum(float(a[1]) for a in asks[:_IMBALANCE_DEPTH])
        imbalance = bids_vol / (asks_vol + 1e-9)

        if imbalance < min_bid_imbalance:
            log.warning(
                "FLASH_CRASH_RISKI: symbol=%s | imbalance=%.3f < %.3f "
                "(bid_vol=%.4f ask_vol=%.4f) — Alici derinligi yetersiz, "
                "islem engellendi.",
                symbol,
                imbalance,
                min_bid_imbalance,
                bids_vol,
                asks_vol,
            )
            return 0.0

        log.debug(
            "Imbalance OK: symbol=%s | oran=%.3f bid=%.4f ask=%.4f",
            symbol,
            imbalance,
            bids_vol,
            asks_vol,
        )

        # ── KATMAN 3: Fractional Kelly (Overfitting Koruması) ─────────────────
        raw_size = self.calculate(symbol, equity, **kwargs)

        if raw_size <= 0:
            return 0.0

        # Kelly'nin %70'ini kullan — güvenli mod
        safe_size = round(raw_size * kelly_safety, 2)

        if safe_size < self.min_notional:
            log.debug(
                "FRACTIONAL_KELLY: symbol=%s raw=%.4f * %.0f%% = %.4f < "
                "min_notional=%.2f — sifir donuyor.",
                symbol,
                raw_size,
                kelly_safety * 100,
                safe_size,
                self.min_notional,
            )
            return 0.0

        log.debug(
            "validate_and_calculate OK: symbol=%s | raw=%.4f safe=%.4f (%.0f%% kelly) "
            "| candle_age=%.0fms imbalance=%.3f",
            symbol,
            raw_size,
            safe_size,
            kelly_safety * 100,
            candle_age,
            imbalance,
        )
        return safe_size

    # ── Order Book slippage kontrolü (v5 — geriye uyumlu) ────────────────────

    def calculate_with_slippage(
        self,
        symbol: str,
        equity: float,
        order_book: Dict[str, List[List[float]]],
        max_allowed_slippage: float = 0.001,
        **kwargs,
    ) -> float:
        """
        Emir defteri likidite analizine göre güvenli boyut hesaplar.
        (v5'ten korundu — geriye dönük uyumluluk)
        """
        raw_size = self.calculate(symbol, equity, **kwargs)

        if raw_size <= 0 or not order_book.get("asks"):
            return raw_size

        asks = order_book["asks"]
        best_ask = float(asks[0][0])
        if best_ask <= 0:
            return raw_size

        available_liquidity = 0.0
        total_cost = 0.0

        for level in asks:
            if available_liquidity >= raw_size:
                break
            price = float(level[0])
            volume = float(level[1])
            needed = min(volume, raw_size - available_liquidity)
            available_liquidity += needed
            total_cost += needed * price

        if available_liquidity <= 0:
            log.warning("PositionSizer: order_book bos veya likidite yok, symbol=%s", symbol)
            return 0.0

        avg_price = total_cost / available_liquidity
        actual_slippage = (avg_price - best_ask) / best_ask

        if actual_slippage > max_allowed_slippage:
            scaling_factor = max_allowed_slippage / (actual_slippage + 1e-9)
            adjusted = round(raw_size * scaling_factor, 2)
            log.warning(
                "PositionSizer: slippage=%.4f%% > limit=%.4f%%, boyut kisiliyor "
                "%.4f -> %.4f | symbol=%s",
                actual_slippage * 100,
                max_allowed_slippage * 100,
                raw_size,
                adjusted,
                symbol,
            )
            return adjusted if adjusted >= self.min_notional else 0.0

        log.debug(
            "PositionSizer: slippage=%.4f%% kabul edildi | symbol=%s size=%.4f",
            actual_slippage * 100,
            symbol,
            raw_size,
        )
        return raw_size

    # ── Yardımcı metotlar ─────────────────────────────────────────────────────

    def total_exposure(self, open_positions: Dict) -> float:
        return sum(pos.get("size", 0) for pos in open_positions.values())

    def can_open(
        self,
        new_size: float,
        equity: float,
        open_positions: Dict,
        max_total_pct: float = 0.80,
    ) -> bool:
        current = self.total_exposure(open_positions)
        return (current + new_size) <= equity * max_total_pct
