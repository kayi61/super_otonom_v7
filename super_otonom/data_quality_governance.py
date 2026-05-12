"""
Faz 66 — Data quality governance.

Amaç:
- Besleme kaynağı güveni, eksik alanlar ve karantina/geri alma sinyallerini ölçüp
  `trade_permission` ile Faz 80 / operasyon katmanına tek çatı altında iletmek.

Girdi (analysis, best-effort):
- data_quality_score: 0-100 (önceden hesaplanmış; yoksa iç heuristik)
- source_trust_score: 0-100 (önceden; yoksa varsayılan + tamlık bonusu)
- quarantine_flag, rollback_required: bool
- signal_age_ms, half_life_ms: tazelik (bayat veri riski)

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

_CORE_KEYS = ("regime", "volatility", "signal", "liquidity_ratio", "order_book", "event_ts")


@dataclass(frozen=True)
class DataQualityGovernanceResult:
    # Faz 66 outputs (requested)
    data_quality_score: int  # 0-100
    source_trust_score: int  # 0-100
    quarantine_flag: bool
    rollback_required: bool

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


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _clamp100(x: float) -> int:
    if x != x:
        return 0
    return int(max(0, min(100, round(x))))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _try_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _try_int(x: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if x is None:
            return default
        return int(float(x))
    except (TypeError, ValueError):
        return default


def evaluate_data_quality_governance(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 40_000,
) -> DataQualityGovernanceResult:
    """
    Faz 66 — veri kalitesi ve kaynak güveni özeti.
    """
    a = analysis or {}
    ts = (
        int(event_ts)
        if isinstance(event_ts, (int, float)) and int(event_ts) > 0
        else int(a.get("event_ts") or _now_ms())
    )
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    present = sum(1 for k in _CORE_KEYS if a.get(k) is not None)
    completeness = present / max(len(_CORE_KEYS), 1)

    dq_in = a.get("data_quality_score")
    if dq_in is not None:
        data_quality_score = _clamp100(float(dq_in))
    else:
        data_quality_score = _clamp100(28.0 + 52.0 * completeness)

    st_in = a.get("source_trust_score")
    if st_in is not None:
        source_trust_score = _clamp100(float(st_in))
    else:
        source_trust_score = _clamp100(55.0 + 30.0 * completeness)

    signal_age = _try_int(a.get("signal_age_ms"), None)
    if signal_age is not None and signal_age > 0 and hl > 0:
        stale = _clamp01(float(signal_age) / (2.5 * float(hl)))
        data_quality_score = _clamp100(float(data_quality_score) * (1.0 - 0.35 * stale))
        source_trust_score = _clamp100(float(source_trust_score) * (1.0 - 0.25 * stale))

    rollback_required = bool(a.get("rollback_required", False))
    quarantine_flag = bool(a.get("quarantine_flag", False))
    if data_quality_score < 28:
        quarantine_flag = True

    trade_permission: TradePermission = "ALLOW"
    if rollback_required:
        trade_permission = "HALT"
    elif quarantine_flag or data_quality_score < 42 or source_trust_score < 38:
        trade_permission = "BLOCK"

    risk_score = _clamp100(
        22.0 * (1.0 if quarantine_flag else 0.0)
        + 35.0 * (1.0 if rollback_required else 0.0)
        + 38.0 * (1.0 - _clamp01(data_quality_score / 100.0))
        + 28.0 * (1.0 - _clamp01(source_trust_score / 100.0))
    )

    alpha_score = _clamp100(
        42.0
        + 0.38 * float(data_quality_score)
        + 0.22 * float(source_trust_score)
        - 30.0 * (1.0 if quarantine_flag else 0.0)
        - 40.0 * (1.0 if rollback_required else 0.0)
    )

    data_health = _clamp01(
        0.55 * (data_quality_score / 100.0) + 0.45 * (source_trust_score / 100.0)
    )
    if rollback_required:
        data_health = min(data_health, 0.35)
    elif quarantine_flag:
        data_health = min(data_health, 0.55)

    confidence = _clamp01(0.20 + 0.62 * data_health + 0.18 * (1.0 - risk_score / 120.0))

    _ = symbol
    return DataQualityGovernanceResult(
        data_quality_score=int(data_quality_score),
        source_trust_score=int(source_trust_score),
        quarantine_flag=quarantine_flag,
        rollback_required=rollback_required,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(data_health),
        event_ts=ts,
        half_life_ms=hl,
    )
