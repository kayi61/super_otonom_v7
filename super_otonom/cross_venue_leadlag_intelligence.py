"""
Faz 74 — Cross-venue lead/lag intelligence.

Amaç:
- Çok borsalı fiyat/return akışından leader venue (öncü borsa) ve lead/lag gücünü sezmek.
- Olası latency-arb / gecikme kaynaklı adverse fill riskini tahmin etmek.
- Smart Order Router (Faz 47) için route_preference önerisi üretmek.

Standartlar:
- trade_permission = HALT/BLOCK/ALLOW
- alpha_score + risk_score
- confidence + data_health
- event_ts + half_life_ms
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional


TradePermission = Literal["HALT", "BLOCK", "ALLOW"]
RoutePreference = Literal["leader", "best_price", "lowest_latency", "avoid_latency_arb", "unknown"]


@dataclass(frozen=True)
class CrossVenueLeadLagResult:
    # Faz 74 outputs (requested)
    leader_venue: str
    leadlag_alpha_score: int  # 0-100
    latency_arb_risk: int  # 0-100
    route_preference: RoutePreference

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Optional debug
    venues_seen: int = 0
    max_price_divergence_bps: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _clamp100(x: float) -> int:
    if x != x:  # NaN
        return 0
    return int(max(0, min(100, round(x))))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _try_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _max_divergence_bps(prices: Dict[str, float]) -> Optional[float]:
    if not prices:
        return None
    vals = [p for p in prices.values() if p and p > 0]
    if len(vals) < 2:
        return None
    mn, mx = min(vals), max(vals)
    mid = (mn + mx) / 2.0
    if mid <= 0:
        return None
    return ((mx - mn) / mid) * 10_000.0  # basis points


def infer_cross_venue_leadlag(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 20_000,
) -> CrossVenueLeadLagResult:
    """
    Minimal, deterministic Faz-74 inference.

    Expected optional inputs (best-effort):
    - analysis["venues"]: {"okx": {"price":..., "ret_1s":..., "latency_ms":...}, ...}
    - analysis["leader_venue"]: precomputed hint (string)
    - analysis["leadlag_alpha_score"]: precomputed (0-100)

    If no multi-venue data exists, returns unknown with low confidence/data_health.
    """
    a = analysis or {}
    ts = int(event_ts if event_ts is not None else a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    venues: Dict[str, Any] = a.get("venues") if isinstance(a.get("venues"), dict) else {}
    venues_seen = len(venues)
    data_health = 0.88 if venues_seen >= 3 else 0.78 if venues_seen == 2 else 0.52

    # Use precomputed hints if present
    leader_hint = a.get("leader_venue")
    if isinstance(leader_hint, str) and leader_hint.strip():
        leader_venue = leader_hint.strip()
    else:
        # Compute leader by best (lowest) latency if available, else by most "active" return magnitude.
        best_latency: Optional[tuple[str, float]] = None
        best_activity: Optional[tuple[str, float]] = None
        for v, d in venues.items():
            if not isinstance(d, dict):
                continue
            lat = _try_float(d.get("latency_ms"))
            if lat is not None and lat > 0:
                if best_latency is None or lat < best_latency[1]:
                    best_latency = (v, lat)
            r = _try_float(d.get("ret_1s"))
            if r is not None:
                act = abs(r)
                if best_activity is None or act > best_activity[1]:
                    best_activity = (v, act)
        if best_activity is not None:
            leader_venue = best_activity[0]
        elif best_latency is not None:
            leader_venue = best_latency[0]
        else:
            leader_venue = "unknown"

    # Price divergence → latency arb risk
    prices: Dict[str, float] = {}
    latencies: Dict[str, float] = {}
    for v, d in venues.items():
        if not isinstance(d, dict):
            continue
        p = _try_float(d.get("price"))
        if p is not None and p > 0:
            prices[v] = p
        lat = _try_float(d.get("latency_ms"))
        if lat is not None and lat > 0:
            latencies[v] = lat
    div_bps = _max_divergence_bps(prices)

    # Latency arb risk increases with divergence and with a clear latency outlier.
    lat_risk_component = 0.0
    if latencies:
        vals = list(latencies.values())
        mn, mx = min(vals), max(vals)
        if mn > 0:
            lat_risk_component = _clamp01((mx / mn - 1.0) / 2.0)  # 2x slower => 0.5, 3x => 1.0 cap

    div_component = 0.0 if div_bps is None else _clamp01(div_bps / 35.0)  # 35 bps => high risk
    latency_arb_risk = _clamp100(100.0 * (0.65 * div_component + 0.35 * lat_risk_component))

    # Lead-lag alpha score:
    # If precomputed exists use it; else base on venues_seen and divergence (low divergence but multi venues => stable).
    pre = _try_float(a.get("leadlag_alpha_score"))
    if pre is not None:
        leadlag_alpha_score = _clamp100(pre)
    else:
        coverage = 0.0 if venues_seen <= 1 else 0.6 if venues_seen == 2 else 0.85
        stability = 1.0 - _clamp01((div_bps or 0.0) / 60.0)
        leadlag_alpha_score = _clamp100(100.0 * (0.55 * coverage + 0.45 * stability))

    # Route preference:
    route_preference: RoutePreference = "unknown"
    if venues_seen <= 1 or leader_venue == "unknown":
        route_preference = "unknown"
    elif latency_arb_risk >= 75:
        route_preference = "avoid_latency_arb"
    else:
        # If leader has low latency, route there; else prefer best_price
        leader_lat = latencies.get(leader_venue)
        if leader_lat is not None and leader_lat <= (min(latencies.values()) + 5.0):
            route_preference = "leader"
        else:
            route_preference = "best_price"

    # Scores:
    alpha_score = _clamp100(leadlag_alpha_score * _clamp01(data_health))
    risk_score = _clamp100(max(latency_arb_risk, 100.0 * (1.0 - _clamp01(data_health))))

    confidence = _clamp01(0.20 + 0.65 * _clamp01(data_health) + 0.15 * (leadlag_alpha_score / 100.0))
    if venues_seen <= 1:
        confidence = min(confidence, 0.55)

    trade_permission: TradePermission = "ALLOW"
    if data_health < 0.35:
        trade_permission = "BLOCK"
    elif latency_arb_risk >= 85 and confidence >= 0.60:
        trade_permission = "BLOCK"

    return CrossVenueLeadLagResult(
        leader_venue=leader_venue,
        leadlag_alpha_score=int(leadlag_alpha_score),
        latency_arb_risk=int(latency_arb_risk),
        route_preference=route_preference,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        venues_seen=int(venues_seen),
        max_price_divergence_bps=None if div_bps is None else float(round(div_bps, 2)),
    )

