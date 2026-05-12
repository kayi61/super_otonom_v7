"""
Faz 53 — Gamma squeeze: max pain, dealer gamma, net gamma haritası, delta hedge baskısı.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np

_HALF_LIFE_MS = 12_000
_EPS = 1e-9


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


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    for k in ("options_chain", "current_price", "spot_price", "dealer_gamma"):
        if k not in data:
            return False, f"missing_field:{k}"

    if not isinstance(data["options_chain"], list):
        return False, "options_chain_invalid"

    if len(data["options_chain"]) == 0:
        return False, "options_chain_empty"

    try:
        float(data["current_price"])
        float(data["spot_price"])
        float(data["dealer_gamma"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    req_opt = (
        "strike",
        "expiry_days",
        "call_oi",
        "put_oi",
        "call_gamma",
        "put_gamma",
    )
    for i, opt in enumerate(data["options_chain"]):
        if not isinstance(opt, dict):
            return False, f"option_not_dict:{i}"
        for k in req_opt:
            if k not in opt:
                return False, f"missing_option_field:{k}:{i}"
        try:
            float(opt["strike"])
            int(opt["expiry_days"])
            float(opt["call_oi"])
            float(opt["put_oi"])
            float(opt["call_gamma"])
            float(opt["put_gamma"])
        except (TypeError, ValueError):
            return False, f"option_numeric_error:{i}"

    return True, ""


def _strike_pains(options_chain: List[dict], spot: float) -> Tuple[np.ndarray, np.ndarray]:
    strikes: List[float] = []
    pains: List[float] = []
    s = float(spot)
    for opt in options_chain:
        k = float(opt["strike"])
        coi = float(opt["call_oi"])
        poi = float(opt["put_oi"])
        pain = coi * max(s - k, 0.0) + poi * max(k - s, 0.0)
        strikes.append(k)
        pains.append(pain)
    return np.asarray(strikes, dtype=float), np.asarray(pains, dtype=float)


def analyze(market_data: dict | None) -> dict:
    """Gamma squeeze analizi — Faz 53 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 53,
            "module": "gamma_squeeze_engine",
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

    chain: List[dict] = list(d["options_chain"])
    spot = float(d["spot_price"])
    current_price = float(d["current_price"])
    dealer_gamma = float(d["dealer_gamma"])

    strikes, pains = _strike_pains(chain, spot)
    min_idx = int(np.argmin(pains))
    max_pain_strike = float(strikes[min_idx])

    distance_to_max_pain = float((current_price - max_pain_strike) / max(max_pain_strike, _EPS))
    max_pain_pull = _clip01(1.0 - abs(distance_to_max_pain) / 0.1)

    gamma_squeeze_risk = _clip01(-dealer_gamma / 1000.0)

    call_gamma_total = 0.0
    put_gamma_total = 0.0
    for opt in chain:
        call_gamma_total += float(opt["call_oi"]) * float(opt["call_gamma"])
        put_gamma_total += float(opt["put_oi"]) * float(opt["put_gamma"])

    net_gamma = float(call_gamma_total - put_gamma_total)
    denom_g = max(abs(call_gamma_total) + abs(put_gamma_total), _EPS)
    gamma_imbalance = float(net_gamma / denom_g)
    gamma_score = _clip01((gamma_imbalance + 1.0) / 2.0)

    delta_hedge_pressure = _clip01(gamma_squeeze_risk * abs(distance_to_max_pain) * 10.0)

    alpha_score = _clip01(
        0.4 * max_pain_pull + 0.3 * gamma_score + 0.3 * (1.0 - delta_hedge_pressure)
    )
    risk_score = _clip01(
        0.5 * gamma_squeeze_risk + 0.3 * delta_hedge_pressure + 0.2 * (1.0 - max_pain_pull)
    )

    n = len(chain)
    data_health = float(np.clip(n / 10.0, 0.1, 1.0))
    confidence = float(data_health * (1.0 - 0.4 * gamma_squeeze_risk))

    score_type = _pick_score_type(data_health, risk_score)

    nested = {
        "max_pain_strike": max_pain_strike,
        "distance_to_max_pain": float(distance_to_max_pain),
        "max_pain_pull": float(max_pain_pull),
        "dealer_gamma": float(dealer_gamma),
        "gamma_squeeze_risk": float(gamma_squeeze_risk),
        "net_gamma": float(net_gamma),
        "gamma_imbalance": float(gamma_imbalance),
        "gamma_score": float(gamma_score),
        "delta_hedge_pressure": float(delta_hedge_pressure),
    }

    trade_permission = "ALLOW"
    reason = "gamma_squeeze_ok"

    if gamma_squeeze_risk > 0.5:
        trade_permission = "BLOCK"
        reason = "squeeze_risk_high"
    elif risk_score > 0.7:
        trade_permission = "BLOCK"
        reason = "risk_threshold"

    return {
        "phase": 53,
        "module": "gamma_squeeze_engine",
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
