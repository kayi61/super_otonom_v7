"""
Faz 41 — Market Maker zekası: VPIN (toxic flow), quote stuffing, stop hunt, envanter baskısı.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_EPS = 1e-12
_VPIN_BLOCK = 0.70
_QS_BLOCK = 0.90
_RISK_BLOCK = 0.70
_QS_RATIO_CAP = 5.0
_HALF_LIFE_MS = 8000


def _clip01(x: float | np.floating) -> float:
    return float(np.clip(np.asarray(x, dtype=float), 0.0, 1.0))


def _now_ms() -> float:
    return float(time.time() * 1000.0)


def compute_vpin(buy_volumes: np.ndarray, sell_volumes: np.ndarray) -> float:
    """VPIN = mean(|buy - sell|) / mean(buy + sell) → [0, 1]."""
    b = np.asarray(buy_volumes, dtype=float).ravel()
    s = np.asarray(sell_volumes, dtype=float).ravel()
    if b.size == 0 or s.size == 0 or b.size != s.size:
        return 0.0
    num = np.mean(np.abs(b - s))
    den = np.mean(b + s) + _EPS
    return _clip01(num / den)


def compute_quote_stuffing(cancel_count: float, fill_count: float) -> float:
    """cancel/fill, normalize [0,1] assuming ratio cap QS_RATIO_CAP."""
    c = float(cancel_count)
    f = float(fill_count)
    ratio = c / max(f, _EPS)
    return _clip01(ratio / _QS_RATIO_CAP)


def compute_stop_hunt_risk(
    current_price: float,
    recent_low: float,
    recent_high: float,
    atr: float,
) -> float:
    """Dip/tepeye ATR'nin %30'u içinde yakınlık → [0, 1] yüksek = riskli."""
    cp = float(current_price)
    lo = float(recent_low)
    hi = float(recent_high)
    a = float(atr)
    band = 0.3 * max(a, _EPS)
    r_low = _clip01(1.0 - (cp - lo) / (band + _EPS))
    r_high = _clip01(1.0 - (hi - cp) / (band + _EPS))
    return _clip01(max(r_low, r_high))


def compute_inventory_pressure(mm_long_ratio: float) -> float:
    """abs(mm_long_ratio - 0.5) * 2 → [0, 1]."""
    mm = _clip01(mm_long_ratio)
    return _clip01(abs(mm - 0.5) * 2.0)


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    required = (
        "buy_volumes",
        "sell_volumes",
        "cancel_count",
        "fill_count",
        "current_price",
        "recent_low",
        "recent_high",
        "atr",
        "mm_long_ratio",
    )
    for k in required:
        if k not in data:
            return False, f"missing_field:{k}"

    bv = data["buy_volumes"]
    sv = data["sell_volumes"]
    if not isinstance(bv, (list, tuple)) or not isinstance(sv, (list, tuple)):
        return False, "volumes_not_list"
    if len(bv) == 0 or len(sv) == 0:
        return False, "empty_volume_series"
    if len(bv) != len(sv):
        return False, "volume_length_mismatch"

    try:
        fc = float(data["fill_count"])
        atr = float(data["atr"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    if fc <= 0:
        return False, "fill_count_non_positive"
    if atr <= 0:
        return False, "atr_non_positive"

    try:
        lo = float(data["recent_low"])
        hi = float(data["recent_high"])
    except (TypeError, ValueError):
        return False, "price_parse_error"

    if hi < lo:
        return False, "recent_high_below_low"

    return True, ""


def _pick_score_type(data_health: float, risk_score: float) -> str:
    if data_health < 0.42:
        return "QUALITY"
    if risk_score >= 0.72:
        return "RISK"
    return "ALPHA"


def analyze(market_data: dict | None) -> dict:
    """
    Market maker intelligence çıktısı — şema Faz 41 standart payload.

    ``analysis`` anahtarı iç içe metrikleri taşır (dış ``analysis`` parametresi yok;
    dönüş şeması gereği payload içinde ``analysis`` dict kullanılır).
    """
    ts = _now_ms()
    empty_analysis: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 41,
            "module": "market_maker_intelligence",
            "trade_permission": "BLOCK",
            "alpha_score": 0.0,
            "risk_score": 1.0,
            "score_type": "QUALITY",
            "confidence": 0.0,
            "data_health": 0.0,
            "event_ts": ts,
            "half_life_ms": _HALF_LIFE_MS,
            "analysis": empty_analysis,
            "reason": err,
        }

    assert market_data is not None
    d = market_data
    buy = np.asarray([float(x) for x in d["buy_volumes"]], dtype=float)
    sell = np.asarray([float(x) for x in d["sell_volumes"]], dtype=float)

    cancel_count = float(d["cancel_count"])
    fill_count = float(d["fill_count"])
    current_price = float(d["current_price"])
    recent_low = float(d["recent_low"])
    recent_high = float(d["recent_high"])
    atr = float(d["atr"])
    mm_long_ratio = float(d["mm_long_ratio"])

    vpin = compute_vpin(buy, sell)
    qs = compute_quote_stuffing(cancel_count, fill_count)
    stop_hunt = compute_stop_hunt_risk(current_price, recent_low, recent_high, atr)
    inv_p = compute_inventory_pressure(mm_long_ratio)

    risk_score = _clip01(
        0.40 * vpin + 0.25 * qs + 0.20 * stop_hunt + 0.15 * inv_p
    )
    alpha_score = _clip01(1.0 - risk_score)

    n = min(len(buy), len(sell))
    data_health = _clip01(n / 20.0)
    confidence = _clip01(data_health * (1.0 - 0.3 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission = "ALLOW"
    reason = "conditions_normal"

    if d.get("force_halt") is True:
        trade_permission = "HALT"
        reason = "force_halt"
    elif vpin >= _VPIN_BLOCK:
        trade_permission = "BLOCK"
        reason = "vpin_toxic_flow"
    elif qs >= _QS_BLOCK:
        trade_permission = "BLOCK"
        reason = "quote_stuffing"
    elif risk_score >= _RISK_BLOCK:
        trade_permission = "BLOCK"
        reason = "aggregate_risk"

    nested_analysis: Dict[str, Any] = {
        "vpin": _clip01(vpin),
        "quote_stuffing_score": _clip01(qs),
        "stop_hunt_risk": _clip01(stop_hunt),
        "inventory_pressure": _clip01(inv_p),
        "buy_bucket_count": int(len(buy)),
        "sell_bucket_count": int(len(sell)),
    }

    return {
        "phase": 41,
        "module": "market_maker_intelligence",
        "trade_permission": trade_permission,
        "alpha_score": alpha_score,
        "risk_score": risk_score,
        "score_type": score_type,
        "confidence": confidence,
        "data_health": data_health,
        "event_ts": ts,
        "half_life_ms": _HALF_LIFE_MS,
        "analysis": nested_analysis,
        "reason": reason,
    }
