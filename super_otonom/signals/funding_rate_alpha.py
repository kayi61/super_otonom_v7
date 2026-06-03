"""PROMPT-3.1 — Funding Rate Alpha: derinlemesine funding analizi (Faz 18 feed).

`derivatives_intel` (Faz 18) ``funding_rate`` girdisini zenginleştirir:

1. **Funding history** (8h aralık): 30g ortalama/std, z-score, aşırılık sınıflandırma.
   - funding > +0.05% → aşırı long kalabalığı (short fırsatı).
   - funding < -0.03% → aşırı short (long squeeze olasılığı).
2. **Cross-exchange**: Binance/Bybit/OKX funding farkı, arbitraj fırsatı, yakınsama trendi.
3. **Predicted funding**: order book imbalance'dan bir sonraki funding tahmini.
4. **Cumulative funding**: 7/30g kümülatif taşıma maliyeti (long/short carry).

Tüm fonksiyonlar saftır (ağsız test edilir). ``analyze_funding`` Faz 18 için
``trade_permission`` önerisi üretir: ``abs(z_score) > 2.5 → BLOCK``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# Eşikler (ondalık funding; 0.0005 = %0.05 / aralık)
OVERCROWDED_LONG = 0.0005    # > → aşırı long kalabalığı (short fırsatı)
OVERCROWDED_SHORT = -0.0003  # < → aşırı short (long squeeze olasılığı)
Z_BLOCK_THRESHOLD = 2.5      # |z| > → trade_permission BLOCK

# 8h funding → günde 3, 30 gün ≈ 90 örnek
FUNDING_PER_DAY = 3

EXTREME_LONG = "overcrowded_long"
EXTREME_SHORT = "overcrowded_short"
EXTREME_NEUTRAL = "neutral"


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # NaN ele
    except (TypeError, ValueError):
        return None


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ── 1) Funding history istatistikleri ────────────────────────────────────────


@dataclass(frozen=True)
class FundingStats:
    current: float
    mean_30d: float
    std_30d: float
    z_score: float
    n_samples: int
    extremity: str

    @property
    def is_extreme(self) -> bool:
        return abs(self.z_score) > Z_BLOCK_THRESHOLD


def classify_extremity(rate: float) -> str:
    if rate > OVERCROWDED_LONG:
        return EXTREME_LONG
    if rate < OVERCROWDED_SHORT:
        return EXTREME_SHORT
    return EXTREME_NEUTRAL


def funding_stats(history: Sequence[float], *, current: Optional[float] = None) -> FundingStats:
    """8h funding serisinden 30g ortalama/std + z-score.

    ``current`` verilmezse serinin son elemanı kullanılır. Yetersiz veri →
    z=0, extremity yine ``current`` değerinden sınıflandırılır.
    """
    vals = [f for f in (_coerce_float(x) for x in history) if f is not None]
    cur = current if current is not None else (vals[-1] if vals else 0.0)
    cur = float(cur)
    n = len(vals)
    if n < 2:
        return FundingStats(cur, cur if n else 0.0, 0.0, 0.0, n, classify_extremity(cur))
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    # Tüm-eşit değerlerde float yuvarlama ~1e-20 std verir → 0'a sabitle (3.10/3.12 uyumu).
    std = math.sqrt(var) if var > 1e-24 else 0.0
    z = (cur - mean) / std if std > 1e-12 else 0.0
    return FundingStats(cur, float(mean), float(std), float(z), n, classify_extremity(cur))


# ── 2) Cross-exchange karşılaştırma ──────────────────────────────────────────


@dataclass(frozen=True)
class CrossExchangeFunding:
    rates: Dict[str, float]
    max_spread: float          # en yüksek - en düşük funding
    high_exchange: str
    low_exchange: str
    arb_opportunity: bool
    convergence_trend: str     # converging | diverging | flat | unknown

    @property
    def mean_rate(self) -> float:
        return sum(self.rates.values()) / len(self.rates) if self.rates else 0.0


def cross_exchange_analysis(
    per_exchange: Dict[str, Any],
    *,
    arb_threshold: float = 0.0003,
    prev_spread: Optional[float] = None,
) -> CrossExchangeFunding:
    """Binance vs Bybit vs OKX funding farkı + arbitraj + yakınsama trendi.

    ``arb_threshold``: funding farkı bu eşiği aşarsa arbitraj fırsatı.
    ``prev_spread`` verilirse yakınsama/uzaklaşma trendi hesaplanır.
    """
    rates = {
        str(k).lower(): f
        for k, v in (per_exchange or {}).items()
        if (f := _coerce_float(v)) is not None
    }
    if len(rates) < 2:
        return CrossExchangeFunding(rates, 0.0, "", "", False, "unknown")
    high_ex = max(rates, key=lambda k: rates[k])
    low_ex = min(rates, key=lambda k: rates[k])
    spread = rates[high_ex] - rates[low_ex]
    arb = spread >= arb_threshold
    trend = "unknown"
    if prev_spread is not None:
        if spread < prev_spread - 1e-9:
            trend = "converging"
        elif spread > prev_spread + 1e-9:
            trend = "diverging"
        else:
            trend = "flat"
    return CrossExchangeFunding(rates, float(spread), high_ex, low_ex, arb, trend)


# ── 3) Predicted funding (order book imbalance'dan) ──────────────────────────


def predict_next_funding(
    current_funding: float,
    *,
    order_book_imbalance: float = 0.0,
    premium_pct: Optional[float] = None,
    sensitivity: float = 0.0004,
) -> float:
    """Bir sonraki funding tahmini.

    ``order_book_imbalance`` ∈ [-1, 1] (pozitif = bid baskısı → funding yükselir).
    ``premium_pct`` (mark-index)/index verilirse funding ona doğru çekilir.
    """
    imb = _clamp(float(order_book_imbalance), -1.0, 1.0)
    pred = float(current_funding) + sensitivity * imb
    if premium_pct is not None:
        # funding kısmen premium'a yakınsar
        pred = 0.6 * pred + 0.4 * _clamp(float(premium_pct), -0.01, 0.01)
    return float(pred)


# ── 4) Cumulative funding / carry ────────────────────────────────────────────


@dataclass(frozen=True)
class CumulativeFunding:
    cum_7d: float
    cum_30d: float
    long_carry_cost_7d: float    # pozitif funding → long maliyeti
    short_carry_cost_7d: float
    long_carry_cost_30d: float
    short_carry_cost_30d: float


def cumulative_funding(history: Sequence[float], *, notional: float = 0.0) -> CumulativeFunding:
    """7/30 günlük kümülatif funding + long/short taşıma maliyeti (USD).

    Pozitif funding longlardan kesilir → long_carry_cost pozitif (maliyet).
    """
    vals = [f for f in (_coerce_float(x) for x in history) if f is not None]
    n7 = FUNDING_PER_DAY * 7
    n30 = FUNDING_PER_DAY * 30
    cum7 = sum(vals[-n7:])
    cum30 = sum(vals[-n30:])
    notion = float(notional)
    return CumulativeFunding(
        cum_7d=float(cum7),
        cum_30d=float(cum30),
        long_carry_cost_7d=float(cum7 * notion),
        short_carry_cost_7d=float(-cum7 * notion),
        long_carry_cost_30d=float(cum30 * notion),
        short_carry_cost_30d=float(-cum30 * notion),
    )


# ── Birleşik analiz ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FundingAnalysis:
    stats: FundingStats
    cross: Optional[CrossExchangeFunding]
    predicted_funding: Optional[float]
    cumulative: Optional[CumulativeFunding]
    alpha_bias: float          # -1 (bearish/short fırsatı) .. +1 (bullish/long fırsatı)
    risk_score: float          # 0..1
    block: bool                # |z| > 2.5
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "funding_current": self.stats.current,
            "funding_mean_30d": self.stats.mean_30d,
            "funding_std_30d": self.stats.std_30d,
            "funding_z_score": self.stats.z_score,
            "funding_extremity": self.stats.extremity,
            "funding_n_samples": self.stats.n_samples,
            "funding_alpha_bias": self.alpha_bias,
            "funding_risk_score": self.risk_score,
            "funding_block": self.block,
            "funding_reasons": list(self.reasons),
        }
        if self.predicted_funding is not None:
            out["funding_predicted_next"] = self.predicted_funding
        if self.cross is not None:
            out["funding_cross_exchange"] = {
                "rates": self.cross.rates,
                "max_spread": self.cross.max_spread,
                "high_exchange": self.cross.high_exchange,
                "low_exchange": self.cross.low_exchange,
                "arb_opportunity": self.cross.arb_opportunity,
                "convergence_trend": self.cross.convergence_trend,
            }
        if self.cumulative is not None:
            out["funding_cum_7d"] = self.cumulative.cum_7d
            out["funding_cum_30d"] = self.cumulative.cum_30d
            out["funding_long_carry_7d"] = self.cumulative.long_carry_cost_7d
            out["funding_short_carry_7d"] = self.cumulative.short_carry_cost_7d
        return out


def analyze_funding(
    history: Sequence[float],
    *,
    current: Optional[float] = None,
    per_exchange: Optional[Dict[str, Any]] = None,
    order_book_imbalance: Optional[float] = None,
    premium_pct: Optional[float] = None,
    notional: float = 0.0,
    prev_cross_spread: Optional[float] = None,
) -> FundingAnalysis:
    """Tüm funding metriklerini birleştirir; alpha bias + risk + BLOCK önerisi.

    Alpha bias işareti: aşırı long kalabalığı (yüksek pozitif funding) → short
    fırsatı (negatif bias); aşırı short → long squeeze (pozitif bias).
    """
    stats = funding_stats(history, current=current)

    cross = cross_exchange_analysis(per_exchange, prev_spread=prev_cross_spread) if per_exchange else None
    predicted = (
        predict_next_funding(
            stats.current,
            order_book_imbalance=order_book_imbalance or 0.0,
            premium_pct=premium_pct,
        )
        if (order_book_imbalance is not None or premium_pct is not None)
        else None
    )
    cumulative = cumulative_funding(history, notional=notional) if history else None

    reasons: List[str] = []

    # Aşırılık → alpha bias (kontraryan: kalabalığın tersi)
    alpha_bias = 0.0
    if stats.extremity == EXTREME_LONG:
        alpha_bias = -_clamp(0.4 + abs(stats.z_score) * 0.2, 0.0, 1.0)
        reasons.append(
            f"Funding {stats.current * 100:.3f}% aşırı long kalabalığı → short fırsatı"
        )
    elif stats.extremity == EXTREME_SHORT:
        alpha_bias = _clamp(0.4 + abs(stats.z_score) * 0.2, 0.0, 1.0)
        reasons.append(
            f"Funding {stats.current * 100:.3f}% aşırı short → long squeeze olasılığı"
        )

    # Risk: z-score büyüklüğü
    risk_score = _clamp(abs(stats.z_score) / 4.0, 0.0, 1.0)

    block = stats.is_extreme
    if block:
        reasons.append(f"Funding z-score {stats.z_score:.2f} (|z|>{Z_BLOCK_THRESHOLD}) → BLOCK")

    if cross is not None and cross.arb_opportunity:
        reasons.append(
            f"Cross-exchange funding arb: {cross.high_exchange} vs {cross.low_exchange} "
            f"spread {cross.max_spread * 100:.3f}%"
        )

    return FundingAnalysis(
        stats=stats,
        cross=cross,
        predicted_funding=predicted,
        cumulative=cumulative,
        alpha_bias=float(alpha_bias),
        risk_score=float(risk_score),
        block=block,
        reasons=reasons,
    )


__all__ = [
    "EXTREME_LONG",
    "EXTREME_NEUTRAL",
    "EXTREME_SHORT",
    "OVERCROWDED_LONG",
    "OVERCROWDED_SHORT",
    "Z_BLOCK_THRESHOLD",
    "CrossExchangeFunding",
    "CumulativeFunding",
    "FundingAnalysis",
    "FundingStats",
    "analyze_funding",
    "classify_extremity",
    "cross_exchange_analysis",
    "cumulative_funding",
    "funding_stats",
    "predict_next_funding",
]
