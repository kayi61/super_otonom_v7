"""PROMPT-3.2 — Open Interest & Liquidation Map: türev piyasa derinlik analizi.

`derivatives_intel` (Faz 18) ``open_interest`` / ``liquidation_levels`` /
``long_short_ratio`` alanlarını zenginleştirir.

1. **Open Interest analizi** (`analyze_oi`):
   - OI↑ + Fiyat↑ → trend güçleniyor (new money in)
   - OI↑ + Fiyat↓ → short buildup (squeeze riski)
   - OI↓ + Fiyat↓ → long capitulation
   - OI↓ + Fiyat↑ → short covering (sürdürülebilir değil)
   - OI değişim hızı (1h/4h/24h delta)
2. **Liquidation haritası** (`analyze_liquidation_map`):
   - $100M+ yoğunluklu fiyat seviyeleri (cluster)
   - Magnet effect (fiyat en yakın büyük cluster'a çekilir)
   - Cascade liquidation risk
3. **Long/Short derinlemesine** (`analyze_long_short`):
   - Top trader vs global L/S, retail vs whale ayrımı
   - Crowded trade (>70% tek tarafa yığılma)
4. **Basis & Contango/Backwardation** (`analyze_basis`):
   - Futures premium/discount, quarterly vs perp, basis trade fırsatı

Tüm fonksiyonlar saftır (ağsız test edilir).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── Eşikler ──────────────────────────────────────────────────────────────────
OI_CHANGE_EPS = 0.005           # |ΔOI| < %0.5 → nötr
PRICE_CHANGE_EPS = 0.001        # |ΔP| < %0.1 → nötr
LIQ_CLUSTER_MIN_USD = 100_000_000.0   # $100M+ yoğunluk
CROWDED_THRESHOLD = 0.70        # tek tarafta > %70 → crowded
MAGNET_MAX_DIST = 0.05          # cluster %5 içinde → magnet etkisi
CASCADE_NEAR_DIST = 0.02        # %2 içindeki liq → cascade riski

# OI rejimleri
OI_TREND_STRENGTHENING = "trend_strengthening"   # new money in (bullish)
OI_SHORT_BUILDUP = "short_buildup"               # squeeze riski
OI_LONG_CAPITULATION = "long_capitulation"
OI_SHORT_COVERING = "short_covering"             # sürdürülebilir değil
OI_NEUTRAL = "neutral"

# Vade yapısı
CONTANGO = "contango"
BACKWARDATION = "backwardation"
FLAT_STRUCTURE = "flat"


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


# ── 1) Open Interest analizi ─────────────────────────────────────────────────


@dataclass(frozen=True)
class OiRegime:
    regime: str
    oi_change_pct: float
    price_change_pct: float
    velocity_1h: Optional[float]
    velocity_4h: Optional[float]
    velocity_24h: Optional[float]
    squeeze_risk: bool          # short_buildup → True

    @property
    def is_bullish(self) -> bool:
        return self.regime == OI_TREND_STRENGTHENING


def classify_oi_regime(oi_change_pct: float, price_change_pct: float) -> str:
    """OI × fiyat değişim yönüne göre rejim."""
    oi_up = oi_change_pct > OI_CHANGE_EPS
    oi_dn = oi_change_pct < -OI_CHANGE_EPS
    p_up = price_change_pct > PRICE_CHANGE_EPS
    p_dn = price_change_pct < -PRICE_CHANGE_EPS
    if oi_up and p_up:
        return OI_TREND_STRENGTHENING
    if oi_up and p_dn:
        return OI_SHORT_BUILDUP
    if oi_dn and p_dn:
        return OI_LONG_CAPITULATION
    if oi_dn and p_up:
        return OI_SHORT_COVERING
    return OI_NEUTRAL


def analyze_oi(
    oi_change_pct: float,
    price_change_pct: float,
    *,
    velocity_1h: Optional[float] = None,
    velocity_4h: Optional[float] = None,
    velocity_24h: Optional[float] = None,
) -> OiRegime:
    regime = classify_oi_regime(float(oi_change_pct), float(price_change_pct))
    return OiRegime(
        regime=regime,
        oi_change_pct=float(oi_change_pct),
        price_change_pct=float(price_change_pct),
        velocity_1h=velocity_1h,
        velocity_4h=velocity_4h,
        velocity_24h=velocity_24h,
        squeeze_risk=(regime == OI_SHORT_BUILDUP),
    )


# ── 2) Liquidation haritası ──────────────────────────────────────────────────


@dataclass(frozen=True)
class LiquidationCluster:
    price: float
    notional_usd: float
    side: str  # long | short | unknown
    distance_pct: float


@dataclass(frozen=True)
class LiquidationMap:
    clusters: List[LiquidationCluster]
    magnet_target: Optional[float]      # en yakın büyük cluster fiyatı
    magnet_distance_pct: Optional[float]
    cascade_risk: float                 # 0..1
    total_near_usd: float               # %2 içindeki toplam liq

    @property
    def has_magnet(self) -> bool:
        return self.magnet_target is not None


def parse_liquidation_levels(levels: Any, ref_price: float) -> List[LiquidationCluster]:
    """Coinglass/CoinAnk benzeri liquidation level listesini normalize eder."""
    out: List[LiquidationCluster] = []
    if not isinstance(levels, (list, tuple)) or ref_price <= 0:
        return out
    for row in levels:
        if not isinstance(row, dict):
            continue
        px = _coerce_float(row.get("price") or row.get("px") or row.get("level"))
        usd = _coerce_float(
            row.get("notional_usd") or row.get("notional") or row.get("usd")
            or row.get("size_usd") or row.get("size") or row.get("amount")
        )
        if px is None or usd is None or px <= 0 or usd < 0:
            continue
        side = str(row.get("side", "unknown")).lower()
        out.append(
            LiquidationCluster(
                price=px,
                notional_usd=usd,
                side=side if side in ("long", "short") else "unknown",
                distance_pct=(px - ref_price) / ref_price,
            )
        )
    return out


def analyze_liquidation_map(
    levels: Any,
    ref_price: float,
    *,
    cluster_min_usd: float = LIQ_CLUSTER_MIN_USD,
) -> LiquidationMap:
    """$100M+ cluster'lar + magnet hedefi + cascade riski."""
    clusters = parse_liquidation_levels(levels, ref_price)
    big = [c for c in clusters if c.notional_usd >= cluster_min_usd]

    magnet_target: Optional[float] = None
    magnet_dist: Optional[float] = None
    # En yakın büyük cluster (magnet etkisi)
    near_big = [c for c in big if abs(c.distance_pct) <= MAGNET_MAX_DIST]
    if near_big:
        m = min(near_big, key=lambda c: abs(c.distance_pct))
        magnet_target = m.price
        magnet_dist = m.distance_pct

    # Cascade riski: %2 içindeki toplam liq / büyük cluster eşiği
    near = [c for c in clusters if abs(c.distance_pct) <= CASCADE_NEAR_DIST]
    total_near = sum(c.notional_usd for c in near)
    cascade = _clamp01(total_near / max(cluster_min_usd * 2.0, 1.0))

    return LiquidationMap(
        clusters=clusters,
        magnet_target=magnet_target,
        magnet_distance_pct=magnet_dist,
        cascade_risk=float(cascade),
        total_near_usd=float(total_near),
    )


# ── 3) Long/Short derinlemesine ──────────────────────────────────────────────


@dataclass(frozen=True)
class LongShortAnalysis:
    top_trader_ratio: Optional[float]
    global_ratio: Optional[float]
    long_pct: Optional[float]            # 0..1
    crowded_side: str                    # long | short | none
    crowded_pct: float                   # max(long_pct, short_pct)
    is_crowded: bool                     # > %70
    retail_whale_divergence: bool        # retail vs top trader ters yön

    @property
    def divergence(self) -> bool:
        return self.retail_whale_divergence


def _ratio_to_long_pct(ratio: Optional[float]) -> Optional[float]:
    """L/S oranını long yüzdesine çevirir: ratio = long/short → long/(long+short)."""
    if ratio is None or ratio < 0:
        return None
    return ratio / (1.0 + ratio)


def analyze_long_short(
    *,
    top_trader_ratio: Optional[float] = None,
    global_ratio: Optional[float] = None,
    long_pct: Optional[float] = None,
    crowded_threshold: float = CROWDED_THRESHOLD,
) -> LongShortAnalysis:
    """Top trader / global L/S + crowded trade + retail-whale divergence."""
    lp = long_pct if long_pct is not None else _ratio_to_long_pct(
        global_ratio if global_ratio is not None else top_trader_ratio
    )
    crowded_side = "none"
    crowded_pct = 0.0
    is_crowded = False
    if lp is not None:
        sp = 1.0 - lp
        crowded_pct = max(lp, sp)
        is_crowded = crowded_pct > crowded_threshold
        crowded_side = "long" if lp >= sp else "short"

    # Retail (global) vs whale (top trader) ters yön → divergence
    divergence = False
    if top_trader_ratio is not None and global_ratio is not None:
        tt_long = (top_trader_ratio >= 1.0)
        gl_long = (global_ratio >= 1.0)
        divergence = tt_long != gl_long

    return LongShortAnalysis(
        top_trader_ratio=top_trader_ratio,
        global_ratio=global_ratio,
        long_pct=lp,
        crowded_side=crowded_side,
        crowded_pct=float(crowded_pct),
        is_crowded=is_crowded,
        retail_whale_divergence=divergence,
    )


# ── 4) Basis & Contango/Backwardation ────────────────────────────────────────


@dataclass(frozen=True)
class BasisAnalysis:
    basis_pct: Optional[float]           # (futures - spot) / spot
    structure: str                       # contango | backwardation | flat
    perp_basis_pct: Optional[float]
    quarterly_basis_pct: Optional[float]
    term_spread_pct: Optional[float]     # quarterly - perp
    basis_trade_opportunity: bool


def analyze_basis(
    *,
    spot: Optional[float] = None,
    perp_price: Optional[float] = None,
    quarterly_price: Optional[float] = None,
    flat_eps: float = 0.0005,
    arb_threshold: float = 0.01,
) -> BasisAnalysis:
    """Futures premium/discount + vade yapısı + basis trade fırsatı."""
    def _basis(fut: Optional[float]) -> Optional[float]:
        if spot is None or fut is None or spot <= 0:
            return None
        return (fut - spot) / spot

    perp_basis = _basis(perp_price)
    q_basis = _basis(quarterly_price)
    # Birincil basis: quarterly varsa o, yoksa perp
    primary = q_basis if q_basis is not None else perp_basis

    structure = FLAT_STRUCTURE
    if primary is not None:
        if primary > flat_eps:
            structure = CONTANGO
        elif primary < -flat_eps:
            structure = BACKWARDATION

    term_spread = None
    if q_basis is not None and perp_basis is not None:
        term_spread = q_basis - perp_basis

    # Basis trade fırsatı: |term_spread| veya |quarterly basis| yüksek
    opp = False
    if term_spread is not None and abs(term_spread) >= arb_threshold:
        opp = True
    elif q_basis is not None and abs(q_basis) >= arb_threshold:
        opp = True

    return BasisAnalysis(
        basis_pct=primary,
        structure=structure,
        perp_basis_pct=perp_basis,
        quarterly_basis_pct=q_basis,
        term_spread_pct=term_spread,
        basis_trade_opportunity=opp,
    )


# ── Birleşik analiz ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MarketStructure:
    oi: Optional[OiRegime]
    liquidation: Optional[LiquidationMap]
    long_short: Optional[LongShortAnalysis]
    basis: Optional[BasisAnalysis]
    alpha_bias: float          # -1..1
    risk_score: float          # 0..1
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ms_alpha_bias": self.alpha_bias,
            "ms_risk_score": self.risk_score,
            "ms_reasons": list(self.reasons),
        }
        if self.oi is not None:
            out["oi_regime"] = self.oi.regime
            out["oi_change_pct"] = self.oi.oi_change_pct
            out["oi_squeeze_risk"] = self.oi.squeeze_risk
            out["oi_velocity"] = {
                "1h": self.oi.velocity_1h,
                "4h": self.oi.velocity_4h,
                "24h": self.oi.velocity_24h,
            }
        if self.liquidation is not None:
            out["liq_magnet_target"] = self.liquidation.magnet_target
            out["liq_magnet_distance_pct"] = self.liquidation.magnet_distance_pct
            out["liq_cascade_risk"] = self.liquidation.cascade_risk
            out["liq_cluster_count"] = len(self.liquidation.clusters)
            out["liq_total_near_usd"] = self.liquidation.total_near_usd
        if self.long_short is not None:
            out["ls_crowded_side"] = self.long_short.crowded_side
            out["ls_crowded_pct"] = self.long_short.crowded_pct
            out["ls_is_crowded"] = self.long_short.is_crowded
            out["ls_divergence"] = self.long_short.retail_whale_divergence
        if self.basis is not None:
            out["basis_pct"] = self.basis.basis_pct
            out["basis_structure"] = self.basis.structure
            out["basis_term_spread_pct"] = self.basis.term_spread_pct
            out["basis_trade_opportunity"] = self.basis.basis_trade_opportunity
        return out


# OI rejim → (alpha bias, risk) eşlemleri
_OI_ALPHA = {
    OI_TREND_STRENGTHENING: 0.5,
    OI_SHORT_BUILDUP: -0.2,        # squeeze riski ama short buildup bearish-ish
    OI_LONG_CAPITULATION: -0.4,
    OI_SHORT_COVERING: 0.1,        # sürdürülebilir değil → zayıf pozitif
    OI_NEUTRAL: 0.0,
}
_OI_RISK = {
    OI_SHORT_BUILDUP: 0.55,
    OI_LONG_CAPITULATION: 0.45,
    OI_SHORT_COVERING: 0.30,
    OI_TREND_STRENGTHENING: 0.15,
    OI_NEUTRAL: 0.20,
}


def analyze_market_structure(
    *,
    oi: Optional[OiRegime] = None,
    liquidation: Optional[LiquidationMap] = None,
    long_short: Optional[LongShortAnalysis] = None,
    basis: Optional[BasisAnalysis] = None,
) -> MarketStructure:
    """Tüm derinlik metriklerini alpha bias + risk + reasons'a indirger."""
    reasons: List[str] = []
    alpha = 0.0
    risk = 0.0
    n = 0

    if oi is not None:
        alpha += _OI_ALPHA.get(oi.regime, 0.0)
        risk = max(risk, _OI_RISK.get(oi.regime, 0.2))
        n += 1
        if oi.regime != OI_NEUTRAL:
            reasons.append(f"OI rejim: {oi.regime} (ΔOI {oi.oi_change_pct * 100:.1f}%)")

    if liquidation is not None:
        risk = max(risk, liquidation.cascade_risk)
        if liquidation.has_magnet:
            # Magnet yukarıdaysa hafif pozitif, aşağıdaysa negatif bias
            mdist = liquidation.magnet_distance_pct or 0.0
            alpha += 0.2 * (1.0 if mdist > 0 else -1.0)
            reasons.append(
                f"Liq magnet {liquidation.magnet_target:.2f} "
                f"({mdist * 100:+.1f}%), cascade risk {liquidation.cascade_risk:.2f}"
            )

    if long_short is not None and long_short.is_crowded:
        # Crowded trade → kontraryan bias (kalabalığın tersi)
        alpha += -0.3 if long_short.crowded_side == "long" else 0.3
        risk = max(risk, long_short.crowded_pct)
        reasons.append(
            f"Crowded {long_short.crowded_side} %{long_short.crowded_pct * 100:.0f}"
        )
        if long_short.retail_whale_divergence:
            reasons.append("Retail-whale L/S divergence")

    if basis is not None and basis.basis_trade_opportunity:
        reasons.append(f"Basis trade fırsatı ({basis.structure})")

    alpha = max(-1.0, min(1.0, alpha))
    return MarketStructure(
        oi=oi,
        liquidation=liquidation,
        long_short=long_short,
        basis=basis,
        alpha_bias=float(alpha),
        risk_score=float(_clamp01(risk)),
        reasons=reasons,
    )


def velocities_from_history(
    oi_history: Sequence[Tuple[int, float]],
    *,
    now_ms: Optional[int] = None,
) -> Dict[str, Optional[float]]:
    """``[(ts_ms, oi), ...]`` serisinden 1h/4h/24h yüzde değişim."""
    pts = sorted(
        ((int(t), f) for t, v in oi_history if (f := _coerce_float(v)) is not None),
        key=lambda x: x[0],
    )
    if not pts:
        return {"1h": None, "4h": None, "24h": None}
    last_ts, last_oi = pts[-1]
    ref = now_ms if now_ms is not None else last_ts

    def _delta(window_ms: int) -> Optional[float]:
        target = ref - window_ms
        prior = [p for p in pts if p[0] <= target]
        base = prior[-1][1] if prior else pts[0][1]
        if base is None or abs(base) < 1e-12:
            return None
        return (last_oi - base) / base

    return {
        "1h": _delta(3_600_000),
        "4h": _delta(4 * 3_600_000),
        "24h": _delta(24 * 3_600_000),
    }


__all__ = [
    "BACKWARDATION",
    "CONTANGO",
    "FLAT_STRUCTURE",
    "LIQ_CLUSTER_MIN_USD",
    "OI_LONG_CAPITULATION",
    "OI_NEUTRAL",
    "OI_SHORT_BUILDUP",
    "OI_SHORT_COVERING",
    "OI_TREND_STRENGTHENING",
    "BasisAnalysis",
    "LiquidationCluster",
    "LiquidationMap",
    "LongShortAnalysis",
    "MarketStructure",
    "OiRegime",
    "analyze_basis",
    "analyze_liquidation_map",
    "analyze_long_short",
    "analyze_market_structure",
    "analyze_oi",
    "classify_oi_regime",
    "parse_liquidation_levels",
    "velocities_from_history",
]
