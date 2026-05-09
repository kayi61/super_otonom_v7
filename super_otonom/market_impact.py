from __future__ import annotations

"""
MarketImpactModel v1.0
─────────────────────────────────────────────────────────────────────────────
Sprint 5 M3 — Amihud illiquidity bazlı market impact modeli

SORUN (önceki durum):
    Büyük emir fiyatı etkiliyor mu? → Bilinmiyordu.
    Slippage sabit range veya volatilite bazlıydı.
    Emir boyutu / piyasa likiditesi ilişkisi yoktu.

ÇÖZÜM:
    Amihud (2002) illiquidity ratio:
        ILLIQ = |return| / volume_usd

    Market impact tahmini:
        impact_pct = sqrt(order_notional / avg_daily_volume) × volatility × lambda

    lambda: piyasa koşuluna göre kalibre edilir (varsayılan 0.1)

Kullanım:
    model = MarketImpactModel()
    impact = model.estimate(
        order_notional=5000,
        avg_daily_volume=1_000_000,
        volatility=0.02,
    )
    # impact.total_pct → toplam etki yüzdesi
    # impact.adjusted_price("buy", 50000) → etki sonrası fiyat
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger("super_otonom.market_impact")

_DEFAULT_LAMBDA     = 0.1    # piyasa etki katsayısı
_DEFAULT_MIN_IMPACT = 0.0001 # minimum %0.01
_DEFAULT_MAX_IMPACT = 0.02   # maksimum %2 — aşırı tahmin önlemi
_HISTORY_SIZE       = 200


@dataclass
class ImpactEstimate:
    """Tek bir emir için market impact tahmini."""
    order_notional:    float
    avg_daily_volume:  float
    volatility:        float
    lambda_:           float
    # Hesaplanan değerler
    participation_rate: float  # order / adv
    amihud_impact_pct:  float  # sqrt(participation) × vol × lambda
    total_pct:          float  # clamp edilmiş toplam etki
    is_large_order:     bool   # participation > %5 → dikkat

    def adjusted_price(self, side: str, price: float) -> float:
        """Market impact sonrası fiyat tahmini."""
        if side == "buy":
            return float(price) * (1 + self.total_pct)
        return float(price) * (1 - self.total_pct)

    def cost_usdt(self, qty: float, price: float) -> float:
        """Market impact maliyeti USDT cinsinden."""
        return qty * float(price) * self.total_pct


class MarketImpactModel:
    """
    Amihud illiquidity bazlı market impact tahmini.

    Kullanım (BotEngine / PositionSizer içinde):
        impact = self.market_impact.estimate(
            order_notional=size,
            avg_daily_volume=analysis.get("avg_volume_usd", 1_000_000),
            volatility=analysis.get("volatility", 0.01),
        )
        if impact.is_large_order:
            log.warning("Büyük emir — market impact yüksek: %.2f%%", impact.total_pct*100)
        adjusted_price = impact.adjusted_price("buy", price)
    """

    def __init__(
        self,
        lambda_: float = _DEFAULT_LAMBDA,
        min_impact: float = _DEFAULT_MIN_IMPACT,
        max_impact: float = _DEFAULT_MAX_IMPACT,
        large_order_threshold: float = 0.05,  # ADV'nin %5'i
    ):
        self._lambda               = lambda_
        self._min_impact           = min_impact
        self._max_impact           = max_impact
        self._large_threshold      = large_order_threshold
        self._history: List[ImpactEstimate] = []
        self._symbol_adv: Dict[str, float]  = {}   # sembol → ortalama günlük hacim

    def estimate(
        self,
        order_notional: float,
        avg_daily_volume: float,
        volatility: float,
        symbol: str = "",
    ) -> ImpactEstimate:
        """
        Market impact tahmini.

        Formül:
            participation_rate = order_notional / max(avg_daily_volume, order_notional)
            amihud_impact = sqrt(participation_rate) × volatility × lambda
            total = clamp(amihud_impact, min_impact, max_impact)
        """
        adv = max(float(avg_daily_volume), float(order_notional), 1.0)
        participation = float(order_notional) / adv
        amihud        = math.sqrt(participation) * float(volatility) * self._lambda
        total         = max(self._min_impact, min(self._max_impact, amihud))
        is_large      = participation > self._large_threshold

        est = ImpactEstimate(
            order_notional=float(order_notional),
            avg_daily_volume=adv,
            volatility=float(volatility),
            lambda_=self._lambda,
            participation_rate=round(participation, 6),
            amihud_impact_pct=round(amihud, 6),
            total_pct=round(total, 6),
            is_large_order=is_large,
        )
        self._history.append(est)
        if len(self._history) > _HISTORY_SIZE:
            self._history = self._history[-_HISTORY_SIZE:]

        if symbol:
            self._symbol_adv[symbol] = adv

        if is_large:
            log.warning(
                "MARKET_IMPACT | %s | participation=%.2f%% > eşik=%.0f%% | "
                "impact=%.4f%% | order=%.0f adv=%.0f",
                symbol or "?", participation * 100,
                self._large_threshold * 100,
                total * 100,
                order_notional, adv,
            )
        else:
            log.debug(
                "MARKET_IMPACT | %s | participation=%.3f%% | impact=%.4f%%",
                symbol or "?", participation * 100, total * 100,
            )
        return est

    def amihud_ratio(
        self,
        returns: List[float],
        volumes_usd: List[float],
    ) -> float:
        """
        Gerçek Amihud illiquidity ratio hesabı.
        Tarihsel mum verisinden hesaplamak için.

            ILLIQ = mean(|r_t| / V_t)

        Yüksek değer → likit değil, büyük emirler büyük etki yapar.
        """
        if not returns or not volumes_usd:
            return 0.0
        pairs = [
            (abs(r), v) for r, v in zip(returns, volumes_usd)
            if v > 0
        ]
        if not pairs:
            return 0.0
        return sum(abs_r / v for abs_r, v in pairs) / len(pairs)

    def snapshot(self) -> Dict:
        if not self._history:
            return {"total_estimates": 0}
        recent = self._history[-10:]
        avg_impact = sum(e.total_pct for e in recent) / len(recent)
        large_count = sum(1 for e in self._history if e.is_large_order)
        return {
            "total_estimates":  len(self._history),
            "large_orders":     large_count,
            "avg_impact_pct":   round(avg_impact * 100, 4),
            "max_impact_pct":   round(max(e.total_pct for e in self._history) * 100, 4),
            "lambda":           self._lambda,
        }
