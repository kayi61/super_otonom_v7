"""
Faz 47 — Smart Order Router.

Amaç:
- Faz 74 (lead/lag, route_preference, leader_venue) + `analysis["venues"]` + Faz 80 kararından
  gerçek emir yönlendirmesi için tercih edilen venue üretmek.

Not:
- Seçenek 3: venue seçimi burada; nihai ENTER/WAIT Faz 80'de kalır.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple


def _get(d: Any, key: str, default: Any = None) -> Any:
    if d is None:
        return default
    if isinstance(d, dict):
        return d.get(key, default)
    return getattr(d, key, default)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _lowest_latency_venue(venues: Dict[str, Any]) -> Tuple[str, str]:
    """(venue_id, reason_suffix) — yoksa ('', 'no_latency')."""
    best_k = ""
    best_lat = float("inf")
    for k, d in venues.items():
        if not isinstance(d, dict):
            continue
        try:
            lat = float(d.get("latency_ms", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lat > 0 and lat < best_lat:
            best_lat = lat
            best_k = str(k)
    return best_k, ("crisis_lowest_latency" if best_k else "no_latency")


@dataclass(frozen=True)
class SmartOrderRouteResult:
    preferred_venue: str
    route_preference: str
    leader_venue: str
    execution_mode: str  # Faz 76 regime_execution_mode
    reason: str
    venues_available: int
    event_ts: int
    half_life_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_smart_order_route(
    *,
    symbol: str,
    analysis: Dict[str, Any],
    phase74: Any,
    phase80: Any,
    phase76: Any = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 20_000,
) -> SmartOrderRouteResult:
    """
    Faz 47: venue önerisi. BLOCK/HALT veya HALT final_action → boş venue.
    Faz 76 regime_execution_mode (execution_mode): crisis → en düşük latency venue tercihi.
    """
    _ = symbol
    venues = analysis.get("venues")
    if not isinstance(venues, dict):
        venues = {}

    exec_mode = str(_get(phase76, "regime_execution_mode", "unknown") or "unknown")
    leader = str(_get(phase74, "leader_venue", "") or "").strip()
    pref = str(_get(phase74, "route_preference", "unknown") or "unknown")
    final_action = str(_get(phase80, "final_action", "WAIT"))
    perm = str(_get(phase80, "trade_permission", "ALLOW"))

    ts = int(event_ts) if isinstance(event_ts, (int, float)) and int(event_ts) > 0 else _now_ms()
    hl = max(2_000, min(300_000, int(half_life_ms)))

    def _ret(
        preferred: str,
        reason: str,
        n: int,
    ) -> SmartOrderRouteResult:
        return SmartOrderRouteResult(
            preferred_venue=preferred,
            route_preference=pref,
            leader_venue=leader,
            execution_mode=exec_mode,
            reason=reason,
            venues_available=n,
            event_ts=ts,
            half_life_ms=hl,
        )

    if perm in ("BLOCK", "HALT") or final_action == "HALT":
        return _ret("", "blocked_or_halt", len(venues))

    if not venues:
        return _ret(leader, "no_venues_use_leader_hint", 0)

    if exec_mode == "crisis":
        fast, rsn = _lowest_latency_venue(venues)
        if fast:
            return _ret(fast, rsn, len(venues))

    if leader and leader in venues:
        return _ret(leader, "leader_present", len(venues))

    first = next(iter(venues.keys()))
    return _ret(str(first), "fallback_first_venue", len(venues))
