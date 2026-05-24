"""
Faz 78 — Alpha decay realtime monitor.

Amaç:
- Sinyalin bayatlamasını (signal_age_ms) gerçek zamanlı izlemek.
- event_ts + half_life_ms üzerinden decay hesaplamak, freshness skoru üretmek.
- Bayat sinyallerde exit_urgency yükseltmek (üst katmanlar EXIT/WAIT kararına kaydırır).

Standartlar:
- trade_permission = HALT/BLOCK/ALLOW
- alpha_score + risk_score
- confidence + data_health
- event_ts + half_life_ms
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

TradePermission = Literal["HALT", "BLOCK", "ALLOW"]


@dataclass(frozen=True)
class AlphaDecayResult:
    # Faz 78 outputs (requested)
    alpha_freshness_score: int  # 0-100
    decay_rate: float  # 0..1 (remaining edge fraction)
    exit_urgency: int  # 0-100
    signal_age_ms: int

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

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


def _try_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        v = int(float(x))
        return v
    except (TypeError, ValueError):
        return None


def monitor_alpha_decay(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: Optional[int] = None,
    now_ts: Optional[int] = None,
) -> AlphaDecayResult:
    """
    Minimal, deterministic Faz-78 monitor.

    Inputs:
    - event_ts: signal event timestamp (ms). Prefer analysis["event_ts"] if present.
    - half_life_ms: expected edge half-life in ms. Prefer analysis["half_life_ms"] if present.
    - now_ts: override current time (ms) for testing/replay.
    """
    a = analysis or {}

    ts_in = _try_int(event_ts) if event_ts is not None else _try_int(a.get("event_ts"))
    hl_in = _try_int(half_life_ms) if half_life_ms is not None else _try_int(a.get("half_life_ms"))
    now = int(_try_int(now_ts) if now_ts is not None else _now_ms())

    data_health = 0.85
    if ts_in is None:
        data_health = min(data_health, 0.45)
        ts_in = now  # unknown -> treat as "just now" but with low health/conf
    if hl_in is None:
        data_health = min(data_health, 0.60)
        hl_in = 25_000

    hl = max(2_000, min(300_000, int(hl_in)))
    event_ms = int(ts_in)

    age = max(0, int(now - event_ms))
    # remaining edge fraction using half-life: remaining = 0.5^(age/half_life)
    remaining = float(math.pow(0.5, age / hl)) if hl > 0 else 0.0
    remaining = _clamp01(remaining)

    alpha_freshness_score = _clamp100(remaining * 100.0)

    # exit urgency grows as freshness decays; extra urgency if very stale
    staleness = 1.0 - remaining
    extra = 0.0
    if age >= 2 * hl:
        extra = min(0.25, (age - 2 * hl) / (6 * hl))  # up to +0.25
    exit_urgency = _clamp100(100.0 * (0.70 * staleness + 0.30 * _clamp01(staleness + extra)))

    # Scores: this phase is ALPHA QUALITY monitor; alpha_score tracks freshness.
    alpha_score = int(alpha_freshness_score)
    risk_score = _clamp100(100.0 * staleness + 100.0 * (1.0 - _clamp01(data_health)) * 0.35)

    # Confidence: requires correct ts + half-life; if missing, confidence drops.
    confidence = _clamp01(0.20 + 0.70 * _clamp01(data_health) + 0.10 * remaining)

    # trade_permission: do not HALT; can BLOCK only if timing inputs unusable.
    trade_permission: TradePermission = "ALLOW"
    if data_health < 0.35:
        trade_permission = "BLOCK"

    _ = symbol
    return AlphaDecayResult(
        alpha_freshness_score=int(alpha_freshness_score),
        decay_rate=float(round(remaining, 6)),
        exit_urgency=int(exit_urgency),
        signal_age_ms=int(age),
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(_clamp01(data_health)),
        event_ts=int(event_ms),
        half_life_ms=int(hl),
    )
