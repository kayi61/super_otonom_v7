"""
Faz 67 — Exchange connectivity engine.

Amaç:
- Borsa gecikmesi, circuit breaker, rate limit baskısı ve failover durumunu ölçüp
  `trade_permission` ile üst katmanlara (Faz 80 vb.) iletmek.

Girdi (analysis, best-effort):
- connectivity_score: 0-100 (opsiyonel; yoksa latency + rate limit ile türetilir)
- exchange_latency_ms: düşük = iyi
- rate_limit_risk | rate_limit_pressure: 0-100 veya 0-1 baskı
- circuit_breaker_state: "OPEN" / "CLOSED" / "HALF_OPEN" vb. (OPEN → ceza)
- failover_active: bool — yedek uç veya yönlendirme aktif
- last_successful_fetch_age_ms: son başarılı çağrı yaşı (büyük = kötü)

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
class ExchangeConnectivityResult:
    # Faz 67 outputs (requested)
    connectivity_score: int  # 0-100
    failover_active: bool
    rate_limit_risk: int  # 0-100
    endpoint_health: int  # 0-100 (uç sağlık skoru)

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


def _latency_quality_score(latency_ms: Optional[float]) -> float:
    if latency_ms is None or latency_ms != latency_ms:
        return 72.0
    if latency_ms <= 0:
        return 50.0
    # 0-80ms → ~100..36; 400ms+ → düşük
    return float(max(0.0, min(100.0, 100.0 - latency_ms / 6.0)))


def evaluate_exchange_connectivity(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 35_000,
) -> ExchangeConnectivityResult:
    """
    Faz 67 — bağlantı ve uç sağlığı özeti.
    """
    a = analysis or {}
    ts = int(event_ts) if isinstance(event_ts, (int, float)) and int(event_ts) > 0 else int(a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    failover_active = bool(a.get("failover_active", False))

    rl_in = a.get("rate_limit_risk")
    if rl_in is not None:
        rate_limit_risk = _clamp100(float(rl_in))
    else:
        rp = _try_float(a.get("rate_limit_pressure"), 0.0) or 0.0
        rp = max(0.0, rp)
        if rp <= 1.0:
            rate_limit_risk = _clamp100(rp * 100.0)
        else:
            rate_limit_risk = _clamp100(rp)

    lat_ms = _try_float(a.get("exchange_latency_ms"), None)
    lat_q = _latency_quality_score(lat_ms)

    cb_raw = str(a.get("circuit_breaker_state", "") or "").strip().upper()
    cb_open = cb_raw.startswith("OPEN")

    fetch_age = _try_float(a.get("last_successful_fetch_age_ms"), None)
    stale_penalty = 0.0
    if fetch_age is not None and fetch_age >= 0 and hl > 0:
        stale_penalty = _clamp01(fetch_age / (3.0 * float(hl)))

    conn_in = a.get("connectivity_score")
    if conn_in is not None:
        connectivity_score = _clamp100(float(conn_in))
    else:
        connectivity_score = _clamp100(
            0.52 * lat_q
            + 0.38 * (100.0 - 0.85 * float(rate_limit_risk))
            - 22.0 * (1.0 if cb_open else 0.0)
            - 28.0 * stale_penalty
        )

    if failover_active:
        connectivity_score = _clamp100(float(connectivity_score) * 0.92)

    endpoint_health = _clamp100(
        0.48 * float(connectivity_score)
        + 0.40 * (100.0 - float(rate_limit_risk))
        + 0.12 * (0.0 if cb_open else 100.0)
    )

    trade_permission: TradePermission = "ALLOW"
    if cb_open and connectivity_score < 22:
        trade_permission = "HALT"
    elif connectivity_score < 38 or rate_limit_risk >= 88:
        trade_permission = "BLOCK"
    elif failover_active and connectivity_score < 52:
        trade_permission = "BLOCK"
    elif stale_penalty >= 0.95:
        trade_permission = "BLOCK"

    risk_score = _clamp100(
        0.45 * float(rate_limit_risk)
        + 0.35 * (100.0 - float(connectivity_score))
        + 20.0 * (1.0 if cb_open else 0.0)
        + 25.0 * stale_penalty
    )

    alpha_score = _clamp100(
        35.0
        + 0.42 * float(connectivity_score)
        + 0.20 * float(endpoint_health)
        - 18.0 * (1.0 if failover_active else 0.0)
    )

    data_health = _clamp01(
        0.45 * (connectivity_score / 100.0)
        + 0.35 * (endpoint_health / 100.0)
        + 0.20 * (1.0 - rate_limit_risk / 120.0)
    )
    if cb_open:
        data_health = min(data_health, 0.42)

    confidence = _clamp01(0.24 + 0.58 * data_health + 0.18 * (1.0 - risk_score / 125.0))

    _ = symbol
    return ExchangeConnectivityResult(
        connectivity_score=int(connectivity_score),
        failover_active=failover_active,
        rate_limit_risk=int(rate_limit_risk),
        endpoint_health=int(endpoint_health),
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(data_health),
        event_ts=ts,
        half_life_ms=hl,
    )
