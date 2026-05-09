"""
Faz 40 — Sistem watchdog: servis sağlığı, veri tazeliği, borsa bağlantısı.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Tuple

import numpy as np

_EPS = 1e-12
_HALF_LIFE_MS = 5_000

TradePermission = Literal["ALLOW", "BLOCK", "HALT"]


def _clip01(x: float | np.floating) -> float:
    return float(np.clip(np.asarray(x, dtype=float), 0.0, 1.0))


def _now_ms() -> float:
    return float(time.time() * 1000.0)


def _pick_score_type(data_health: float, risk_score: float) -> str:
    if data_health < 0.42:
        return "QUALITY"
    if risk_score >= 0.72:
        return "RISK"
    return "ALPHA"


def _normalize_status(st: Any) -> str:
    return str(st).strip().lower()


def compute_service_metrics(services: List[Dict[str, Any]]) -> Tuple[float, float, List[str], float]:
    """service_health, avg_latency, critical_down_names, latency_score."""
    if not services:
        return 0.0, 0.0, [], 1.0

    up = 0
    latencies: List[float] = []
    critical_down: List[str] = []

    for s in services:
        if not isinstance(s, dict):
            continue
        try:
            lat = float(s.get("latency_ms", 0.0))
        except (TypeError, ValueError):
            lat = 0.0
        latencies.append(lat)

        st = _normalize_status(s.get("status", ""))
        if st == "up":
            up += 1

        crit = bool(s.get("critical", False))
        if crit and st == "down":
            nm = str(s.get("name", "?"))
            critical_down.append(nm)

    n = len(services)
    service_health = up / max(n, 1)
    avg_lat = float(np.mean(np.asarray(latencies, dtype=float))) if latencies else 0.0
    latency_score = _clip01(1.0 - avg_lat / 1000.0)
    return service_health, avg_lat, critical_down, latency_score


def compute_freshness_metrics(
    data_feeds: List[Dict[str, Any]],
    current_ts_ms: float,
) -> Tuple[float, int]:
    """freshness_score [0,1], stale_feeds_count."""
    now = float(current_ts_ms)
    if not data_feeds:
        return 1.0, 0

    stale = 0
    for f in data_feeds:
        if not isinstance(f, dict):
            continue
        try:
            lu = float(f["last_update_ms"])
            mx = float(f["max_age_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        if (now - lu) > mx + _EPS:
            stale += 1

    n = len(data_feeds)
    freshness_score = 1.0 - float(stale) / max(n, 1)
    return float(np.clip(freshness_score, 0.0, 1.0)), stale


def compute_exchange_metrics(
    exchange_connections: List[Dict[str, Any]],
) -> Tuple[float, float, float, int]:
    """exchange_health, avg_ping (connected only), ping_score, connected_count."""
    if not exchange_connections:
        return 0.0, 500.0, 0.0, 0

    pings: List[float] = []
    conn = 0
    for e in exchange_connections:
        if not isinstance(e, dict):
            continue
        if bool(e.get("connected", False)):
            conn += 1
            try:
                pings.append(float(e.get("ping_ms", 0.0)))
            except (TypeError, ValueError):
                pings.append(0.0)

    n = len(exchange_connections)
    exchange_health = conn / max(n, 1)
    if pings:
        avg_ping = float(np.mean(np.asarray(pings, dtype=float)))
    else:
        avg_ping = 500.0 if conn == 0 else 0.0
    ping_score = _clip01(1.0 - avg_ping / 500.0)
    return exchange_health, avg_ping, ping_score, conn


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    if "services" not in data or "data_feeds" not in data or "exchange_connections" not in data:
        return False, "missing_required_keys"

    if "current_ts_ms" not in data:
        return False, "missing_current_ts_ms"

    if not isinstance(data["services"], list):
        return False, "services_not_list"

    if not isinstance(data["data_feeds"], list):
        return False, "data_feeds_not_list"

    if not isinstance(data["exchange_connections"], list):
        return False, "exchange_connections_not_list"

    try:
        float(data["current_ts_ms"])
    except (TypeError, ValueError):
        return False, "current_ts_invalid"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Sistem watchdog özeti — Faz 40 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 40,
            "module": "system_watchdog",
            "trade_permission": "HALT",
            "alpha_score": 0.0,
            "risk_score": 1.0,
            "score_type": "QUALITY",
            "confidence": 0.0,
            "data_health": 0.0,
            "event_ts": ts,
            "half_life_ms": _HALF_LIFE_MS,
            "analysis": empty,
            "reason": err,
        }

    assert market_data is not None
    d = market_data

    services = d["services"]
    if len(services) == 0:
        return {
            "phase": 40,
            "module": "system_watchdog",
            "trade_permission": "HALT",
            "alpha_score": 0.0,
            "risk_score": 1.0,
            "score_type": "QUALITY",
            "confidence": 0.0,
            "data_health": 0.0,
            "event_ts": ts,
            "half_life_ms": _HALF_LIFE_MS,
            "analysis": empty,
            "reason": "services_empty",
        }

    data_feeds = d["data_feeds"]
    exch = d["exchange_connections"]
    cur_ts = float(d["current_ts_ms"])

    service_health, avg_latency, critical_down, _latency_sc = compute_service_metrics(services)
    freshness_score, stale_count = compute_freshness_metrics(data_feeds, cur_ts)
    exchange_health, avg_ping, _ping_sc, connected_exchanges = compute_exchange_metrics(exch)

    weighted_health = 0.4 * service_health + 0.3 * freshness_score + 0.3 * exchange_health
    risk_score = _clip01(1.0 - weighted_health)
    alpha_score = _clip01(1.0 - risk_score)

    n_sources = len(services) + len(data_feeds) + len(exch)
    data_health = float(np.clip(n_sources / 20.0, 0.1, 1.0))
    confidence = _clip01(data_health * (1.0 - risk_score * 0.4))

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission: TradePermission = "ALLOW"
    reason = "system_healthy"

    if critical_down:
        trade_permission = "HALT"
        reason = "critical_service_down:" + ",".join(sorted(critical_down))
    elif exchange_health < 0.5:
        trade_permission = "BLOCK"
        reason = "exchange_health_low"
    elif stale_count > 0:
        trade_permission = "BLOCK"
        reason = "stale_data_feeds"

    nested = {
        "service_health": float(service_health),
        "freshness_score": float(freshness_score),
        "exchange_health": float(exchange_health),
        "critical_down_services": list(critical_down),
        "stale_feeds_count": int(stale_count),
        "avg_latency": float(avg_latency),
        "avg_ping": float(avg_ping),
        "connected_exchanges": int(connected_exchanges),
    }

    return {
        "phase": 40,
        "module": "system_watchdog",
        "trade_permission": trade_permission,
        "alpha_score": alpha_score,
        "risk_score": risk_score,
        "score_type": score_type,
        "confidence": confidence,
        "data_health": data_health,
        "event_ts": ts,
        "half_life_ms": _HALF_LIFE_MS,
        "analysis": nested,
        "reason": reason,
    }
