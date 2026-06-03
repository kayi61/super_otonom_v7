"""PROMPT-2.1 — On-Chain Metrics Engine — Faz 27 adoption feed.

Blockchain on-chain metriklerini toplar/analiz eder; `alternative_data_engine`
(Faz 27) adoption bölümünü zenginleştirir.

1. **Ağ aktivitesi**: active addresses, tx count/volume, new address hızı,
   ortalama tx fee (congestion proxy).
2. **Holder analizi**: supply distribution (top 10/100/1000), holder count trendi,
   LTH vs STH oranı, accumulation/distribution (30g).
3. **Miner/Validator**: miner outflow (BTC), staking ratio değişimi (ETH/SOL),
   hash rate trend.
4. **MVRV & Realized Price**: MVRV ratio (> 3.5 aşırı değerli/satış riski,
   < 1.0 düşük değerli/birikim), realized vs market price.

Kaynaklar: Blockchain.com / Etherscan / Glassnode / CoinMetrics Community
(enjekte edilebilir ``http_get``). Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("super_otonom.onchain")

HttpGet = Callable[[str, float], Optional[str]]

# MVRV eşikleri
MVRV_OVERVALUED = 3.5   # > → aşırı değerli (satış riski)
MVRV_UNDERVALUED = 1.0  # < → düşük değerli (birikim fırsatı)

MVRV_OVER = "overvalued"
MVRV_UNDER = "undervalued"
MVRV_FAIR = "fair_value"

ACCUMULATION = "accumulation"
DISTRIBUTION = "distribution"
NEUTRAL = "neutral"


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("onchain http_get hata (%s): %s", url[:60], exc)
        return None


# ── 1) Ağ aktivitesi ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NetworkActivity:
    active_addresses: float
    tx_count: float
    tx_volume_usd: float
    new_address_rate: float       # yeni adres / gün
    avg_tx_fee_usd: float
    activity_score: float         # 0..1 (yüksek = sağlıklı adoption)
    congestion: float             # 0..1 (yüksek fee → tıkanıklık)


def analyze_network_activity(
    *,
    active_addresses: Optional[float] = None,
    tx_count: Optional[float] = None,
    tx_volume_usd: Optional[float] = None,
    new_address_rate: Optional[float] = None,
    avg_tx_fee_usd: Optional[float] = None,
) -> NetworkActivity:
    aa = active_addresses or 0.0
    txc = tx_count or 0.0
    txv = tx_volume_usd or 0.0
    nar = new_address_rate or 0.0
    fee = avg_tx_fee_usd or 0.0

    s_aa = _clamp01(math.tanh(aa / 8e5))
    s_tx = _clamp01(math.tanh(txc / 1e6))
    s_vol = _clamp01(math.tanh(txv / 5e9))
    s_new = _clamp01(math.tanh(nar / 4e5))
    activity = _clamp01(0.34 * s_aa + 0.26 * s_tx + 0.24 * s_vol + 0.16 * s_new)
    congestion = _clamp01(math.tanh(fee / 15.0)) if fee > 0 else 0.0

    return NetworkActivity(
        active_addresses=float(aa),
        tx_count=float(txc),
        tx_volume_usd=float(txv),
        new_address_rate=float(nar),
        avg_tx_fee_usd=float(fee),
        activity_score=float(activity),
        congestion=float(congestion),
    )


# ── 2) Holder analizi ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HolderAnalysis:
    top10_pct: Optional[float]
    top100_pct: Optional[float]
    top1000_pct: Optional[float]
    holder_count_change_pct: Optional[float]
    lth_ratio: Optional[float]          # long-term holder oranı (>1y)
    concentration_risk: float           # 0..1 (yüksek top10 → risk)
    trend: str                          # accumulation | distribution | neutral


def analyze_holders(
    *,
    top10_pct: Optional[float] = None,
    top100_pct: Optional[float] = None,
    top1000_pct: Optional[float] = None,
    holder_count_change_pct: Optional[float] = None,
    lth_ratio: Optional[float] = None,
    accumulation_trend_30d: Optional[float] = None,
) -> HolderAnalysis:
    """Holder dağılımı + konsantrasyon riski + accumulation/distribution trendi."""
    conc = _clamp01((top10_pct - 0.15) / 0.35) if top10_pct is not None else 0.3

    trend = NEUTRAL
    # accumulation_trend_30d > 0 → birikim; holder büyümesi + LTH artışı destekler
    score = 0.0
    if accumulation_trend_30d is not None:
        score += accumulation_trend_30d
    if holder_count_change_pct is not None:
        score += holder_count_change_pct * 2.0
    if score > 0.02:
        trend = ACCUMULATION
    elif score < -0.02:
        trend = DISTRIBUTION

    return HolderAnalysis(
        top10_pct=top10_pct,
        top100_pct=top100_pct,
        top1000_pct=top1000_pct,
        holder_count_change_pct=holder_count_change_pct,
        lth_ratio=lth_ratio,
        concentration_risk=float(conc),
        trend=trend,
    )


# ── 3) Miner / Validator ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class MinerMetrics:
    miner_outflow_usd: Optional[float]
    staking_ratio_change: Optional[float]
    hash_rate_change_pct: Optional[float]
    miner_sell_pressure: float          # 0..1
    security_score: float               # 0..1 (hash rate / staking artışı)


def analyze_miner_metrics(
    *,
    miner_outflow_usd: Optional[float] = None,
    staking_ratio_change: Optional[float] = None,
    hash_rate_change_pct: Optional[float] = None,
) -> MinerMetrics:
    sell = _clamp01(math.tanh((miner_outflow_usd or 0.0) / 5e7)) if miner_outflow_usd and miner_outflow_usd > 0 else 0.0
    sec = 0.5
    if hash_rate_change_pct is not None:
        sec = _clamp01(0.5 + 2.0 * hash_rate_change_pct)
    elif staking_ratio_change is not None:
        sec = _clamp01(0.5 + 4.0 * staking_ratio_change)
    return MinerMetrics(
        miner_outflow_usd=miner_outflow_usd,
        staking_ratio_change=staking_ratio_change,
        hash_rate_change_pct=hash_rate_change_pct,
        miner_sell_pressure=float(sell),
        security_score=float(sec),
    )


# ── 4) MVRV & Realized Price ─────────────────────────────────────────────────


@dataclass(frozen=True)
class MvrvAnalysis:
    mvrv: Optional[float]
    valuation: str                      # overvalued | undervalued | fair_value
    market_price: Optional[float]
    realized_price: Optional[float]
    price_premium_pct: Optional[float]  # (market - realized) / realized
    bias: float                         # -1..1 (overvalued → -, undervalued → +)


def classify_mvrv(mvrv: float) -> str:
    if mvrv > MVRV_OVERVALUED:
        return MVRV_OVER
    if mvrv < MVRV_UNDERVALUED:
        return MVRV_UNDER
    return MVRV_FAIR


def analyze_mvrv(
    *,
    mvrv: Optional[float] = None,
    market_price: Optional[float] = None,
    realized_price: Optional[float] = None,
) -> MvrvAnalysis:
    """MVRV ratio + valuation + realized-market premium."""
    if mvrv is None and market_price is not None and realized_price is not None and realized_price > 0:
        mvrv = market_price / realized_price
    premium = None
    if market_price is not None and realized_price is not None and realized_price > 0:
        premium = (market_price - realized_price) / realized_price

    valuation = MVRV_FAIR
    bias = 0.0
    if mvrv is not None:
        valuation = classify_mvrv(float(mvrv))
        if valuation == MVRV_OVER:
            bias = -_clamp((mvrv - MVRV_OVERVALUED) / 2.0, 0.0, 1.0)
        elif valuation == MVRV_UNDER:
            bias = _clamp((MVRV_UNDERVALUED - mvrv) * 1.5 + 0.3, 0.0, 1.0)

    return MvrvAnalysis(
        mvrv=float(mvrv) if mvrv is not None else None,
        valuation=valuation,
        market_price=market_price,
        realized_price=realized_price,
        price_premium_pct=premium,
        bias=float(bias),
    )


# ── Birleşik analiz ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OnchainSignal:
    network: Optional[NetworkActivity]
    holders: Optional[HolderAnalysis]
    miner: Optional[MinerMetrics]
    mvrv: Optional[MvrvAnalysis]
    adoption_score: float       # 0..1 (Faz 27 adoption blend)
    alpha_bias: float           # -1..1
    risk_score: float           # 0..1
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "onchain_adoption_score": self.adoption_score,
            "onchain_alpha_bias": self.alpha_bias,
            "onchain_risk_score": self.risk_score,
            "onchain_reasons": list(self.reasons),
        }
        if self.network is not None:
            out["network_activity_score"] = self.network.activity_score
            out["network_congestion"] = self.network.congestion
            out["active_addresses"] = self.network.active_addresses
        if self.holders is not None:
            out["holder_trend"] = self.holders.trend
            out["holder_concentration_risk"] = self.holders.concentration_risk
            out["lth_ratio"] = self.holders.lth_ratio
        if self.miner is not None:
            out["miner_sell_pressure"] = self.miner.miner_sell_pressure
            out["network_security_score"] = self.miner.security_score
        if self.mvrv is not None:
            out["mvrv"] = self.mvrv.mvrv
            out["mvrv_valuation"] = self.mvrv.valuation
            out["price_premium_pct"] = self.mvrv.price_premium_pct
        return out


def analyze_onchain(
    *,
    network: Optional[NetworkActivity] = None,
    holders: Optional[HolderAnalysis] = None,
    miner: Optional[MinerMetrics] = None,
    mvrv: Optional[MvrvAnalysis] = None,
) -> OnchainSignal:
    """Tüm on-chain metrikleri adoption_score + alpha bias + risk'e indirger."""
    reasons: List[str] = []
    alpha = 0.0
    risk = 0.0
    adoption = 0.0
    n = 0

    if network is not None:
        adoption += network.activity_score
        n += 1
        if network.congestion > 0.7:
            risk = max(risk, network.congestion * 0.5)
            reasons.append(f"Ağ tıkanıklığı yüksek ({network.congestion:.2f})")

    if holders is not None:
        risk = max(risk, holders.concentration_risk * 0.6)
        if holders.trend == ACCUMULATION:
            alpha += 0.25
            adoption += 0.15
            reasons.append("Holder birikim trendi (accumulation)")
        elif holders.trend == DISTRIBUTION:
            alpha -= 0.25
            reasons.append("Holder dağıtım trendi (distribution)")
        if holders.concentration_risk > 0.7:
            reasons.append(f"Yüksek holder konsantrasyonu ({holders.concentration_risk:.2f})")

    if miner is not None:
        risk = max(risk, miner.miner_sell_pressure * 0.5)
        if miner.miner_sell_pressure > 0.6:
            alpha -= 0.15
            reasons.append(f"Miner satış baskısı ({miner.miner_sell_pressure:.2f})")
        adoption += 0.10 * miner.security_score

    if mvrv is not None:
        alpha += 0.5 * mvrv.bias
        if mvrv.valuation == MVRV_OVER:
            risk = max(risk, _clamp((mvrv.mvrv or 0) / 6.0, 0.4, 1.0))
            reasons.append(f"MVRV {mvrv.mvrv:.2f} aşırı değerli (satış riski)")
        elif mvrv.valuation == MVRV_UNDER:
            reasons.append(f"MVRV {mvrv.mvrv:.2f} düşük değerli (birikim fırsatı)")

    adoption_score = _clamp01(adoption / max(1, n) if n else adoption)
    alpha = _clamp(alpha, -1.0, 1.0)
    return OnchainSignal(
        network=network, holders=holders, miner=miner, mvrv=mvrv,
        adoption_score=float(adoption_score), alpha_bias=float(alpha),
        risk_score=float(_clamp01(risk)), reasons=reasons,
    )


# ── Parser'lar (kaynak normalize) ────────────────────────────────────────────


def parse_blockchain_stats(payload: Any) -> Dict[str, float]:
    """Blockchain.com ``/stats`` JSON → normalize metrik dict."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    out: Dict[str, float] = {}
    for src, dst in (
        ("n_tx", "tx_count"),
        ("estimated_transaction_volume_usd", "tx_volume_usd"),
        ("hash_rate", "hash_rate"),
        ("trade_volume_usd", "trade_volume_usd"),
        ("market_price_usd", "market_price"),
    ):
        v = _coerce_float(payload.get(src))
        if v is not None:
            out[dst] = v
    return out


def parse_coinmetrics(payload: Any) -> Dict[str, float]:
    """CoinMetrics community timeseries JSON → son değerleri normalize eder."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        return {}
    last = rows[-1]
    if not isinstance(last, dict):
        return {}
    out: Dict[str, float] = {}
    for src, dst in (
        ("AdrActCnt", "active_addresses"),
        ("TxCnt", "tx_count"),
        ("CapMVRVCur", "mvrv"),
        ("PriceUSD", "market_price"),
        ("CapRealUSD", "realized_cap"),
        ("FeeMeanUSD", "avg_tx_fee_usd"),
    ):
        v = _coerce_float(last.get(src))
        if v is not None:
            out[dst] = v
    return out


# ── Collector ────────────────────────────────────────────────────────────────


class OnchainCollector:
    """Blockchain.com / CoinMetrics on-chain metrik toplayıcı (mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 5.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_blockchain_stats(self) -> Dict[str, float]:
        base = os.getenv("BLOCKCHAIN_STATS_URL", "https://api.blockchain.info/stats")
        body = self._http_get(f"{base}?format=json", self._timeout)
        return parse_blockchain_stats(body) if body else {}

    def fetch_coinmetrics(self) -> Dict[str, float]:
        base = os.getenv("COINMETRICS_API_URL", "")
        if not base:
            return {}
        body = self._http_get(base, self._timeout)
        return parse_coinmetrics(body) if body else {}


__all__ = [
    "ACCUMULATION",
    "DISTRIBUTION",
    "MVRV_FAIR",
    "MVRV_OVER",
    "MVRV_OVERVALUED",
    "MVRV_UNDER",
    "MVRV_UNDERVALUED",
    "NEUTRAL",
    "HolderAnalysis",
    "MinerMetrics",
    "MvrvAnalysis",
    "NetworkActivity",
    "OnchainCollector",
    "OnchainSignal",
    "analyze_holders",
    "analyze_miner_metrics",
    "analyze_mvrv",
    "analyze_network_activity",
    "analyze_onchain",
    "classify_mvrv",
    "parse_blockchain_stats",
    "parse_coinmetrics",
]
