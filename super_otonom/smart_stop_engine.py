"""
Faz 77 — Smart Stop Engine (dynamic stop + stop-hunt aware).

Amaç:
- Sabit stop yerine dinamik stop üretmek.
- MM stop-hunt riski yüksekse stop'u "çok obvious" bölgeden uzaklaştırmak (widen/offset).

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
TrailMode = Literal["off", "atr", "chandelier", "unknown"]
StopPlacementHint = Literal["widen", "tighten", "keep", "unknown"]


@dataclass(frozen=True)
class SmartStopResult:
    # Faz 77 outputs (requested)
    dynamic_stop_level: float
    hunt_risk_score: int  # 0-100
    stop_placement_hint: StopPlacementHint
    trail_mode: TrailMode

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Optional debug
    atr: Optional[float] = None
    side: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _clamp100(x: float) -> int:
    if x != x:  # NaN
        return 0
    return int(max(0, min(100, round(x))))


def _try_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def compute_smart_stop(
    *,
    symbol: str,
    side: Literal["LONG", "SHORT"],
    last_price: float,
    analysis: Optional[Dict[str, Any]] = None,
    # Optional: upstream phases can pass hunt risk (e.g., Faz 73 manipulation_risk_score)
    hunt_risk_score: Optional[int] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 35_000,
) -> SmartStopResult:
    """
    Minimal, deterministic smart stop calculator.

    Inputs:
    - side: LONG/SHORT
    - last_price: current / mark price
    - analysis: may include "atr", "volatility", "regime"
    - hunt_risk_score: optional external risk proxy (0-100)
    """
    a = analysis or {}
    ts = int(event_ts if event_ts is not None else a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    lp = float(last_price)
    if lp <= 0:
        lp = 1.0

    atr = _try_float(a.get("atr"))
    vol = _try_float(a.get("volatility"))
    regime = str(a.get("regime", "") or "").upper()

    # Data health depends on having ATR or volatility proxy.
    data_health = 0.84
    if atr is None:
        data_health = min(data_health, 0.70)
    if vol is None:
        data_health = min(data_health, 0.75)

    # If hunt_risk not provided, approximate from volatility + regime.
    if hunt_risk_score is None:
        v = 0.02 if vol is None else max(0.0, float(vol))
        v_comp = min(1.0, v / 0.06)
        reg_comp = 0.0
        if "CRISIS" in regime or "FLASH" in regime or "PANIC" in regime:
            reg_comp = 1.0
        elif "VOLAT" in regime:
            reg_comp = 0.7
        elif "NOISY" in regime:
            reg_comp = 0.4
        hunt_risk = _clamp100(100.0 * (0.55 * v_comp + 0.45 * reg_comp))
    else:
        hunt_risk = _clamp100(hunt_risk_score)

    # ATR fallback: use volatility percentage if ATR missing
    if atr is None or atr <= 0:
        v = 0.02 if vol is None else max(0.0, float(vol))
        atr = max(0.0001, lp * (0.6 * v))

    # Base stop distance: ATR multiple (wider for higher hunt risk)
    # Example: 1.6 ATR at low risk → up to ~2.6 ATR at high risk.
    atr_mult = 1.60 + 1.00 * (hunt_risk / 100.0)
    stop_dist = float(atr) * float(atr_mult)

    # Additional offset to avoid "obvious" round levels when hunt risk is high.
    offset = stop_dist * (0.08 * (hunt_risk / 100.0))
    stop_dist_adj = stop_dist + offset

    if side == "LONG":
        dynamic_stop_level = max(0.0001, lp - stop_dist_adj)
    else:
        dynamic_stop_level = lp + stop_dist_adj

    # Hint + trail mode
    if hunt_risk >= 75:
        stop_placement_hint = "widen"
    elif hunt_risk <= 30:
        stop_placement_hint = "tighten"
    else:
        stop_placement_hint = "keep"

    if "TREND" in regime:
        trail_mode = "chandelier"
    elif "RANGE" in regime or "MEAN" in regime:
        trail_mode = "off"
    elif "VOLAT" in regime or "CRISIS" in regime:
        trail_mode = "atr"
    else:
        trail_mode = "unknown"

    # Scores: stop engine is mostly RISK/QUALITY.
    risk_score = _clamp100(hunt_risk * 0.95 + 100.0 * (1.0 - _clamp01(data_health)) * 0.25)
    alpha_score = _clamp100(max(0.0, 35.0 - hunt_risk * 0.25))

    # Confidence
    confidence = _clamp01(0.25 + 0.65 * _clamp01(data_health) + 0.10 * (hunt_risk / 100.0))

    # trade_permission: stop logic alone should not HALT; block only if data_health very poor.
    trade_permission: TradePermission = "ALLOW"
    if data_health < 0.35:
        trade_permission = "BLOCK"

    _ = symbol
    return SmartStopResult(
        dynamic_stop_level=float(dynamic_stop_level),
        hunt_risk_score=int(hunt_risk),
        stop_placement_hint=stop_placement_hint,
        trail_mode=trail_mode,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(_clamp01(confidence)),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        atr=float(atr) if atr is not None else None,
        side=str(side),
    )

