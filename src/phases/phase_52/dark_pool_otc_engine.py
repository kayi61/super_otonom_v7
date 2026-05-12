"""
Faz 52 — Dark pool & OTC: OTC gecikmesi, blok işlem etkisi, stablecoin mint/burn.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple

import numpy as np

_HALF_LIFE_MS = 45_000
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

    req = (
        "otc_trades",
        "block_trades",
        "stablecoin_mints",
        "current_price",
        "adv_usd",
    )
    for k in req:
        if k not in data:
            return False, f"missing_field:{k}"

    if not isinstance(data["otc_trades"], list):
        return False, "otc_trades_invalid"
    if not isinstance(data["block_trades"], list):
        return False, "block_trades_invalid"
    if not isinstance(data["stablecoin_mints"], list):
        return False, "stablecoin_mints_invalid"

    try:
        cp = float(data["current_price"])
        float(data["adv_usd"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    if cp <= 0.0:
        return False, "current_price_non_positive"

    for i, t in enumerate(data["otc_trades"]):
        if not isinstance(t, dict):
            return False, f"otc_not_dict:{i}"
        for k in ("size_usd", "side", "delay_ms"):
            if k not in t:
                return False, f"missing_otc_field:{k}:{i}"
        try:
            float(t["size_usd"])
            float(t["delay_ms"])
        except (TypeError, ValueError):
            return False, f"otc_numeric_error:{i}"
        if t["side"] not in ("buy", "sell"):
            return False, f"otc_side_invalid:{i}"

    for i, b in enumerate(data["block_trades"]):
        if not isinstance(b, dict):
            return False, f"block_not_dict:{i}"
        for k in ("size_usd", "side", "price_impact_pct"):
            if k not in b:
                return False, f"missing_block_field:{k}:{i}"
        try:
            float(b["size_usd"])
            float(b["price_impact_pct"])
        except (TypeError, ValueError):
            return False, f"block_numeric_error:{i}"
        if b["side"] not in ("buy", "sell"):
            return False, f"block_side_invalid:{i}"

    for i, m in enumerate(data["stablecoin_mints"]):
        if not isinstance(m, dict):
            return False, f"mint_not_dict:{i}"
        for k in ("amount_usd", "type", "ts"):
            if k not in m:
                return False, f"missing_mint_field:{k}:{i}"
        try:
            float(m["amount_usd"])
            float(m["ts"])
        except (TypeError, ValueError):
            return False, f"mint_numeric_error:{i}"
        if m["type"] not in ("mint", "burn"):
            return False, f"mint_type_invalid:{i}"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Dark pool / OTC analizi — Faz 52 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 52,
            "module": "dark_pool_otc_engine",
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

    otc = list(d["otc_trades"])
    total_otc_buy = 0.0
    total_otc_sell = 0.0
    for t in otc:
        sz = float(t["size_usd"])
        if t["side"] == "buy":
            total_otc_buy += sz
        else:
            total_otc_sell += sz

    denom_otc = max(total_otc_buy + total_otc_sell, _EPS)
    otc_imbalance = float((total_otc_buy - total_otc_sell) / denom_otc)
    otc_signal = _clip01((otc_imbalance + 1.0) / 2.0)

    if len(otc) > 0:
        delays = [float(x["delay_ms"]) for x in otc]
        avg_delay_ms = float(np.mean(np.asarray(delays, dtype=float)))
    else:
        avg_delay_ms = 0.0

    block_buy_impact = 0.0
    block_sell_impact = 0.0
    for b in d["block_trades"]:
        imp = float(b["price_impact_pct"])
        if b["side"] == "buy":
            block_buy_impact += imp
        else:
            block_sell_impact += imp

    net_block_impact = float(block_buy_impact - block_sell_impact)
    block_score = _clip01((net_block_impact + 5.0) / 10.0)

    total_mint = 0.0
    total_burn = 0.0
    for m in d["stablecoin_mints"]:
        amt = float(m["amount_usd"])
        if m["type"] == "mint":
            total_mint += amt
        else:
            total_burn += amt

    adv = float(d["adv_usd"])
    denom_adv = max(adv, _EPS)
    mint_pressure = float((total_mint - total_burn) / denom_adv)
    mint_score = _clip01((mint_pressure + 0.5) / 1.0)

    burn_dominance = bool(total_burn > total_mint * 2.0)

    alpha_score = _clip01(0.40 * otc_signal + 0.35 * block_score + 0.25 * mint_score)

    high_impact = bool(abs(net_block_impact) > 3.0)
    risk_score = _clip01(
        0.5 * (1.0 - alpha_score)
        + 0.3 * (1.0 if high_impact else 0.0)
        + 0.2 * (1.0 if burn_dominance else 0.0)
    )

    n_otc = len(otc)
    n_block = len(d["block_trades"])
    data_health = float(np.clip((n_otc + n_block) / 20.0, 0.1, 1.0))
    confidence = float(data_health * (1.0 - 0.3 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    nested = {
        "otc_signal": float(otc_signal),
        "otc_imbalance": float(otc_imbalance),
        "avg_delay_ms": float(avg_delay_ms),
        "block_score": float(block_score),
        "net_block_impact": float(net_block_impact),
        "mint_score": float(mint_score),
        "mint_pressure": float(mint_pressure),
        "total_mint": float(total_mint),
        "total_burn": float(total_burn),
        "burn_dominance": burn_dominance,
    }

    trade_permission = "ALLOW"
    reason = "dark_pool_otc_ok"

    if burn_dominance:
        trade_permission = "BLOCK"
        reason = "burn_dominance"
    elif risk_score > 0.7:
        trade_permission = "BLOCK"
        reason = "risk_threshold"

    return {
        "phase": 52,
        "module": "dark_pool_otc_engine",
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
