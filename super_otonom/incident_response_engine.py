"""
Faz 70 — Incident response engine.

Amaç:
- Olay şiddeti, kayıt durumu, kök neden şablonu ve SLO ihlallerini tek
  `trade_permission` ile üst katmana iletmek (observability / runbook uyumu).

Girdi (analysis, best-effort):
- incident_active: bool — olay devam ediyor
- incident_severity: "none"|"low"|"medium"|"high"|"critical" (veya 0-100 int → iç seviyeye map)
- incident_recorded: bool — olay deftere işlendi mi (yoksa otomatik True olay varsa)
- root_cause_template: str — önceden seçilmiş şablon kodu
- postmortem_ready: bool — kök neden analizi tamam mı
- slo_breach: bool — SLO ihlali

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
IncidentSeverity = Literal["none", "low", "medium", "high", "critical"]

_SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class IncidentResponseResult:
    # Faz 70 outputs (requested)
    incident_severity: IncidentSeverity
    incident_recorded: bool
    root_cause_template: str
    postmortem_ready: bool
    slo_breach: bool

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


def _normalize_severity(raw: Any) -> IncidentSeverity:
    if isinstance(raw, (int, float)):
        v = int(round(float(raw)))
        if v >= 90:
            return "critical"
        if v >= 70:
            return "high"
        if v >= 45:
            return "medium"
        if v >= 20:
            return "low"
        return "none"
    s = str(raw or "").strip().lower()
    if s in _SEVERITY_RANK:
        return s  # type: ignore[return-value]
    return "none"


def _default_root_cause(sev: IncidentSeverity, slo: bool) -> str:
    if slo and sev in ("high", "critical"):
        return "SLO_BREACH_LATENCY_OR_AVAILABILITY"
    if sev == "critical":
        return "CRITICAL_INCIDENT_UNKNOWN_SUBSYSTEM"
    if sev == "high":
        return "HIGH_SEVERITY_ESCALATION_REQUIRED"
    if sev == "medium":
        return "MEDIUM_INCIDENT_MONITOR_AND_CONTAIN"
    if sev == "low":
        return "LOW_INCIDENT_INFORMATIONAL"
    return "NO_ACTIVE_INCIDENT"


def evaluate_incident_response(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 90_000,
) -> IncidentResponseResult:
    """
    Faz 70 — olay müdahalesi özeti.
    """
    a = analysis or {}
    ts = (
        int(event_ts)
        if isinstance(event_ts, (int, float)) and int(event_ts) > 0
        else int(a.get("event_ts") or _now_ms())
    )
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(600_000, hl))

    slo_breach = bool(a.get("slo_breach", False))
    incident_active = bool(a.get("incident_active", False))

    sev_raw = a.get("incident_severity")
    incident_severity = _normalize_severity(sev_raw)
    if incident_active and incident_severity == "none":
        incident_severity = "medium"

    postmortem_ready = bool(a.get("postmortem_ready", False))

    rc_in = a.get("root_cause_template")
    if isinstance(rc_in, str) and rc_in.strip():
        root_cause_template = rc_in.strip()
    else:
        root_cause_template = _default_root_cause(incident_severity, slo_breach)

    recorded_in = a.get("incident_recorded")
    if recorded_in is not None:
        incident_recorded = bool(recorded_in)
    else:
        incident_recorded = (
            incident_active or slo_breach or (_SEVERITY_RANK[incident_severity] >= 2)
        )

    rank = _SEVERITY_RANK[incident_severity]

    trade_permission: TradePermission = "ALLOW"
    if slo_breach and rank >= 3:
        trade_permission = "HALT"
    elif incident_severity == "critical" or (slo_breach and rank >= 2):
        trade_permission = "HALT"
    elif rank >= 2 or slo_breach:
        trade_permission = "BLOCK"
    elif rank == 1 and incident_active:
        trade_permission = "BLOCK"

    risk_score = _clamp100(
        12.0 * float(rank)
        + 35.0 * (1.0 if slo_breach else 0.0)
        + 22.0 * (1.0 if incident_active else 0.0)
        + 18.0 * (0.0 if postmortem_ready else 1.0 if rank >= 2 else 0.0)
    )

    alpha_score = _clamp100(
        72.0
        - 14.0 * float(rank)
        - 25.0 * (1.0 if slo_breach else 0.0)
        - 10.0 * (1.0 if incident_active else 0.0)
    )

    data_health = _clamp01(0.88 - 0.14 * float(rank) - 0.22 * (1.0 if slo_breach else 0.0))
    if incident_severity == "critical":
        data_health = min(data_health, 0.48)

    confidence = _clamp01(0.22 + 0.58 * data_health + 0.20 * (1.0 - risk_score / 118.0))

    _ = symbol
    return IncidentResponseResult(
        incident_severity=incident_severity,
        incident_recorded=incident_recorded,
        root_cause_template=root_cause_template,
        postmortem_ready=postmortem_ready,
        slo_breach=slo_breach,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(data_health),
        event_ts=ts,
        half_life_ms=hl,
    )
