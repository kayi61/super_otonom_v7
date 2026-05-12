"""
Faz 51 — Market Maker tahmin motoru: envanter, quote migration, hedge flow.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np

_HALF_LIFE_MS = 6_000
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


def inventory_direction(mm_inventory_ratio: float) -> str:
    r = float(mm_inventory_ratio)
    if r > 0.3:
        return "LONG_HEAVY"
    if r < -0.3:
        return "SHORT_HEAVY"
    return "BALANCED"


def expected_mm_direction_from_flow(flow_imbalance: float) -> str:
    x = float(flow_imbalance)
    if x < -0.3:
        return "WILL_BUY"
    if x > 0.3:
        return "WILL_SELL"
    return "NEUTRAL"


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    req_top = (
        "mm_inventory_ratio",
        "quote_history",
        "trade_flow",
        "mid_price",
        "volatility",
    )
    for k in req_top:
        if k not in data:
            return False, f"missing_field:{k}"

    try:
        float(data["mm_inventory_ratio"])
        float(data["mid_price"])
        float(data["volatility"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    if not isinstance(data["quote_history"], list):
        return False, "quote_history_invalid"
    if not isinstance(data["trade_flow"], list):
        return False, "trade_flow_invalid"

    if len(data["quote_history"]) == 0:
        return False, "quote_history_empty"

    mid = float(data["mid_price"])
    if mid <= 0.0:
        return False, "mid_price_non_positive"

    for i, q in enumerate(data["quote_history"]):
        if not isinstance(q, dict):
            return False, f"quote_not_dict:{i}"
        for k in ("bid", "ask", "ts"):
            if k not in q:
                return False, f"missing_quote_field:{k}:{i}"
        try:
            float(q["bid"])
            float(q["ask"])
            float(q["ts"])
        except (TypeError, ValueError):
            return False, f"quote_numeric_error:{i}"

    for i, t in enumerate(data["trade_flow"]):
        if not isinstance(t, dict):
            return False, f"trade_not_dict:{i}"
        for k in ("size", "side", "ts"):
            if k not in t:
                return False, f"missing_trade_field:{k}:{i}"
        try:
            float(t["size"])
            float(t["ts"])
        except (TypeError, ValueError):
            return False, f"trade_numeric_error:{i}"
        side = t["side"]
        if side not in ("buy", "sell"):
            return False, f"trade_side_invalid:{i}"

    return True, ""


def _quote_spreads(quotes: List[dict]) -> np.ndarray:
    spreads: List[float] = []
    for q in quotes:
        spreads.append(float(q["ask"]) - float(q["bid"]))
    return np.asarray(spreads, dtype=float)


def analyze(market_data: dict | None) -> dict:
    """MM tahmin analizi — Faz 51 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 51,
            "module": "mm_prediction_engine",
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

    mm_ir = float(d["mm_inventory_ratio"])
    mid_price = float(d["mid_price"])
    volatility = float(d["volatility"])

    inventory_pressure = abs(mm_ir)
    inv_dir = inventory_direction(mm_ir)
    inventory_risk = _clip01(inventory_pressure / 0.5)

    qh = list(d["quote_history"])
    spreads = _quote_spreads(qh)
    last5 = spreads[-5:] if spreads.size >= 5 else spreads
    avg_spread = float(np.mean(last5))

    if spreads.size >= 10:
        prev5_avg = float(np.mean(spreads[-10:-5]))
        last5_avg = float(np.mean(spreads[-5:]))
        spread_trend = last5_avg - prev5_avg
    else:
        spread_trend = 0.0

    spread_widening = bool(spread_trend > 0.0)

    migration_score = _clip01(avg_spread / mid_price / 0.002)

    buy_flow = 0.0
    sell_flow = 0.0
    for t in d["trade_flow"]:
        sz = float(t["size"])
        if t["side"] == "buy":
            buy_flow += sz
        else:
            sell_flow += sz

    denom = max(buy_flow + sell_flow, _EPS)
    flow_imbalance = float((buy_flow - sell_flow) / denom)
    hedge_pressure = abs(flow_imbalance)
    exp_mm_dir = expected_mm_direction_from_flow(flow_imbalance)

    vol_penalty = _clip01(volatility / 0.05)

    alpha_score = _clip01(
        1.0
        - 0.35 * inventory_risk
        - 0.30 * migration_score
        - 0.20 * hedge_pressure
        - 0.15 * vol_penalty
    )
    risk_score = _clip01(1.0 - alpha_score)

    nq = len(qh)
    data_health = float(np.clip(nq / 20.0, 0.1, 1.0))
    confidence = float(data_health * (1.0 - 0.3 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    nested = {
        "inventory_pressure": float(inventory_pressure),
        "inventory_direction": inv_dir,
        "inventory_risk": float(inventory_risk),
        "avg_spread": float(avg_spread),
        "spread_widening": spread_widening,
        "migration_score": float(migration_score),
        "flow_imbalance": float(flow_imbalance),
        "hedge_pressure": float(hedge_pressure),
        "expected_mm_direction": exp_mm_dir,
        "vol_penalty": float(vol_penalty),
    }

    trade_permission = "ALLOW"
    reason = "mm_prediction_ok"

    if inventory_risk > 0.8:
        trade_permission = "BLOCK"
        reason = "inventory_risk_high"
    elif migration_score > 0.8:
        trade_permission = "BLOCK"
        reason = "migration_risk_high"

    return {
        "phase": 51,
        "module": "mm_prediction_engine",
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
