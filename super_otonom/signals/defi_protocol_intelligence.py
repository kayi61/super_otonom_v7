"""PROMPT-2.2 — DeFi Protocol Intelligence (signals/) — Faz 27 adoption feed.

DeFi protokol verilerini izler; `alternative_data_engine` (Faz 27) adoption
bölümünü zenginleştirir.

1. **TVL**: protokol/chain TVL değişimi, chain akışı (ETH→Solana/L2), TVL/FDV
   (düşük = overvalued), ani TVL düşüşü → bank run / exploit uyarısı.
2. **DEX Volume & Liquidity**: Uniswap/Raydium/Jupiter volume, büyük swap'lar
   ($1M+, whale), pool depth değişimi, yeni pool (token launch göstergesi).
3. **Lending/Borrowing**: Aave/Compound borrow rate spike (kaldıraç↑), büyük
   liquidation seviyeleri, utilization > %80, stablecoin borrow spike (stres).
4. **Bridge Flow**: cross-chain akış (hangi chain'e para akıyor), bridge exploit
   geçmişi risk skoru.

Sinyal mantığı:
- TVL akışı bir chain'e yoğunlaşıyorsa → o chain token'larına alpha.
- DEX'te whale swap → price impact öncesi pozisyon.
- Lending rate spike → volatilite artışı beklentisi.
- Toplu liquidation seviyesi yaklaşıyorsa → cascade riski.

Kaynak: DeFiLlama API (ücretsiz, key gereksiz; enjekte edilebilir ``http_get``).
Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("super_otonom.defi")

HttpGet = Callable[[str, float], Optional[str]]

# Eşikler
WHALE_SWAP_USD = 1_000_000.0        # $1M+ swap → whale DEX aktivitesi
SUDDEN_TVL_DROP = -0.15             # ≤ -%15 ani TVL → bank run / exploit
HIGH_UTILIZATION = 0.80             # > %80 → borrowing talep patlaması
LOW_TVL_FDV = 0.10                  # < → overvalued (FDV, TVL'e göre yüksek)
RATE_SPIKE_PCT = 0.5               # borrow rate ≥ +%50 değişim → spike


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
        log.debug("defi http_get hata (%s): %s", url[:60], exc)
        return None


def _dominant_inflow(flows: Any) -> Optional[str]:
    """{chain: net_flow} → en yüksek pozitif akışlı chain."""
    if not isinstance(flows, dict) or not flows:
        return None
    best, best_v = None, 0.0
    for chain, v in flows.items():
        fv = _coerce_float(v)
        if fv is not None and fv > best_v:
            best, best_v = str(chain), fv
    return best


# ── 1) TVL ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TvlAnalysis:
    change_pct: Optional[float]
    dominant_chain: Optional[str]   # TVL akışının yoğunlaştığı chain
    tvl_fdv_ratio: Optional[float]
    overvalued: bool                # düşük TVL/FDV
    exploit_alert: bool             # ani TVL düşüşü
    bias: float                     # -1..1
    risk: float                     # 0..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_pct": self.change_pct,
            "dominant_chain": self.dominant_chain,
            "tvl_fdv_ratio": self.tvl_fdv_ratio,
            "overvalued": self.overvalued,
            "exploit_alert": self.exploit_alert,
            "bias": self.bias,
            "risk": self.risk,
        }


def analyze_tvl(
    *,
    protocol_tvl: Optional[float] = None,
    protocol_tvl_prev: Optional[float] = None,
    tvl_change_pct: Optional[float] = None,
    chain_tvl_flows: Any = None,
    tvl_usd: Optional[float] = None,
    fdv_usd: Optional[float] = None,
) -> TvlAnalysis:
    """Protokol/chain TVL + TVL/FDV + ani düşüş (exploit) analizi."""
    change = _coerce_float(tvl_change_pct)
    if change is None:
        cur, prev = _coerce_float(protocol_tvl), _coerce_float(protocol_tvl_prev)
        if cur is not None and prev is not None and prev > 0:
            change = (cur - prev) / prev

    dominant = _dominant_inflow(chain_tvl_flows)

    tvl_fdv = None
    tv, fdv = _coerce_float(tvl_usd), _coerce_float(fdv_usd)
    if tv is not None and fdv is not None and fdv > 0:
        tvl_fdv = tv / fdv
    overvalued = tvl_fdv is not None and tvl_fdv < LOW_TVL_FDV

    exploit_alert = change is not None and change <= SUDDEN_TVL_DROP

    bias = 0.0
    risk = 0.0
    if change is not None:
        if exploit_alert:
            bias = -1.0
            risk = _clamp01(0.7 + abs(change))
        else:
            bias = _clamp(change * 2.0, -0.6, 0.6)
    if overvalued:
        bias = _clamp(bias - 0.2, -1.0, 1.0)
        risk = max(risk, 0.3)
    return TvlAnalysis(
        change_pct=change,
        dominant_chain=dominant,
        tvl_fdv_ratio=tvl_fdv,
        overvalued=bool(overvalued),
        exploit_alert=bool(exploit_alert),
        bias=float(_clamp(bias, -1.0, 1.0)),
        risk=float(_clamp01(risk)),
    )


# ── 2) DEX Volume & Liquidity ────────────────────────────────────────────────


@dataclass(frozen=True)
class DexAnalysis:
    volume_usd: float
    large_swap_count: int           # $1M+ swap sayısı
    whale_activity: float           # 0..1
    pool_depth_change_pct: Optional[float]
    new_pool_signal: bool           # yeni pool → token launch göstergesi
    bias: float                     # -1..1 (whale net yönü)
    risk: float                     # 0..1 (likidite çekilmesi)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "volume_usd": self.volume_usd,
            "large_swap_count": self.large_swap_count,
            "whale_activity": self.whale_activity,
            "pool_depth_change_pct": self.pool_depth_change_pct,
            "new_pool_signal": self.new_pool_signal,
            "bias": self.bias,
            "risk": self.risk,
        }


def analyze_dex(
    *,
    dex_volume_usd: Optional[float] = None,
    large_swaps: Any = None,
    large_swap_count: Optional[float] = None,
    whale_net_direction: Optional[float] = None,
    pool_depth_change_pct: Optional[float] = None,
    new_pools: Optional[float] = None,
) -> DexAnalysis:
    """DEX volume + büyük swap (whale) + pool depth + yeni pool analizi."""
    vol = max(0.0, _coerce_float(dex_volume_usd) or 0.0)

    count = 0
    net_dir = _coerce_float(whale_net_direction) or 0.0
    if isinstance(large_swaps, list):
        for s in large_swaps:
            amt = _coerce_float(s.get("amount_usd") if isinstance(s, dict) else s)
            if amt is not None and abs(amt) >= WHALE_SWAP_USD:
                count += 1
                if isinstance(s, dict):
                    side = str(s.get("side", "")).lower()
                    if side in ("buy", "long"):
                        net_dir += 1
                    elif side in ("sell", "short"):
                        net_dir -= 1
    lc = _coerce_float(large_swap_count)
    if lc is not None:
        count = max(count, int(lc))

    whale_activity = _clamp01(math.tanh(count / 5.0))
    depth = _coerce_float(pool_depth_change_pct)
    new_pool_signal = (_coerce_float(new_pools) or 0.0) >= 1

    bias = _clamp(0.15 * net_dir, -0.6, 0.6)
    risk = 0.0
    if depth is not None and depth <= -0.2:
        risk = _clamp01(abs(depth))  # likidite çekiliyor
    return DexAnalysis(
        volume_usd=float(vol),
        large_swap_count=int(count),
        whale_activity=float(whale_activity),
        pool_depth_change_pct=depth,
        new_pool_signal=bool(new_pool_signal),
        bias=float(bias),
        risk=float(risk),
    )


# ── 3) Lending / Borrowing ───────────────────────────────────────────────────


@dataclass(frozen=True)
class LendingAnalysis:
    borrow_rate: Optional[float]
    rate_spike: bool                # borrow rate ani artış → kaldıraç↑
    utilization: Optional[float]
    high_utilization: bool          # > %80
    stablecoin_stress: bool         # stablecoin borrow spike
    cascade_risk: float             # 0..1 (toplu liquidation yaklaşıyor)
    volatility_expectation: float   # 0..1
    risk: float                     # 0..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "borrow_rate": self.borrow_rate,
            "rate_spike": self.rate_spike,
            "utilization": self.utilization,
            "high_utilization": self.high_utilization,
            "stablecoin_stress": self.stablecoin_stress,
            "cascade_risk": self.cascade_risk,
            "volatility_expectation": self.volatility_expectation,
            "risk": self.risk,
        }


def analyze_lending(
    *,
    borrow_rate: Optional[float] = None,
    borrow_rate_prev: Optional[float] = None,
    utilization_rate: Optional[float] = None,
    stablecoin_borrow_rate_change: Optional[float] = None,
    liquidation_proximity: Optional[float] = None,
) -> LendingAnalysis:
    """Borrow rate spike / utilization / liquidation cascade analizi.

    ``liquidation_proximity`` 0..1: toplu liquidation seviyesine yakınlık (1 = çok yakın).
    """
    rate = _coerce_float(borrow_rate)
    prev = _coerce_float(borrow_rate_prev)
    rate_spike = False
    if rate is not None and prev is not None and prev > 0:
        rate_spike = (rate - prev) / prev >= RATE_SPIKE_PCT

    util = _coerce_float(utilization_rate)
    if util is not None and util > 1.0:
        util = util / 100.0
    high_util = util is not None and util >= HIGH_UTILIZATION

    stable_change = _coerce_float(stablecoin_borrow_rate_change)
    stable_stress = stable_change is not None and stable_change >= RATE_SPIKE_PCT

    cascade = _clamp01(_coerce_float(liquidation_proximity) or 0.0)

    vol_exp = 0.0
    if rate_spike:
        vol_exp = max(vol_exp, 0.5)
    if high_util:
        vol_exp = max(vol_exp, 0.45)
    if stable_stress:
        vol_exp = max(vol_exp, 0.6)

    risk = _clamp01(max(cascade, 0.5 * vol_exp, 0.6 if stable_stress else 0.0))
    return LendingAnalysis(
        borrow_rate=rate,
        rate_spike=bool(rate_spike),
        utilization=util,
        high_utilization=bool(high_util),
        stablecoin_stress=bool(stable_stress),
        cascade_risk=float(cascade),
        volatility_expectation=float(_clamp01(vol_exp)),
        risk=float(risk),
    )


# ── 4) Bridge Flow ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BridgeAnalysis:
    dominant_inflow_chain: Optional[str]
    net_inflow_usd: Optional[float]
    exploit_risk: float             # 0..1 (bridge exploit geçmişi)
    bias: float                     # -1..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dominant_inflow_chain": self.dominant_inflow_chain,
            "net_inflow_usd": self.net_inflow_usd,
            "exploit_risk": self.exploit_risk,
            "bias": self.bias,
        }


def analyze_bridge(
    *,
    bridge_flows: Any = None,
    bridge_exploit_history: Optional[float] = None,
) -> BridgeAnalysis:
    """Cross-chain bridge akışı (hangi chain'e para) + exploit risk skoru."""
    dominant = _dominant_inflow(bridge_flows)
    net = None
    if isinstance(bridge_flows, dict) and dominant is not None:
        net = _coerce_float(bridge_flows.get(dominant))

    exploit_risk = _clamp01(_coerce_float(bridge_exploit_history) or 0.0)
    bias = 0.0
    if net is not None and net > 0:
        bias = _clamp(math.tanh(net / 5e8), 0.0, 0.5)
    bias = _clamp(bias - 0.3 * exploit_risk, -1.0, 1.0)
    return BridgeAnalysis(
        dominant_inflow_chain=dominant,
        net_inflow_usd=net,
        exploit_risk=float(exploit_risk),
        bias=float(bias),
    )


# ── Birleşik sinyal ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DefiSignal:
    tvl: Optional[TvlAnalysis]
    dex: Optional[DexAnalysis]
    lending: Optional[LendingAnalysis]
    bridge: Optional[BridgeAnalysis]
    chain_rotation: Optional[str]       # TVL+bridge akışının yoğunlaştığı chain
    adoption_score: float               # 0..1 (Faz 27 adoption blend)
    alpha_bias: float                   # -1..1
    risk_score: float                   # 0..1
    cascade_risk: float                 # 0..1
    volatility_expectation: float       # 0..1
    exploit_alert: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "chain_rotation": self.chain_rotation,
            "defi_adoption_score": self.adoption_score,
            "defi_alpha_bias": self.alpha_bias,
            "defi_risk_score": self.risk_score,
            "cascade_risk": self.cascade_risk,
            "volatility_expectation": self.volatility_expectation,
            "exploit_alert": self.exploit_alert,
            "defi_reasons": list(self.reasons),
        }
        if self.tvl is not None:
            out["tvl"] = self.tvl.to_dict()
        if self.dex is not None:
            out["dex"] = self.dex.to_dict()
        if self.lending is not None:
            out["lending"] = self.lending.to_dict()
        if self.bridge is not None:
            out["bridge"] = self.bridge.to_dict()
        return out


def analyze_defi(
    *,
    tvl: Optional[TvlAnalysis] = None,
    dex: Optional[DexAnalysis] = None,
    lending: Optional[LendingAnalysis] = None,
    bridge: Optional[BridgeAnalysis] = None,
) -> Optional[DefiSignal]:
    """DeFi katmanlarını adoption/alpha/risk + chain rotation'a indirger. Veri yoksa None."""
    if tvl is None and dex is None and lending is None and bridge is None:
        return None

    reasons: List[str] = []
    alpha = 0.0
    risk = 0.0
    cascade = 0.0
    vol_exp = 0.0
    exploit_alert = False
    adoption = 0.0
    n = 0

    # Chain rotation: TVL ve bridge akışları aynı chain'e işaret ediyorsa güçlü
    tvl_chain = tvl.dominant_chain if tvl else None
    bridge_chain = bridge.dominant_inflow_chain if bridge else None
    rotation = tvl_chain or bridge_chain
    if tvl_chain and bridge_chain and tvl_chain == bridge_chain:
        alpha += 0.2
        reasons.append(f"TVL + bridge akışı '{rotation}' chain'inde yoğunlaşıyor → alpha")
    elif rotation:
        reasons.append(f"Akış '{rotation}' chain'ine yöneliyor")

    if tvl is not None:
        alpha += 0.3 * tvl.bias
        risk = max(risk, tvl.risk)
        adoption += _clamp01(0.5 + 0.5 * tvl.bias)
        n += 1
        if tvl.exploit_alert:
            exploit_alert = True
            reasons.append(f"Ani TVL düşüşü ({tvl.change_pct:.0%}) → bank run / exploit uyarısı")
        if tvl.overvalued:
            reasons.append(f"Düşük TVL/FDV ({tvl.tvl_fdv_ratio:.3f}) → overvalued")

    if dex is not None:
        alpha += 0.25 * dex.bias
        risk = max(risk, dex.risk)
        adoption += _clamp01(math.tanh(dex.volume_usd / 5e9))
        n += 1
        if dex.large_swap_count > 0:
            reasons.append(f"{dex.large_swap_count} whale swap ($1M+) → price impact öncesi sinyal")
        if dex.new_pool_signal:
            reasons.append("Yeni pool oluşumu → token launch göstergesi")

    if lending is not None:
        risk = max(risk, lending.risk)
        cascade = max(cascade, lending.cascade_risk)
        vol_exp = max(vol_exp, lending.volatility_expectation)
        if lending.rate_spike:
            reasons.append("Borrow rate spike → kaldıraç artışı / volatilite beklentisi")
        if lending.high_utilization:
            reasons.append("Utilization > %80 → borrowing talep patlaması")
        if lending.stablecoin_stress:
            reasons.append("Stablecoin borrow spike → piyasa stresi")
        if lending.cascade_risk >= 0.6:
            reasons.append("Toplu liquidation seviyesi yaklaşıyor → cascade riski")

    if bridge is not None:
        alpha += 0.2 * bridge.bias
        if bridge.exploit_risk >= 0.5:
            risk = max(risk, bridge.exploit_risk * 0.6)
            reasons.append(f"Bridge exploit geçmişi riski ({bridge.exploit_risk:.2f})")

    if exploit_alert:
        risk = _clamp01(max(risk, 0.85))
        alpha = _clamp(min(alpha, -0.5), -1.0, 1.0)

    adoption_score = _clamp01(adoption / max(1, n)) if n else 0.0
    risk = _clamp01(max(risk, 0.5 * cascade))
    return DefiSignal(
        tvl=tvl, dex=dex, lending=lending, bridge=bridge,
        chain_rotation=rotation,
        adoption_score=float(adoption_score),
        alpha_bias=float(_clamp(alpha, -1.0, 1.0)),
        risk_score=float(_clamp01(risk)),
        cascade_risk=float(_clamp01(cascade)),
        volatility_expectation=float(_clamp01(vol_exp)),
        exploit_alert=bool(exploit_alert),
        reasons=reasons,
    )


_DEFI_KEYS = (
    "tvl", "dex", "lending", "bridge", "protocol_tvl", "tvl_change_pct",
    "chain_tvl_flows", "dex_volume_usd", "large_swaps", "borrow_rate",
    "utilization_rate", "bridge_flows", "liquidation_proximity",
)


def analyze_defi_data(data: Dict[str, Any]) -> Optional[DefiSignal]:
    """Düz dict köprüsü (alternative_data_engine Faz 27).

    ``defi`` alt dict veya düz ``tvl``/``dex``/``lending``/``bridge`` alt dict'leri.
    """
    if not isinstance(data, dict):
        return None
    block = data.get("defi") if isinstance(data.get("defi"), dict) else data
    if not (isinstance(data.get("defi"), dict) or any(k in data for k in _DEFI_KEYS)):
        return None

    def sub(key: str) -> Dict[str, Any]:
        v = block.get(key)
        return v if isinstance(v, dict) else {}

    tvl_in = {**sub("tvl"), **{k: block[k] for k in (
        "protocol_tvl", "protocol_tvl_prev", "tvl_change_pct", "chain_tvl_flows",
        "tvl_usd", "fdv_usd") if k in block}}
    dex_in = {**sub("dex"), **{k: block[k] for k in (
        "dex_volume_usd", "large_swaps", "large_swap_count", "whale_net_direction",
        "pool_depth_change_pct", "new_pools") if k in block}}
    lend_in = {**sub("lending"), **{k: block[k] for k in (
        "borrow_rate", "borrow_rate_prev", "utilization_rate",
        "stablecoin_borrow_rate_change", "liquidation_proximity") if k in block}}
    bridge_in = {**sub("bridge"), **{k: block[k] for k in (
        "bridge_flows", "bridge_exploit_history") if k in block}}

    tvl = analyze_tvl(**tvl_in) if tvl_in else None
    dex = analyze_dex(**dex_in) if dex_in else None
    lending = analyze_lending(**lend_in) if lend_in else None
    bridge = analyze_bridge(**bridge_in) if bridge_in else None
    return analyze_defi(tvl=tvl, dex=dex, lending=lending, bridge=bridge)


# ── Parser + Collector ───────────────────────────────────────────────────────


def parse_defillama_protocol(payload: Any) -> Dict[str, Any]:
    """DeFiLlama ``/protocol/{slug}`` JSON → {tvl, chain_tvls}."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    out: Dict[str, Any] = {}
    cur = payload.get("currentChainTvls")
    if isinstance(cur, dict):
        total = sum(v for v in (_coerce_float(x) for x in cur.values()) if v is not None)
        out["tvl"] = total
        out["chain_tvls"] = {k: _coerce_float(v) for k, v in cur.items()}
    elif _coerce_float(payload.get("tvl")) is not None:
        out["tvl"] = _coerce_float(payload.get("tvl"))
    return out


def parse_defillama_chains(payload: Any) -> Dict[str, float]:
    """DeFiLlama ``/v2/chains`` JSON → {chain: tvl}."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, list):
        return {}
    out: Dict[str, float] = {}
    for row in payload:
        if isinstance(row, dict):
            name = row.get("name") or row.get("gecko_id")
            tvl = _coerce_float(row.get("tvl"))
            if name and tvl is not None:
                out[str(name)] = tvl
    return out


class DefiCollector:
    """DeFiLlama toplayıcı (ücretsiz, key gereksiz; mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 6.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_protocol(self, slug: str) -> Dict[str, Any]:
        base = os.getenv("DEFILLAMA_API_URL", "https://api.llama.fi")
        body = self._http_get(f"{base}/protocol/{slug}", self._timeout)
        return parse_defillama_protocol(body) if body else {}

    def fetch_chains(self) -> Dict[str, float]:
        base = os.getenv("DEFILLAMA_API_URL", "https://api.llama.fi")
        body = self._http_get(f"{base}/v2/chains", self._timeout)
        return parse_defillama_chains(body) if body else {}


__all__ = [
    "HIGH_UTILIZATION",
    "LOW_TVL_FDV",
    "SUDDEN_TVL_DROP",
    "WHALE_SWAP_USD",
    "BridgeAnalysis",
    "DefiCollector",
    "DefiSignal",
    "DexAnalysis",
    "LendingAnalysis",
    "TvlAnalysis",
    "analyze_bridge",
    "analyze_defi",
    "analyze_defi_data",
    "analyze_dex",
    "analyze_lending",
    "analyze_tvl",
    "parse_defillama_chains",
    "parse_defillama_protocol",
]
