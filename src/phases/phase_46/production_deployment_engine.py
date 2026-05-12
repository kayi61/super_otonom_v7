"""
Faz 46 — Üretim dağıtım: Paper/Shadow/Live, pozisyon durum makinesi, onay kapısı.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Literal, Set, Tuple

import numpy as np

_EPS = 1e-12
_HALF_LIFE_MS = 20_000

DeploymentState = Literal["PAPER", "SHADOW", "LIVE"]
PositionState = Literal["WAIT", "ENTER", "HEDGE", "EXIT", "HALT"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_VALID_FROM: Dict[str, Set[str]] = {
    "WAIT": {"ENTER", "EXIT", "HALT"},
    "ENTER": {"HEDGE", "WAIT", "HALT"},
    "HEDGE": {"WAIT", "HALT"},
    "EXIT": {"WAIT", "HALT"},
    "HALT": {"WAIT", "HALT"},
}


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


def deployment_score(state: str) -> Tuple[float, bool]:
    s = str(state).strip().upper()
    if s == "PAPER":
        return 0.3, True
    if s == "SHADOW":
        return 0.6, True
    if s == "LIVE":
        return 1.0, True
    return 0.0, False


def is_transition_valid(current: str, requested: str) -> bool:
    cur = str(current).strip().upper()
    req = str(requested).strip().upper()
    if cur == "ENTER" and req == "EXIT":
        return False
    allowed = _VALID_FROM.get(cur)
    if allowed is None:
        return False
    return req in allowed


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    req = (
        "deployment_state",
        "current_position",
        "requested_position",
        "cooldown_remaining_ms",
        "human_approval_required",
        "human_approved",
        "paper_sharpe",
        "shadow_sharpe",
        "uptime_hours",
    )
    for k in req:
        if k not in data:
            return False, f"missing_field:{k}"

    try:
        float(data["cooldown_remaining_ms"])
        float(data["paper_sharpe"])
        float(data["shadow_sharpe"])
        float(data["uptime_hours"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Üretim dağıtım analizi — Faz 46 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 46,
            "module": "production_deployment_engine",
            "trade_permission": "BLOCK",
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

    dep = str(d["deployment_state"]).strip().upper()
    d_score, dep_ok = deployment_score(dep)

    cur_pos = str(d["current_position"]).strip().upper()
    req_pos = str(d["requested_position"]).strip().upper()
    cooldown = float(d["cooldown_remaining_ms"])
    hum_req = bool(d["human_approval_required"])
    hum_ok = bool(d["human_approved"])
    paper_s = float(d["paper_sharpe"])
    shadow_s = float(d["shadow_sharpe"])
    uptime_h = float(d["uptime_hours"])

    transition_valid = is_transition_valid(cur_pos, req_pos)

    perf_score = _clip01((paper_s + shadow_s) / 4.0)
    uptime_score = _clip01(uptime_h / 72.0)

    alpha_score = _clip01(
        0.4 * float(d_score)
        + 0.4 * perf_score
        + 0.2 * uptime_score
    )
    risk_score = _clip01(1.0 - alpha_score)

    if paper_s < 0.5:
        risk_score = _clip01(risk_score + 0.12)
        alpha_score = _clip01(1.0 - risk_score)

    data_health = float(np.clip(uptime_h / 24.0, 0.1, 1.0))
    confidence = _clip01(data_health * (1.0 - 0.3 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission: TradePermission = "ALLOW"
    reason = "deployment_ok"

    if not dep_ok:
        trade_permission = "BLOCK"
        reason = "invalid_deployment_state"
    elif cooldown > _EPS:
        trade_permission = "BLOCK"
        reason = "cooldown_active"
    elif not transition_valid:
        trade_permission = "BLOCK"
        reason = "invalid_state_transition"
    elif dep == "LIVE" and not hum_ok:
        trade_permission = "BLOCK"
        reason = "live_requires_approval"
    elif hum_req and not hum_ok:
        trade_permission = "BLOCK"
        reason = "awaiting_human_approval"
    elif transition_valid and req_pos == "HALT":
        trade_permission = "HALT"
        reason = "halt_requested"

    nested = {
        "deployment_state": dep,
        "deployment_score": float(d_score),
        "current_position": cur_pos,
        "requested_position": req_pos,
        "transition_valid": bool(transition_valid),
        "cooldown_remaining_ms": float(cooldown),
        "human_approval_required": hum_req,
        "human_approved": hum_ok,
        "perf_score": float(perf_score),
        "uptime_score": float(uptime_score),
    }

    return {
        "phase": 46,
        "module": "production_deployment_engine",
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
