"""
Faz 69 — Backtest leakage guard.

Amaç:
- Look-ahead bias, veri sızıntısı ve yanlış çapraz doğrulama (purged K-fold vb.)
  riskini tek `trade_permission` ve skorlarla üst katmana iletmek.
  Canlı tick'te genelde kapalı bayraklar; araştırma / backtest pipeline'ından beslenir.

Girdi (analysis, best-effort):
- lookahead_detected, data_snooping_warning, purged_cv_required: bool
- leakage_risk_score: 0-100 (önceden hesaplanmış; yoksa bayraklardan türetilir)
- backtest_integrity_breach: bool — ciddi ihlal (HALT adayı)

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


@dataclass(frozen=True)
class BacktestLeakageGuardResult:
    # Faz 69 outputs (requested)
    leakage_risk_score: int  # 0-100
    lookahead_detected: bool
    data_snooping_warning: bool
    purged_cv_required: bool

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


def evaluate_backtest_leakage_guard(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 120_000,
) -> BacktestLeakageGuardResult:
    """
    Faz 69 — sızıntı / look-ahead koruma özeti.
    """
    a = analysis or {}
    ts = int(event_ts) if isinstance(event_ts, (int, float)) and int(event_ts) > 0 else int(a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(600_000, hl))

    lookahead_detected = bool(a.get("lookahead_detected", False))
    data_snooping_warning = bool(a.get("data_snooping_warning", False))
    purged_cv_required = bool(a.get("purged_cv_required", False))
    integrity_breach = bool(a.get("backtest_integrity_breach", False))

    lr_in = a.get("leakage_risk_score")
    if lr_in is not None:
        leakage_risk_score = _clamp100(float(lr_in))
    else:
        base = 12.0
        base += 38.0 * (1.0 if lookahead_detected else 0.0)
        base += 28.0 * (1.0 if data_snooping_warning else 0.0)
        base += 18.0 * (1.0 if purged_cv_required else 0.0)
        leakage_risk_score = _clamp100(base)

    if integrity_breach:
        leakage_risk_score = max(leakage_risk_score, 96)

    trade_permission: TradePermission = "ALLOW"
    if integrity_breach or (lookahead_detected and leakage_risk_score >= 92):
        trade_permission = "HALT"
    elif (
        lookahead_detected
        or data_snooping_warning
        or purged_cv_required
        or leakage_risk_score >= 55
    ):
        trade_permission = "BLOCK"

    risk_score = _clamp100(
        float(leakage_risk_score) * 0.88
        + 8.0 * (1.0 if integrity_breach else 0.0)
    )

    alpha_score = _clamp100(
        78.0
        - 0.55 * float(leakage_risk_score)
        - 12.0 * (1.0 if lookahead_detected else 0.0)
        - 8.0 * (1.0 if data_snooping_warning else 0.0)
    )

    data_health = _clamp01(0.92 - 0.65 * (float(leakage_risk_score) / 100.0))
    if integrity_breach:
        data_health = min(data_health, 0.25)
    elif trade_permission == "BLOCK":
        data_health = min(data_health, 0.62)

    confidence = _clamp01(0.26 + 0.58 * data_health + 0.16 * (1.0 - risk_score / 115.0))

    _ = symbol
    return BacktestLeakageGuardResult(
        leakage_risk_score=int(leakage_risk_score),
        lookahead_detected=lookahead_detected,
        data_snooping_warning=data_snooping_warning,
        purged_cv_required=purged_cv_required,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(data_health),
        event_ts=ts,
        half_life_ms=hl,
    )
