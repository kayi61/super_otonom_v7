"""
Faz 54 — Kurumsal parmak izi: TWAP, iceberg derinlik davranışı, NAV marking baskısı.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np

_HALF_LIFE_MS = 20_000
_EPS = 1e-9
_NAV_WINDOW_MS = 30 * 60 * 1000


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

    for k in (
        "trades",
        "order_book_snapshots",
        "current_price",
        "session_end_ts",
        "current_ts",
    ):
        if k not in data:
            return False, f"missing_field:{k}"

    if not isinstance(data["trades"], list):
        return False, "trades_invalid"
    if not isinstance(data["order_book_snapshots"], list):
        return False, "order_book_snapshots_invalid"

    if len(data["trades"]) < 2:
        return False, "trades_insufficient"

    if len(data["order_book_snapshots"]) < 1:
        return False, "order_book_snapshots_empty"

    try:
        cp = float(data["current_price"])
        float(data["session_end_ts"])
        float(data["current_ts"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    if cp <= 0.0:
        return False, "current_price_non_positive"

    for i, t in enumerate(data["trades"]):
        if not isinstance(t, dict):
            return False, f"trade_not_dict:{i}"
        for k in ("size", "price", "ts", "side"):
            if k not in t:
                return False, f"missing_trade_field:{k}:{i}"
        try:
            float(t["size"])
            float(t["price"])
            float(t["ts"])
        except (TypeError, ValueError):
            return False, f"trade_numeric_error:{i}"
        if t["side"] not in ("buy", "sell"):
            return False, f"trade_side_invalid:{i}"

    for i, s in enumerate(data["order_book_snapshots"]):
        if not isinstance(s, dict):
            return False, f"snapshot_not_dict:{i}"
        for k in ("ts", "best_bid", "best_ask", "bid_depth", "ask_depth"):
            if k not in s:
                return False, f"missing_snapshot_field:{k}:{i}"
        try:
            float(s["ts"])
            float(s["best_bid"])
            float(s["best_ask"])
            float(s["bid_depth"])
            float(s["ask_depth"])
        except (TypeError, ValueError):
            return False, f"snapshot_numeric_error:{i}"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Kurumsal parmak izi analizi — Faz 54 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 54,
            "module": "institutional_fingerprint_engine",
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

    trades: List[dict] = list(d["trades"])
    ts_sorted = sorted(trades, key=lambda x: float(x["ts"]))
    time_gaps = [
        float(ts_sorted[i + 1]["ts"]) - float(ts_sorted[i]["ts"]) for i in range(len(ts_sorted) - 1)
    ]
    gaps_arr = np.asarray(time_gaps, dtype=float)
    gap_mean = float(np.mean(gaps_arr))
    gap_std = float(np.std(gaps_arr))
    regularity_score = _clip01(1.0 - gap_std / max(gap_mean, _EPS))

    sizes = np.asarray([float(t["size"]) for t in ts_sorted], dtype=float)
    size_mean = float(np.mean(sizes))
    size_std = float(np.std(sizes))
    size_regularity = _clip01(1.0 - size_std / max(size_mean, _EPS))

    twap_fingerprint = float((regularity_score + size_regularity) / 2.0)

    obs = list(d["order_book_snapshots"])
    depth_changes = [
        abs(float(obs[i]["bid_depth"]) - float(obs[i - 1]["bid_depth"])) for i in range(1, len(obs))
    ]
    avg_depth_change = float(np.mean(depth_changes)) if depth_changes else 0.0
    bid_depths = [float(s["bid_depth"]) for s in obs]
    mean_bid_depth = float(np.mean(np.asarray(bid_depths, dtype=float)))
    iceberg_score = _clip01(avg_depth_change / max(mean_bid_depth, _EPS))

    session_end = float(d["session_end_ts"])
    current_ts_in = float(d["current_ts"])
    time_to_close_ms = float(max(session_end - current_ts_in, 0.0))
    nav_window = bool(time_to_close_ms < _NAV_WINDOW_MS)
    if nav_window:
        nav_pressure = _clip01(1.0 - time_to_close_ms / float(_NAV_WINDOW_MS))
    else:
        nav_pressure = 0.0

    buy_volume = 0.0
    sell_volume = 0.0
    for t in ts_sorted:
        sz = float(t["size"])
        if t["side"] == "buy":
            buy_volume += sz
        else:
            sell_volume += sz

    denom_vol = max(buy_volume + sell_volume, _EPS)
    inst_bias = float((buy_volume - sell_volume) / denom_vol)

    institutional_score = float(0.5 * twap_fingerprint + 0.3 * iceberg_score + 0.2 * nav_pressure)

    bias_term = (inst_bias + 1.0) / 2.0
    alpha_score = _clip01(0.4 * twap_fingerprint + 0.3 * bias_term + 0.3 * (1.0 - nav_pressure))
    risk_score = _clip01(0.4 * nav_pressure + 0.3 * iceberg_score + 0.3 * (1.0 - bias_term))

    n_tr = len(trades)
    data_health = float(np.clip(n_tr / 30.0, 0.1, 1.0))
    confidence = float(data_health * (1.0 - 0.3 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    nested = {
        "twap_fingerprint": float(twap_fingerprint),
        "regularity_score": float(regularity_score),
        "size_regularity": float(size_regularity),
        "iceberg_score": float(iceberg_score),
        "nav_pressure": float(nav_pressure),
        "nav_window": nav_window,
        "institutional_score": float(institutional_score),
        "inst_bias": float(inst_bias),
        "buy_volume": float(buy_volume),
        "sell_volume": float(sell_volume),
    }

    trade_permission = "ALLOW"
    reason = "institutional_fingerprint_ok"

    if nav_pressure > 0.7:
        trade_permission = "BLOCK"
        reason = "nav_marking_high"
    elif risk_score > 0.7:
        trade_permission = "BLOCK"
        reason = "risk_threshold"

    return {
        "phase": 54,
        "module": "institutional_fingerprint_engine",
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
